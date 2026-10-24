"""Shared API key check.

When API_KEYS is set, every request must carry one of the keys in the X-API-Key header
(or ?api_key=, for clients like the browser's EventSource that can't set headers).
Health, docs and HLS playlists stay open: video players fetch playlists on their own and
can't reliably add headers, and a playlist only links to segments of one known clip.
"""

import hmac
import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

HEADER = "x-api-key"
QUERY_PARAM = "api_key"
_OPEN_PATHS = re.compile(r"^/(health|docs|redoc|openapi\.json)$|\.m3u8$")


def key_matches(candidate: str | None, keys: list[str]) -> bool:
    if not candidate:
        return False
    # Compare against every key so timing doesn't reveal which (if any) matched.
    matched = False
    for key in keys:
        matched |= hmac.compare_digest(candidate.encode(), key.encode())
    return matched


def _query_key(scope: Scope) -> str | None:
    from urllib.parse import parse_qs

    values = parse_qs(scope.get("query_string", b"").decode()).get(QUERY_PARAM)
    return values[0] if values else None


class ApiKeyMiddleware:
    def __init__(self, app: ASGIApp, keys: list[str]):
        self.app = app
        self.keys = [k for k in keys if k]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not self.keys
            or scope["method"] == "OPTIONS"  # CORS preflight never carries custom headers
            or _OPEN_PATHS.search(scope["path"])
        ):
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        candidate = headers.get(HEADER.encode(), b"").decode() or _query_key(scope)
        if not key_matches(candidate, self.keys):
            response = JSONResponse({"detail": "Missing or invalid API key (send X-API-Key)"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
