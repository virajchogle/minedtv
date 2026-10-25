"""YouTube: Google OAuth (connect a channel once) and resumable video uploads.

Plain HTTP via httpx, so there are no Google client libraries to install. Refresh tokens are
stored encrypted with YOUTUBE_TOKEN_KEY (Fernet); the OAuth `state` is an HMAC-signed,
time-limited user id, so a callback can't be replayed or pointed at another account.

Note: until the Google Cloud project passes Google's API audit, videos uploaded through the
API are private, and the project's quota allows roughly 6 uploads a day (1600 units each).
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPES = ("https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly")
STATE_TTL_S = 15 * 60

TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_MAX_CHARS = 500


class YouTubeError(RuntimeError):
    pass


class YouTubeNotConfigured(YouTubeError):
    pass


def is_configured(settings: Settings) -> bool:
    return bool(settings.youtube_client_id and settings.youtube_client_secret and settings.youtube_token_key)


def _require(settings: Settings) -> None:
    if not is_configured(settings):
        raise YouTubeNotConfigured(
            "YouTube posting isn't configured (set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and YOUTUBE_TOKEN_KEY)"
        )


# ---------------------------------------------------------------- secrets


def encrypt_token(settings: Settings, token: str) -> str:
    _require(settings)
    return Fernet(settings.youtube_token_key.encode()).encrypt(token.encode()).decode()


def decrypt_token(settings: Settings, token_enc: str) -> str:
    _require(settings)
    try:
        return Fernet(settings.youtube_token_key.encode()).decrypt(token_enc.encode()).decode()
    except InvalidToken as e:
        raise YouTubeError("Stored YouTube token can't be decrypted (was YOUTUBE_TOKEN_KEY changed?)") from e


def sign_state(settings: Settings, user_id: uuid.UUID, now: float | None = None) -> str:
    _require(settings)
    payload = f"{user_id}.{int(now or time.time())}"
    mac = hmac.new(settings.youtube_token_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{payload}.{mac}".encode()).decode().rstrip("=")


def verify_state(settings: Settings, state: str, now: float | None = None) -> uuid.UUID:
    _require(settings)
    try:
        raw = base64.urlsafe_b64decode(state + "=" * (-len(state) % 4)).decode()
        user_id, issued, mac = raw.rsplit(".", 2)
    except Exception as e:  # noqa: BLE001
        raise YouTubeError("Invalid sign-in state") from e
    expected = hmac.new(settings.youtube_token_key.encode(), f"{user_id}.{issued}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(mac, expected):
        raise YouTubeError("Invalid sign-in state")
    if (now or time.time()) - int(issued) > STATE_TTL_S:
        raise YouTubeError("Sign-in took too long; start again")
    return uuid.UUID(user_id)


# ---------------------------------------------------------------- OAuth


def auth_url(settings: Settings, redirect_uri: str, state: str) -> str:
    _require(settings)
    return AUTH_URL + "?" + urlencode(
        {
            "client_id": settings.youtube_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",  # we need a refresh token for background uploads
            "prompt": "consent",  # always return a refresh token, even on reconnect
            "include_granted_scopes": "true",
            "state": state,
        }
    )


async def _post_token(client: httpx.AsyncClient, data: dict) -> dict:
    resp = await client.post(TOKEN_URL, data=data)
    body = resp.json() if resp.content else {}
    if resp.status_code != 200:
        raise YouTubeError(f"Google token error: {body.get('error_description') or body.get('error') or resp.status_code}")
    return body


async def exchange_code(client: httpx.AsyncClient, settings: Settings, code: str, redirect_uri: str) -> dict:
    _require(settings)
    return await _post_token(
        client,
        {
            "code": code,
            "client_id": settings.youtube_client_id,
            "client_secret": settings.youtube_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )


async def access_token(client: httpx.AsyncClient, settings: Settings, refresh_token: str) -> str:
    _require(settings)
    body = await _post_token(
        client,
        {
            "refresh_token": refresh_token,
            "client_id": settings.youtube_client_id,
            "client_secret": settings.youtube_client_secret,
            "grant_type": "refresh_token",
        },
    )
    return body["access_token"]


async def revoke(client: httpx.AsyncClient, token: str) -> None:
    await client.post(REVOKE_URL, data={"token": token})  # best effort


async def my_channel(client: httpx.AsyncClient, token: str) -> tuple[str, str | None]:
    """(channel id, channel title) of the signed-in account."""
    resp = await client.get(CHANNELS_URL, params={"part": "snippet", "mine": "true"}, headers={"Authorization": f"Bearer {token}"})
    body = resp.json() if resp.content else {}
    if resp.status_code != 200:
        raise YouTubeError(f"Couldn't read the YouTube channel: {_api_error(body, resp.status_code)}")
    items = body.get("items") or []
    if not items:
        raise YouTubeError("This Google account has no YouTube channel yet; create one on youtube.com first")
    return items[0]["id"], items[0].get("snippet", {}).get("title")


# ---------------------------------------------------------------- uploads


def _api_error(body: dict, status: int) -> str:
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        reasons = [e.get("reason") for e in err.get("errors", []) if e.get("reason")]
        return f"{err.get('message') or status}" + (f" ({', '.join(reasons)})" if reasons else "")
    return str(status)


def clean_metadata(title: str, description: str, tags: list[str]) -> tuple[str, str, list[str]]:
    """Fit YouTube's limits: title <= 100 chars, no angle brackets; description <= 5000; tags <= 500 chars total."""
    title = " ".join((title or "").replace("<", "").replace(">", "").split())[:TITLE_MAX] or "MinedTV clip"
    description = (description or "").replace("<", "").replace(">", "")[:DESCRIPTION_MAX]
    kept, used = [], 0
    for tag in tags or []:
        tag = tag.strip().lstrip("#").replace("<", "").replace(">", "")
        if not tag or tag in kept:
            continue
        cost = len(tag) + (2 if " " in tag else 0) + (1 if kept else 0)
        if used + cost > TAGS_MAX_CHARS:
            break
        kept.append(tag)
        used += cost
    return title, description, kept


async def upload_video(
    client: httpx.AsyncClient,
    token: str,
    path: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str,
    category_id: str = "20",  # Gaming
) -> str:
    """Resumable upload; returns the new video id."""
    metadata = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": category_id},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    size = path.stat().st_size
    init = await client.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(size),
        },
        content=json.dumps(metadata),
    )
    if init.status_code != 200 or "location" not in init.headers:
        raise YouTubeError(f"YouTube refused the upload: {_api_error(init.json() if init.content else {}, init.status_code)}")

    with path.open("rb") as f:
        resp = await client.put(
            init.headers["location"],
            headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4", "Content-Length": str(size)},
            content=f.read(),
            timeout=httpx.Timeout(600),
        )
    body = resp.json() if resp.content else {}
    if resp.status_code not in (200, 201) or "id" not in body:
        raise YouTubeError(f"YouTube upload failed: {_api_error(body, resp.status_code)}")
    return body["id"]


def video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


async def posted_urls(db, clip_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Each clip's most recent successful YouTube post, for marking clips "On YouTube" in lists."""
    from sqlalchemy import select

    from app.db.models import YouTubeUpload, YouTubeUploadStatus

    if not clip_ids:
        return {}
    rows = await db.execute(
        select(YouTubeUpload.clip_id, YouTubeUpload.video_id)
        .where(
            YouTubeUpload.clip_id.in_(clip_ids),
            YouTubeUpload.status == YouTubeUploadStatus.PUBLISHED,
            YouTubeUpload.video_id.is_not(None),
        )
        .order_by(YouTubeUpload.updated_at)
    )
    return {clip_id: video_url(video_id) for clip_id, video_id in rows}  # later rows win
