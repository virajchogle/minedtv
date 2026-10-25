import base64
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Float, Select, and_, cast, func, or_, select

from app.api.deps import Db, OptionalUser, UrlBuilder, Urls
from app.db.models import Clip, Comment, FrameViralityScore, Like, Session, User
from app.schemas import ClipFormat, FeedOut, FeedSort
from app.services import counters, youtube
from app.services.formats import format_filter
from app.services.serialize import clip_out
from app.services.social import comment_counts

router = APIRouter(tags=["feed"])


def encode_cursor(created_at: datetime, clip_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{clip_id}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        ts, cid = raw.split("|")
        return datetime.fromisoformat(ts), uuid.UUID(cid)
    except Exception as e:
        raise HTTPException(422, "Invalid cursor") from e


def rank_score():
    """"top" ranking: engagement plus the clip's strongest frame-virality moment, decayed by age
    so the swipe feed doesn't freeze on the same old hits."""
    virality = (
        select(func.max(FrameViralityScore.score))
        .where(
            FrameViralityScore.session_id == Clip.session_id,
            FrameViralityScore.t_ms.between(Clip.start_ms, Clip.end_ms),
        )
        .scalar_subquery()
    )
    comments = select(func.count(Comment.id)).where(Comment.clip_id == Clip.id).scalar_subquery()
    age_h = func.extract("epoch", func.now() - func.coalesce(Clip.published_at, Clip.created_at)) / 3600
    engagement = 1 + Clip.like_count * 4 + comments * 6 + Clip.view_count * 0.05 + func.coalesce(virality, 0) * 25
    return cast(engagement, Float) / func.power(func.greatest(age_h, 0) + 2, 1.3)


def _encode_offset(offset: int) -> str:
    return base64.urlsafe_b64encode(f"top|{offset}".encode()).decode().rstrip("=")


def _decode_offset(cursor: str) -> int:
    try:
        tag, offset = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode().split("|")
        if tag != "top" or int(offset) < 0:
            raise ValueError(tag)
        return int(offset)
    except Exception as e:
        raise HTTPException(422, "Invalid cursor") from e


async def clip_page(
    db,
    stmt: Select,
    limit: int,
    cursor: str | None,
    urls: UrlBuilder,
    me,
    fmt: ClipFormat | None = None,
    sort: FeedSort = "new",
) -> FeedOut:
    """Keyset pagination over a select(Clip, Session, User) statement, newest first; or, with
    sort="top", ranked by rank_score() with an offset cursor (ranks drift with time, so a keyset
    can't hold). fmt keeps only short or long clips.

    Age-restricted clips are excluded unless the viewer is a signed-in adult
    account. Both filters are SQL predicates (not post-filters) so pages stay full."""
    if not (me is not None and me.is_adult):
        stmt = stmt.where(Clip.age_restricted.is_(False))
    if (cond := format_filter(fmt)) is not None:
        stmt = stmt.where(cond)
    if sort == "top":
        offset = _decode_offset(cursor) if cursor else 0
        stmt = stmt.order_by(rank_score().desc(), Clip.id.desc()).offset(offset)
    else:
        if cursor:
            ts, cid = decode_cursor(cursor)
            stmt = stmt.where(or_(Clip.created_at < ts, and_(Clip.created_at == ts, Clip.id < cid)))
        stmt = stmt.order_by(Clip.created_at.desc(), Clip.id.desc())
    rows = (await db.execute(stmt.limit(limit + 1))).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    ids = [r.Clip.id for r in rows]
    pending = await counters.pending(ids)
    liked = None
    if me is not None and ids:
        liked = set(await db.scalars(select(Like.clip_id).where(Like.user_id == me.id, Like.clip_id.in_(ids))))
    comments = await comment_counts(db, ids)
    on_youtube = await youtube.posted_urls(db, ids)
    items = [
        clip_out(r.Clip, r.Session, r.User, urls, pending[r.Clip.id], liked, comments[r.Clip.id], on_youtube.get(r.Clip.id))
        for r in rows
    ]
    if not (has_more and rows):
        next_cursor = None
    elif sort == "top":
        next_cursor = _encode_offset(offset + len(rows))
    else:
        next_cursor = encode_cursor(rows[-1].Clip.created_at, rows[-1].Clip.id)
    return FeedOut(items=items, next_cursor=next_cursor)


def base_clip_query(states: tuple[str, ...] = ("published",)) -> Select:
    return (
        select(Clip, Session, User)
        .join(Session, Session.id == Clip.session_id)
        .join(User, User.id == Clip.user_id)
        .where(Clip.status == "ready", Clip.publish_state.in_(states))
    )


@router.get("/feed", response_model=FeedOut)
async def feed(
    db: Db,
    urls: Urls,
    me: OptionalUser,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    game: str | None = Query(default=None, description="Only clips from this game"),
    format: ClipFormat | None = Query(default=None, description="short (Reels) or long (Home); omit for both"),
    sort: FeedSort = Query(default="new", description="new = newest first; top = ranked by engagement and virality"),
) -> FeedOut:
    """Published clips, newest first (or ranked with sort=top)."""
    stmt = base_clip_query()
    if game:
        stmt = stmt.where(Session.game.ilike(game))
    return await clip_page(db, stmt, limit, cursor, urls, me, format, sort)
