"""Creator analytics: daily views (flushed + pending), likes, comments and followers over time."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import analytics as analytics_api
from app.db.models import ClipDailyViews, Comment, Follow, Like, User
from app.services import counters
from app.services.redis import get_redis
from tests.test_pipeline_e2e import migrated_db, sessionmaker  # noqa: F401  (fixtures)
from tests.test_publish_flow import _draft_clip, _Urls


@pytest.fixture
async def clean_counters(sessionmaker, monkeypatch):  # noqa: F811
    # The flush writes through the app's sessionmaker; point it at the test database.
    monkeypatch.setattr(counters, "get_sessionmaker", lambda: sessionmaker)
    r = get_redis()
    keys = (counters.DAILY_VIEWS_KEY, counters.VIEWS_KEY, counters.LIKES_KEY)
    await r.delete(*keys)
    yield
    await r.delete(*keys)


async def test_analytics_counts_by_day_and_period(sessionmaker, clean_counters):  # noqa: F811
    owner, clip = await _draft_clip(sessionmaker)
    today = counters.today()
    week_ago = datetime.now(UTC) - timedelta(days=7)
    async with sessionmaker() as db:
        fans = [User(username=f"fan_{uuid.uuid4().hex[:6]}") for _ in range(3)]
        db.add_all(fans)
        await db.flush()
        db.add_all([
            ClipDailyViews(clip_id=clip.id, day=today, views=5),
            ClipDailyViews(clip_id=clip.id, day=today - timedelta(days=7), views=2),
            ClipDailyViews(clip_id=clip.id, day=today - timedelta(days=40), views=9),  # previous period
            Like(user_id=fans[0].id, clip_id=clip.id),
            Like(user_id=fans[1].id, clip_id=clip.id, created_at=week_ago),
            Comment(clip_id=clip.id, user_id=fans[2].id, body="gg"),
            Follow(follower_id=fans[0].id, followee_id=owner.id),
        ])
        await db.commit()
    await counters.incr_view(clip.id)  # pending in Redis, not flushed yet

    async with sessionmaker() as db:
        me = await db.get(User, owner.id)
        out = await analytics_api.user_analytics(owner.id, db, _Urls(), me, days=30)

    assert out.days == 30 and len(out.daily) == 30 and out.daily[-1].day == today
    assert (out.daily[-1].views, out.daily[-1].likes, out.daily[-1].comments, out.daily[-1].new_followers) == (6, 1, 1, 1)
    assert out.daily[-8].views == 2 and out.daily[-8].likes == 1
    assert (out.period.views, out.period.likes, out.period.comments, out.period.new_followers) == (8, 2, 1, 1)
    assert out.previous_period.views == 9
    assert out.follower_count == 1 and out.lifetime.comments == 1
    [row] = out.clips
    assert row.clip.id == clip.id and row.period_views == 8 and row.period_likes == 2
    assert row.virality.status == "none" and row.virality.score is None

    # The flush moves pending daily views into the table without double counting.
    await counters.flush()
    async with sessionmaker() as db:
        stored = await db.scalar(select(ClipDailyViews.views).where(ClipDailyViews.clip_id == clip.id, ClipDailyViews.day == today))
        assert stored == 6
        out = await analytics_api.user_analytics(owner.id, db, _Urls(), await db.get(User, owner.id), days=30)
    assert out.daily[-1].views == 6


async def test_analytics_owner_only(sessionmaker):  # noqa: F811
    owner, _ = await _draft_clip(sessionmaker)
    async with sessionmaker() as db:
        stranger = User(username=f"x_{uuid.uuid4().hex[:6]}")
        db.add(stranger)
        await db.commit()
        for who in (None, stranger):
            with pytest.raises(HTTPException) as e:
                await analytics_api.user_analytics(owner.id, db, _Urls(), who, days=30)
            assert e.value.status_code == 403


class _Req:
    def __init__(self, ip="203.0.113.7"):
        self.headers = {"x-forwarded-for": f"{ip}, 10.0.0.1"}
        self.client = None


async def test_views_count_once_per_viewer_and_not_for_owner(sessionmaker, clean_counters):  # noqa: F811
    from app.api import clips as clips_api

    owner, clip = await _draft_clip(sessionmaker)
    async with sessionmaker() as db:
        clip_row = await db.get(type(clip), clip.id)
        clip_row.publish_state = "published"
        fan = User(username=f"fan_{uuid.uuid4().hex[:6]}")
        db.add(fan)
        await db.commit()
        r = get_redis()
        async for k in r.scan_iter(f"viewed:{clip.id}:*"):
            await r.delete(k)

        for _ in range(3):  # a refreshing fan counts once
            await clips_api.view(clip.id, _Req(), db, fan, None)
        await clips_api.view(clip.id, _Req(), db, owner, None)  # owners don't count
        await clips_api.view(clip.id, _Req(), db, None, "browser-a")  # two anonymous browsers
        await clips_api.view(clip.id, _Req(), db, None, "browser-a")
        await clips_api.view(clip.id, _Req(), db, None, "browser-b")
        await clips_api.view(clip.id, _Req("198.51.100.1"), db, None, None)  # no ID: by IP
        await clips_api.view(clip.id, _Req("198.51.100.1"), db, None, None)

    assert (await counters.pending([clip.id]))[clip.id][0] == 4
