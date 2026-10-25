"""Comments, follows and notifications against real Postgres (same setup as the pipeline e2e test)."""

import uuid

import pytest
from sqlalchemy import func, select

from app.db.models import Clip, Comment, Follow, Notification, NotificationType, Session, SessionStatus, User
from app.services import social
from tests.test_pipeline_e2e import migrated_db, sessionmaker  # noqa: F401  (fixtures)


async def _users(sm, *names):
    async with sm() as db:
        users = [User(username=f"{n}_{uuid.uuid4().hex[:6]}") for n in names]
        db.add_all(users)
        await db.commit()
        return users


async def _clip(sm, owner: User) -> Clip:
    async with sm() as db:
        sid = uuid.uuid4()
        db.add(Session(id=sid, user_id=owner.id, storage_prefix=f"sessions/{sid}", source_key="x", status=SessionStatus.READY,
                       duration_ms=10_000))
        await db.flush()  # no ORM relationship, so insert the session before the clip explicitly
        clip = Clip(session_id=sid, user_id=owner.id, start_ms=0, end_ms=10_000, publish_state="published", status="ready")
        db.add(clip)
        await db.commit()
        return clip


async def _notes(sm, user: User) -> list[Notification]:
    async with sm() as db:
        return list((await db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at))).all())


async def test_comments_replies_and_their_notifications(sessionmaker):  # noqa: F811
    owner, fan, other = await _users(sessionmaker, "owner", "fan", "other")
    clip = await _clip(sessionmaker, owner)

    async with sessionmaker() as db:
        top = await social.add_comment(db, clip, fan.id, "  that flick was disgusting  ")
        await db.commit()
    assert top.body == "that flick was disgusting"  # trimmed
    notes = await _notes(sessionmaker, owner)
    assert [(n.type, n.actor_id, n.comment_id) for n in notes] == [(NotificationType.COMMENT, fan.id, top.id)]
    assert notes[0].data["preview"] == "that flick was disgusting"

    async with sessionmaker() as db:
        reply = await social.add_comment(db, clip, other.id, "agreed", parent_id=top.id)
        # Replying to a reply attaches to the top-level comment (one level of threading).
        nested = await social.add_comment(db, clip, owner.id, "thanks both", parent_id=reply.id)
        await db.commit()
    assert reply.parent_id == top.id and nested.parent_id == top.id

    fan_notes = await _notes(sessionmaker, fan)
    assert [n.type for n in fan_notes] == [NotificationType.REPLY, NotificationType.REPLY]
    owner_types = [n.type for n in await _notes(sessionmaker, owner)]
    # owner: fan's comment + other's reply on their clip; their own reply notifies nobody about themselves
    assert owner_types == [NotificationType.COMMENT, NotificationType.COMMENT]

    async with sessionmaker() as db:
        counts = await social.comment_counts(db, [clip.id])
        replies = await social.reply_counts(db, [top.id])
    assert counts == {clip.id: 3} and replies == {top.id: 2}


async def test_comment_rules(sessionmaker):  # noqa: F811
    owner, fan = await _users(sessionmaker, "owner", "fan")
    clip_a, clip_b = await _clip(sessionmaker, owner), await _clip(sessionmaker, owner)
    async with sessionmaker() as db:
        on_b = await social.add_comment(db, clip_b, fan.id, "hi")
        await db.commit()
        with pytest.raises(social.SocialError, match="empty"):
            await social.add_comment(db, clip_a, fan.id, "   ")
        with pytest.raises(social.SocialError, match="longer"):
            await social.add_comment(db, clip_a, fan.id, "x" * 1001)
        with pytest.raises(social.SocialError, match="isn't on this clip"):
            await social.add_comment(db, clip_a, fan.id, "wrong clip", parent_id=on_b.id)
    # Commenting on your own clip notifies nobody.
    async with sessionmaker() as db:
        await social.add_comment(db, clip_a, owner.id, "first!")
        await db.commit()
    assert [n.type for n in await _notes(sessionmaker, owner)] == [NotificationType.COMMENT]  # only fan's on clip_b

    # Deleting a comment deletes its replies (cascade).
    async with sessionmaker() as db:
        reply = await social.add_comment(db, clip_b, owner.id, "reply", parent_id=on_b.id)
        await db.commit()
        await db.delete(await db.get(Comment, on_b.id))
        await db.commit()
    async with sessionmaker() as db:  # fresh session: the cascade happens in the database
        assert await db.scalar(select(Comment.id).where(Comment.id == reply.id)) is None


async def test_follows_are_idempotent_and_notify_once(sessionmaker):  # noqa: F811
    a, b = await _users(sessionmaker, "a", "b")
    async with sessionmaker() as db:
        with pytest.raises(social.SocialError, match="yourself"):
            await social.follow(db, a.id, a.id)
        assert await social.follow(db, a.id, b.id) is True
        assert await social.follow(db, a.id, b.id) is False  # already following
        await db.commit()
        assert await social.follow_counts(db, b.id) == (1, 0)
        assert await social.follow_counts(db, a.id) == (0, 1)
        assert await social.following_set(db, a.id, [b.id]) == {b.id}

        assert await social.unfollow(db, a.id, b.id) is True
        assert await social.unfollow(db, a.id, b.id) is False
        await db.commit()
        assert await social.follow(db, a.id, b.id) is True  # follow again
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(Follow)) >= 1
    # Unfollow + follow again doesn't send a second "started following you".
    assert [n.type for n in await _notes(sessionmaker, b)] == [NotificationType.FOLLOW]
    assert await _notes(sessionmaker, a) == []


async def test_like_notification_once_and_unread_count(sessionmaker):  # noqa: F811
    owner, fan = await _users(sessionmaker, "owner", "fan")
    clip = await _clip(sessionmaker, owner)
    async with sessionmaker() as db:
        for _ in range(3):  # like, unlike, like...
            await social.notify(db, user_id=owner.id, actor_id=fan.id, type=NotificationType.LIKE, clip_id=clip.id, once=True)
            await db.commit()
        assert await social.notify(db, user_id=owner.id, actor_id=owner.id, type=NotificationType.LIKE, clip_id=clip.id) is False
        assert await social.unread_count(db, owner.id) == 1
