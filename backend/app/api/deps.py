import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db

Db = Annotated[AsyncSession, Depends(get_db)]


async def current_user_optional(
    db: Db,
    x_user_id: Annotated[uuid.UUID | None, Header(description="Acting user's ID (demo identity, no auth yet)")] = None,
) -> User | None:
    if x_user_id is None:
        return None
    user = await db.get(User, x_user_id)
    if user is None:
        raise HTTPException(401, "Unknown X-User-Id")
    return user


async def current_user(user: Annotated[User | None, Depends(current_user_optional)]) -> User:
    if user is None:
        raise HTTPException(401, "X-User-Id header required")
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
