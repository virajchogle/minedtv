"""The acting user's notifications (Inbox)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import aliased

from app.api.deps import CurrentUser, Db
from app.api.feed import decode_cursor, encode_cursor
from app.db.models import Clip, Notification, NotificationType, User
from app.schemas import MarkReadIn, NotificationClip, NotificationOut, NotificationsPage, UnreadCountOut, UserOut
from app.services import social
from app.services.serialize import url_or_none

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _message(n: Notification, actor: User | None, clip: Clip | None) -> str:
    who = actor.username if actor else "Someone"
    title = f" “{clip.title}”" if clip and clip.title else ""
    data = n.data or {}
    match n.type:
        case NotificationType.LIKE:
            return f"{who} liked your clip{title}"
        case NotificationType.COMMENT:
            return f"{who} commented on your clip{title}: {data.get('preview', '')}".rstrip(": ")
        case NotificationType.REPLY:
            return f"{who} replied to your comment: {data.get('preview', '')}".rstrip(": ")
        case NotificationType.FOLLOW:
            return f"{who} started following you"
        case NotificationType.UPLOAD_READY:
            n_clips = len(data.get("clip_ids", []))
            name = f" “{data['title']}”" if data.get("title") else ""
            return f"Your upload{name} is ready" + (f" ({n_clips} clips, saved as drafts)" if n_clips > 1 else "")
        case NotificationType.VIRALITY_READY:
            score = data.get("virality_score")
            verdict = data.get("verdict")
            detail = f": {round(score)} ({verdict})" if score is not None and verdict else ""
            return f"Virality check for{title or ' your clip'} is ready{detail}"
    return "New activity"


@router.get("", response_model=NotificationsPage)
async def list_notifications(
    me: CurrentUser,
    db: Db,
    cursor: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    unread_only: bool = False,
) -> NotificationsPage:
    """Your notifications, newest first."""
    actor = aliased(User)
    stmt = (
        select(Notification, actor, Clip)
        .outerjoin(actor, actor.id == Notification.actor_id)
        .outerjoin(Clip, Clip.id == Notification.clip_id)
        .where(Notification.user_id == me.id)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if cursor:
        ts, nid = decode_cursor(cursor)
        stmt = stmt.where(or_(Notification.created_at < ts, and_(Notification.created_at == ts, Notification.id < nid)))
    rows = (await db.execute(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1))).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = []
    for n, a, clip in rows:
        items.append(
            NotificationOut(
                id=n.id,
                type=n.type,
                message=_message(n, a, clip),
                actor=UserOut.model_validate(a) if a else None,
                clip=NotificationClip(id=clip.id, title=clip.title, thumbnail_url=url_or_none(clip.thumbnail_key))
                if clip
                else None,
                comment_id=n.comment_id,
                session_id=n.session_id,
                data=n.data or {},
                read=n.read_at is not None,
                created_at=n.created_at,
            )
        )
    next_cursor = encode_cursor(rows[-1][0].created_at, rows[-1][0].id) if has_more and rows else None
    return NotificationsPage(items=items, next_cursor=next_cursor, unread_count=await social.unread_count(db, me.id))


@router.get("/unread-count", response_model=UnreadCountOut)
async def get_unread_count(me: CurrentUser, db: Db) -> UnreadCountOut:
    """For the Inbox badge. Cheap enough to poll."""
    return UnreadCountOut(unread_count=await social.unread_count(db, me.id))


@router.post("/read", response_model=UnreadCountOut)
async def mark_read(body: MarkReadIn, me: CurrentUser, db: Db) -> UnreadCountOut:
    """Mark some notifications (ids) or all of them read."""
    stmt = update(Notification).where(Notification.user_id == me.id, Notification.read_at.is_(None))
    if not body.all:
        if not body.ids:
            return UnreadCountOut(unread_count=await social.unread_count(db, me.id))
        stmt = stmt.where(Notification.id.in_(body.ids))
    await db.execute(stmt.values(read_at=datetime.now(UTC)))
    await db.commit()
    return UnreadCountOut(unread_count=await social.unread_count(db, me.id))
