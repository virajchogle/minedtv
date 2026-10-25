import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import Db, OptionalUser, Urls
from app.api.feed import base_clip_query, clip_page
from app.db.models import PUBLISH_STATES, UNPUBLISHED_STATES, Clip, User
from app.schemas import ClipFormat, FeedOut, FeedSort, ProfileOut, UserCreate, UserOut
from app.services import social

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, db: Db) -> UserOut:
    """Create a demo user. There's no auth yet: clients act as a user by sending X-User-Id."""
    if await db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, "Username taken")
    user = User(username=body.username, avatar_url=body.avatar_url)
    db.add(user)
    await db.commit()
    return UserOut.model_validate(user)


@router.get("", response_model=list[UserOut])
async def list_users(db: Db, limit: int = Query(default=50, ge=1, le=200)) -> list[UserOut]:
    users = (await db.scalars(select(User).order_by(User.username).limit(limit))).all()
    return [UserOut.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=ProfileOut)
async def get_user(user_id: uuid.UUID, db: Db, me: OptionalUser) -> ProfileOut:
    """A user's profile: follower/following counts, published clip count, and (with X-User-Id)
    whether you follow them and they follow you."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    followers, following = await social.follow_counts(db, user.id)
    published = await db.scalar(
        select(func.count()).select_from(Clip).where(Clip.user_id == user.id, Clip.publish_state == "published")
    )
    followed_by_me = follows_me = None
    if me is not None and me.id != user.id:
        followed_by_me = user.id in await social.following_set(db, me.id, [user.id])
        follows_me = me.id in await social.following_set(db, user.id, [me.id])
    return ProfileOut(
        **UserOut.model_validate(user).model_dump(),
        follower_count=followers,
        following_count=following,
        published_clip_count=published or 0,
        followed_by_me=followed_by_me,
        follows_me=follows_me,
    )


@router.get("/{user_id}/clips", response_model=FeedOut)
async def user_clips(
    user_id: uuid.UUID,
    db: Db,
    urls: Urls,
    me: OptionalUser,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    state: Literal["all", "draft", "ready", "published", "unpublished"] = Query(
        default="all", description="Owner only (X-User-Id = user_id); everyone else always gets published clips"
    ),
    format: ClipFormat | None = Query(default=None, description="short (Reels) or long; omit for both"),
    sort: FeedSort = Query(default="new", description="new = newest first; top = ranked by engagement and virality"),
) -> FeedOut:
    """A user's clips, newest first (same pagination as /feed). Owners can filter by publish state:
    draft, ready (queued to post to YouTube), published, unpublished (draft + ready) or all."""
    if await db.get(User, user_id) is None:
        raise HTTPException(404, "User not found")
    if me is None or me.id != user_id:
        states: tuple[str, ...] = ("published",)
    else:
        states = {
            "all": PUBLISH_STATES,
            "unpublished": UNPUBLISHED_STATES,
        }.get(state, (state,))
    stmt = base_clip_query(states).where(Clip.user_id == user_id)
    return await clip_page(db, stmt, limit, cursor, urls, me, format, sort)
