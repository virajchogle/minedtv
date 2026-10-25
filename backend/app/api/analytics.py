"""Creator analytics: a user's views, likes, comments and followers over time, per clip.

Likes, comments and follows are counted from their own rows (each has created_at); views come
from clip_daily_views plus whatever Redis hasn't flushed yet. Days are UTC.
"""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Date, cast, func, select

from app.api.deps import Db, OptionalUser, Urls
from app.db.models import Clip, ClipDailyViews, Comment, Follow, Like, Session
from app.schemas import (
    AnalyticsDayOut,
    AnalyticsOut,
    AnalyticsTotalsOut,
    ClipAnalyticsOut,
)
from app.services import counters, youtube
from app.services.clip_virality import clip_virality_summary
from app.services.serialize import clip_out
from app.services.social import comment_counts

router = APIRouter(prefix="/users", tags=["analytics"])

def _utc_day(column):
    return cast(func.timezone("UTC", column), Date)


async def _per_clip_day(db, model, clip_ids: list[uuid.UUID], since: date) -> dict[tuple[uuid.UUID, date], int]:
    """Row counts of likes or comments per (clip, day)."""
    if not clip_ids:
        return {}
    day = _utc_day(model.created_at)
    rows = await db.execute(
        select(model.clip_id, day, func.count())
        .where(model.clip_id.in_(clip_ids), model.created_at >= since)
        .group_by(model.clip_id, day)
    )
    return {(cid, d): n for cid, d, n in rows}


@router.get("/{user_id}/analytics", response_model=AnalyticsOut)
async def user_analytics(
    user_id: uuid.UUID,
    db: Db,
    urls: Urls,
    me: OptionalUser,
    days: int = Query(default=30, ge=7, le=180),
) -> AnalyticsOut:
    """Your own analytics for the last `days` days (and the `days` before, for comparison)."""
    if me is None or me.id != user_id:
        raise HTTPException(403, "Analytics are only visible to their owner")

    end = counters.today()
    start = end - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)

    rows = (
        await db.execute(
            select(Clip, Session)
            .join(Session, Session.id == Clip.session_id)
            .where(Clip.user_id == user_id, Clip.status == "ready")
            .order_by(Clip.created_at.desc())
        )
    ).all()
    clips = [r.Clip for r in rows]
    ids = [c.id for c in clips]

    views: dict[tuple[uuid.UUID, date], int] = {}
    if ids:
        for cid, d, n in await db.execute(
            select(ClipDailyViews.clip_id, ClipDailyViews.day, ClipDailyViews.views).where(
                ClipDailyViews.clip_id.in_(ids), ClipDailyViews.day >= prev_start
            )
        ):
            views[(cid, d)] = n
    for key, n in (await counters.pending_daily_views(set(ids))).items():
        views[key] = views.get(key, 0) + n
    likes = await _per_clip_day(db, Like, ids, prev_start)
    comments = await _per_clip_day(db, Comment, ids, prev_start)

    follow_day = _utc_day(Follow.created_at)
    follows = {
        d: n
        for d, n in await db.execute(
            select(follow_day, func.count())
            .where(Follow.followee_id == user_id, Follow.created_at >= prev_start)
            .group_by(follow_day)
        )
    }
    follower_count = await db.scalar(select(func.count()).select_from(Follow).where(Follow.followee_id == user_id)) or 0
    tracking_since = (
        await db.scalar(select(func.min(ClipDailyViews.day)).where(ClipDailyViews.clip_id.in_(ids))) if ids else None
    ) or (min((d for _, d in views), default=None))

    def by_day(series: dict[tuple[uuid.UUID, date], int]) -> dict[date, int]:
        out: dict[date, int] = {}
        for (_, d), n in series.items():
            out[d] = out.get(d, 0) + n
        return out

    v_day, l_day, c_day = by_day(views), by_day(likes), by_day(comments)

    def totals(lo: date, hi: date) -> AnalyticsTotalsOut:
        def total(series: dict[date, int]) -> int:
            return sum(n for d, n in series.items() if lo <= d <= hi)

        return AnalyticsTotalsOut(views=total(v_day), likes=total(l_day), comments=total(c_day), new_followers=total(follows))

    daily = [
        AnalyticsDayOut(
            day=d,
            views=v_day.get(d, 0),
            likes=l_day.get(d, 0),
            comments=c_day.get(d, 0),
            new_followers=follows.get(d, 0),
        )
        for d in (start + timedelta(days=i) for i in range(days))
    ]

    pending = await counters.pending(ids)
    all_comments = await comment_counts(db, ids)
    on_youtube = await youtube.posted_urls(db, ids)
    virality = [await clip_virality_summary(db, c) for c in clips]

    def in_period(series: dict[tuple[uuid.UUID, date], int], cid: uuid.UUID) -> int:
        return sum(n for (c, d), n in series.items() if c == cid and d >= start)

    clip_rows = [
        ClipAnalyticsOut(
            clip=clip_out(r.Clip, r.Session, me, urls, pending[r.Clip.id], None, all_comments[r.Clip.id], on_youtube.get(r.Clip.id)),
            period_views=in_period(views, r.Clip.id),
            period_likes=in_period(likes, r.Clip.id),
            period_comments=in_period(comments, r.Clip.id),
            virality=v,
        )
        for r, v in zip(rows, virality, strict=True)
    ]

    lifetime = AnalyticsTotalsOut(
        views=sum(c.clip.view_count for c in clip_rows),
        likes=sum(c.clip.like_count for c in clip_rows),
        comments=sum(all_comments.values()),
        new_followers=follower_count,
    )
    return AnalyticsOut(
        days=days,
        start=start,
        end=end,
        tracking_since=tracking_since,
        lifetime=lifetime,
        period=totals(start, end),
        previous_period=totals(prev_start, start - timedelta(days=1)),
        follower_count=follower_count,
        daily=daily,
        clips=clip_rows,
    )
