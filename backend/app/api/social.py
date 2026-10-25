"""Comments, follows and the following feed."""

import uuid

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import and_, func, or_, select

from app.api.clips import _check_visible
from app.api.deps import CurrentUser, Db, OptionalUser, Urls
from app.api.feed import base_clip_query, clip_page, decode_cursor, encode_cursor
from app.db.models import Clip, Comment, Follow, User
from app.schemas import (
    ClipFormat,
    CommentCreate,
    CommentOut,
    CommentsPage,
    FeedOut,
    FeedSort,
    FollowOut,
    UserOut,
    UsersPage,
)
from app.services import social

router = APIRouter(tags=["social"])


# ---------------------------------------------------------------- comments


async def _visible_clip(db, clip_id: uuid.UUID, me: User | None) -> Clip:
    clip = await db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    _check_visible(clip, me)
    return clip


def _comment_out(c: Comment, author: User, clip: Clip, me: User | None, reply_count: int = 0, replies=None) -> CommentOut:
    return CommentOut(
        id=c.id,
        clip_id=c.clip_id,
        user=UserOut.model_validate(author),
        body=c.body,
        parent_id=c.parent_id,
        created_at=c.created_at,
        reply_count=reply_count,
        replies=replies or [],
        can_delete=None if me is None else me.id in (c.user_id, clip.user_id),
    )


@router.get("/clips/{clip_id}/comments", response_model=CommentsPage)
async def list_comments(
    clip_id: uuid.UUID,
    db: Db,
    me: OptionalUser,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> CommentsPage:
    """Top-level comments, newest first, each with its replies (oldest first)."""
    clip = await _visible_clip(db, clip_id, me)
    stmt = (
        select(Comment, User)
        .join(User, User.id == Comment.user_id)
        .where(Comment.clip_id == clip.id, Comment.parent_id.is_(None))
    )
    if cursor:
        ts, cid = decode_cursor(cursor)
        stmt = stmt.where(or_(Comment.created_at < ts, and_(Comment.created_at == ts, Comment.id < cid)))
    rows = (await db.execute(stmt.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit + 1))).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    top_ids = [r.Comment.id for r in rows]
    replies_by_parent: dict[uuid.UUID, list[CommentOut]] = {cid: [] for cid in top_ids}
    if top_ids:
        reply_rows = await db.execute(
            select(Comment, User)
            .join(User, User.id == Comment.user_id)
            .where(Comment.parent_id.in_(top_ids))
            .order_by(Comment.created_at.asc(), Comment.id.asc())
        )
        for r in reply_rows:
            replies_by_parent[r.Comment.parent_id].append(_comment_out(r.Comment, r.User, clip, me))

    total = await db.scalar(select(func.count()).select_from(Comment).where(Comment.clip_id == clip.id)) or 0
    items = [
        _comment_out(r.Comment, r.User, clip, me, len(replies_by_parent[r.Comment.id]), replies_by_parent[r.Comment.id])
        for r in rows
    ]
    next_cursor = encode_cursor(rows[-1].Comment.created_at, rows[-1].Comment.id) if has_more and rows else None
    return CommentsPage(items=items, next_cursor=next_cursor, total=total)


@router.post("/clips/{clip_id}/comments", response_model=CommentOut, status_code=201)
async def post_comment(clip_id: uuid.UUID, body: CommentCreate, user: CurrentUser, db: Db) -> CommentOut:
    """Comment on a clip, or reply with parent_id. Notifies the clip owner and the replied-to author."""
    clip = await _visible_clip(db, clip_id, user)
    try:
        comment = await social.add_comment(db, clip, user.id, body.body, body.parent_id)
    except social.SocialError as e:
        raise HTTPException(422, str(e)) from e
    await db.commit()
    await db.refresh(comment)
    return _comment_out(comment, user, clip, user)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: uuid.UUID, user: CurrentUser, db: Db) -> Response:
    """Delete a comment (and its replies). Allowed for its author and the clip's owner."""
    comment = await db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(404, "Comment not found")
    clip = await db.get(Clip, comment.clip_id)
    if user.id not in (comment.user_id, clip.user_id if clip else None):
        raise HTTPException(403, "Only the author or the clip's owner can delete this comment")
    await db.delete(comment)
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- follows


async def _user_or_404(db, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


@router.post("/users/{user_id}/follow", response_model=FollowOut)
async def follow_user(user_id: uuid.UUID, me: CurrentUser, db: Db) -> FollowOut:
    """Follow a user (idempotent). Notifies them the first time."""
    await _user_or_404(db, user_id)
    try:
        await social.follow(db, me.id, user_id)
    except social.SocialError as e:
        raise HTTPException(422, str(e)) from e
    await db.commit()
    followers, _ = await social.follow_counts(db, user_id)
    return FollowOut(user_id=user_id, following=True, follower_count=followers)


@router.delete("/users/{user_id}/follow", response_model=FollowOut)
async def unfollow_user(user_id: uuid.UUID, me: CurrentUser, db: Db) -> FollowOut:
    await _user_or_404(db, user_id)
    await social.unfollow(db, me.id, user_id)
    await db.commit()
    followers, _ = await social.follow_counts(db, user_id)
    return FollowOut(user_id=user_id, following=False, follower_count=followers)


async def _follow_page(db, user_id: uuid.UUID, direction: str, cursor: str | None, limit: int) -> UsersPage:
    """direction 'followers': people who follow user_id; 'following': people user_id follows."""
    other = Follow.follower_id if direction == "followers" else Follow.followee_id
    this = Follow.followee_id if direction == "followers" else Follow.follower_id
    stmt = select(User, Follow.created_at).join(Follow, other == User.id).where(this == user_id)
    if cursor:
        ts, uid = decode_cursor(cursor)
        stmt = stmt.where(or_(Follow.created_at < ts, and_(Follow.created_at == ts, User.id < uid)))
    rows = (await db.execute(stmt.order_by(Follow.created_at.desc(), User.id.desc()).limit(limit + 1))).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1].created_at, rows[-1].User.id) if has_more and rows else None
    return UsersPage(items=[UserOut.model_validate(r.User) for r in rows], next_cursor=next_cursor)


@router.get("/users/{user_id}/followers", response_model=UsersPage)
async def followers(
    user_id: uuid.UUID, db: Db, cursor: str | None = None, limit: int = Query(default=30, ge=1, le=100)
) -> UsersPage:
    """People who follow this user, most recent first."""
    await _user_or_404(db, user_id)
    return await _follow_page(db, user_id, "followers", cursor, limit)


@router.get("/users/{user_id}/following", response_model=UsersPage)
async def following(
    user_id: uuid.UUID, db: Db, cursor: str | None = None, limit: int = Query(default=30, ge=1, le=100)
) -> UsersPage:
    """People this user follows, most recent first."""
    await _user_or_404(db, user_id)
    return await _follow_page(db, user_id, "following", cursor, limit)


@router.get("/feed/following", response_model=FeedOut)
async def following_feed(
    me: CurrentUser,
    db: Db,
    urls: Urls,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    format: ClipFormat | None = Query(default=None, description="short (Reels) or long; omit for both"),
    sort: FeedSort = Query(default="new", description="new = newest first; top = ranked by engagement and virality"),
) -> FeedOut:
    """Published clips from people you follow, newest first (or ranked with sort=top)."""
    followees = select(Follow.followee_id).where(Follow.follower_id == me.id)
    stmt = base_clip_query().where(Clip.user_id.in_(followees))
    return await clip_page(db, stmt, limit, cursor, urls, me, format, sort)
