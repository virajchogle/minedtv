"""Comments, follows and notifications.

Everything here works inside the caller's transaction (no commits), so an action and the
notification it causes are written together or not at all. Counts are computed from the
rows themselves rather than kept in counters, so they can't drift.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clip, Comment, Follow, Notification, NotificationType

COMMENT_MAX = 1000


class SocialError(ValueError):
    """A request that breaks a rule (bad parent comment, following yourself, ...)."""


# ---------------------------------------------------------------- notifications


async def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    actor_id: uuid.UUID | None = None,
    clip_id: uuid.UUID | None = None,
    comment_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    data: dict | None = None,
    once: bool = False,
) -> bool:
    """Record a notification for user_id. Never notifies people about their own actions.

    once=True skips it if this actor already caused the same notification about the same
    clip/session (so like/unlike/like or unfollow/follow doesn't spam). Returns whether one
    was added.
    """
    if actor_id is not None and actor_id == user_id:
        return False
    if once:
        dup = await db.scalar(
            select(
                exists().where(
                    Notification.user_id == user_id,
                    Notification.type == type,
                    Notification.actor_id.is_(None) if actor_id is None else Notification.actor_id == actor_id,
                    Notification.clip_id.is_(None) if clip_id is None else Notification.clip_id == clip_id,
                    Notification.session_id.is_(None) if session_id is None else Notification.session_id == session_id,
                )
            )
        )
        if dup:
            return False
    db.add(
        Notification(
            user_id=user_id,
            actor_id=actor_id,
            type=type,
            clip_id=clip_id,
            comment_id=comment_id,
            session_id=session_id,
            data=data or {},
        )
    )
    return True


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    ) or 0


# ---------------------------------------------------------------- comments


def clean_body(body: str) -> str:
    text = (body or "").strip()
    if not text:
        raise SocialError("Comment is empty")
    if len(text) > COMMENT_MAX:
        raise SocialError(f"Comment is longer than {COMMENT_MAX} characters")
    return text


async def add_comment(
    db: AsyncSession, clip: Clip, author_id: uuid.UUID, body: str, parent_id: uuid.UUID | None = None
) -> Comment:
    """Add a comment (or a reply) and notify the clip owner and the replied-to author."""
    text = clean_body(body)
    parent = None
    if parent_id is not None:
        parent = await db.get(Comment, parent_id)
        if parent is None or parent.clip_id != clip.id:
            raise SocialError("The comment you're replying to isn't on this clip")
        # One level of threading: replying to a reply attaches to its top-level comment.
        if parent.parent_id is not None:
            parent = await db.get(Comment, parent.parent_id)
    comment = Comment(clip_id=clip.id, user_id=author_id, parent_id=parent.id if parent else None, body=text)
    db.add(comment)
    await db.flush()

    preview = {"preview": text[:140]}
    notified = set()
    if parent is not None and parent.user_id != author_id:
        await notify(db, user_id=parent.user_id, actor_id=author_id, type=NotificationType.REPLY,
                     clip_id=clip.id, comment_id=comment.id, data=preview)
        notified.add(parent.user_id)
    if clip.user_id not in notified:
        await notify(db, user_id=clip.user_id, actor_id=author_id, type=NotificationType.COMMENT,
                     clip_id=clip.id, comment_id=comment.id, data=preview)
    return comment


async def comment_counts(db: AsyncSession, clip_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
    ids = list(clip_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(Comment.clip_id, func.count()).where(Comment.clip_id.in_(ids)).group_by(Comment.clip_id)
    )
    counts = {cid: n for cid, n in rows}
    return {cid: counts.get(cid, 0) for cid in ids}


async def reply_counts(db: AsyncSession, comment_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
    ids = list(comment_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(Comment.parent_id, func.count()).where(Comment.parent_id.in_(ids)).group_by(Comment.parent_id)
    )
    counts = {cid: n for cid, n in rows}
    return {cid: counts.get(cid, 0) for cid in ids}


# ---------------------------------------------------------------- follows


async def follow(db: AsyncSession, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
    """Follow someone. Idempotent; returns True if this created the follow."""
    if follower_id == followee_id:
        raise SocialError("You can't follow yourself")
    created = await db.execute(
        pg_insert(Follow)
        .values(follower_id=follower_id, followee_id=followee_id)
        .on_conflict_do_nothing()
        .returning(Follow.follower_id)
    )
    if created.first() is None:
        return False
    await notify(db, user_id=followee_id, actor_id=follower_id, type=NotificationType.FOLLOW, once=True)
    return True


async def unfollow(db: AsyncSession, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
    gone = await db.execute(
        delete(Follow)
        .where(Follow.follower_id == follower_id, Follow.followee_id == followee_id)
        .returning(Follow.follower_id)
    )
    return gone.first() is not None


async def follow_counts(db: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    """(followers, following)."""
    followers = await db.scalar(select(func.count()).select_from(Follow).where(Follow.followee_id == user_id))
    following = await db.scalar(select(func.count()).select_from(Follow).where(Follow.follower_id == user_id))
    return followers or 0, following or 0


async def following_set(db: AsyncSession, follower_id: uuid.UUID, user_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    ids = list(user_ids)
    if not ids:
        return set()
    rows = await db.scalars(
        select(Follow.followee_id).where(Follow.follower_id == follower_id, Follow.followee_id.in_(ids))
    )
    return set(rows)
