import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.services import accounts

Db = Annotated[AsyncSession, Depends(get_db)]


async def signed_in_user(
    db: Db,
    authorization: Annotated[str | None, Header(description="Bearer <token> from /auth/login")] = None,
) -> User | None:
    """The account behind the login token, if one was sent (never an impersonated user)."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Authorization must be 'Bearer <token>'")
    try:
        user_id = accounts.read_token(get_settings(), token.strip())
    except accounts.AuthNotConfigured as e:
        raise HTTPException(503, str(e)) from e
    except accounts.InvalidToken as e:
        raise HTTPException(401, str(e)) from e
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "Account no longer exists")
    return user


SignedInUser = Annotated[User | None, Depends(signed_in_user)]


async def current_user_optional(
    db: Db,
    account: SignedInUser,
    x_user_id: Annotated[
        uuid.UUID | None,
        Header(description="Act as this user. Dev accounts may act as anyone; others only as themselves."),
    ] = None,
) -> User | None:
    """Who the request acts as: the X-User-Id user if sent and allowed, else the signed-in account.
    While REQUIRE_LOGIN is off (testing), anyone may act as anyone, as before accounts existed.
    With it on, a login token is required and only dev accounts may act as someone else."""
    if x_user_id is None or (account is not None and x_user_id == account.id):
        return account
    if get_settings().require_login:
        if account is None:
            raise HTTPException(401, "Sign in first (Authorization: Bearer <token>)")
        if not account.is_dev:
            raise HTTPException(403, "Only dev accounts can act as another user")
    user = await db.get(User, x_user_id)
    if user is None:
        raise HTTPException(401, "Unknown X-User-Id")
    return user


async def current_user(user: Annotated[User | None, Depends(current_user_optional)]) -> User:
    if user is None:
        raise HTTPException(401, "Sign in first (or send X-User-Id)")
    return user


OptionalUser = Annotated[User | None, Depends(current_user_optional)]
CurrentUser = Annotated[User, Depends(current_user)]


class UrlBuilder:
    """Builds absolute URLs for links the API hands out (e.g. HLS playlists)."""

    def __init__(self, request: Request):
        base = get_settings().public_api_base_url or str(request.base_url)
        self.base = base.rstrip("/")

    def clip_playlist(self, clip_id) -> str:
        return f"{self.base}/clips/{clip_id}/playlist.m3u8"

    def session_playlist(self, session_id, start_ms: int | None = None, end_ms: int | None = None) -> str:
        url = f"{self.base}/sessions/{session_id}/playlist.m3u8"
        if start_ms is not None and end_ms is not None:
            url += f"?start_ms={start_ms}&end_ms={end_ms}"
        return url


Urls = Annotated[UrlBuilder, Depends(UrlBuilder)]
