import base64
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Select, and_, or_, select

from app.api.deps import Db, OptionalUser, UrlBuilder, Urls
from app.db.models import Clip, Like, Session, User
from app.schemas import FeedOut
from app.services import counters, youtube
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


async def clip_page(db, stmt: Select, limit: int, cursor: str | None, urls: UrlBuilder, me) -> FeedOut:
    """Newest-first keyset pagination over a select(Clip, Session, User) statement.

    Age-restricted clips are excluded unless the viewer is a signed-in adult
    account — applied as a SQL predicate (not a post-filter) so pagination
    counts stay correct."""
    if not (me is not None and me.is_adult):
        stmt = stmt.where(Clip.age_restricted.is_(False))
    if cursor:
        ts, cid = decode_cursor(cursor)
        stmt = stmt.where(or_(Clip.created_at < ts, and_(Clip.created_at == ts, Clip.id < cid)))
    rows = (await db.execute(stmt.order_by(Clip.created_at.desc(), Clip.id.desc()).limit(limit + 1))).all()
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
    next_cursor = encode_cursor(rows[-1].Clip.created_at, rows[-1].Clip.id) if has_more and rows else None
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
) -> FeedOut:
    """Published clips, newest first."""
    stmt = base_clip_query()
    if game:
        stmt = stmt.where(Session.game.ilike(game))
    return await clip_page(db, stmt, limit, cursor, urls, me)
