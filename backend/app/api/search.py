import time
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.api.deps import OptionalUser, UrlBuilder, Urls
from app.config import get_settings
from app.db.session import get_sessionmaker
from app.ml.registry import get_embedder
from app.schemas import MomentOut, SearchOut, SearchResult, UserOut
from app.services.redis import get_redis
from app.services.search import Filters, Resolved, SearchService
from app.services.serialize import url_or_none

router = APIRouter(prefix="/search", tags=["search"])

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _service(cache: bool = True) -> SearchService:
    return SearchService(get_sessionmaker(), get_embedder(), get_settings(), get_redis() if cache else None)


def _out(r: Resolved, urls: UrlBuilder) -> SearchResult:
    return SearchResult(
        kind=r.kind,
        clip_id=r.clip_id,
        session_id=r.session_id,
        match_t_ms=r.match_t_ms,
        start_ms=r.start_ms,
        end_ms=r.end_ms,
        score=r.score,
        confidence=r.confidence,
        signals=r.signals,
        thumbnail_url=url_or_none(r.thumbnail_key),
        transcript_snippet=r.transcript_snippet,
        playlist_url=urls.clip_playlist(r.clip_id) if r.clip_id else urls.session_playlist(r.session_id, r.start_ms, r.end_ms),
        game=r.game,
        title=r.title,
        user=UserOut(**r.user),
        other_moments_ms=r.other_moments_ms,
        moments=[
            MomentOut(
                t_ms=m["t_ms"],
                offset_ms=max(0, m["t_ms"] - r.start_ms),
                confidence=m["confidence"],
                signals=m["signals"],
                label=m["label"],
                snippet=m["snippet"],
                thumbnail_url=url_or_none(m["thumbnail_key"]),
            )
            for m in r.moments
        ],
    )


@router.get("", response_model=SearchOut)
async def search(
    urls: Urls,
    me: OptionalUser,
    q: str = Query(min_length=1, max_length=300, examples=["the clutch on Bind"]),
    game: str | None = None,
    user_id: uuid.UUID | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    nocache: bool = Query(default=False, description="Skip the 5-minute result cache (for load testing)"),
) -> SearchOut:
    """Hybrid semantic search: visual frames + speech (semantic and keyword) + highlight events, fused with RRF.

    One result per session, resolved to the clip containing the best moment. Only published clips
    are searched, except when user_id is your own X-User-Id: then your drafts and "ready" clips
    are included too, plus suggested ±15 s windows for matches outside any clip.
    """
    t0 = time.monotonic()
    # Searching your own clips (user_id == your X-User-Id) includes drafts and "ready" clips.
    own = me is not None and user_id == me.id
    results, cached = await _service(cache=not nocache).search_text(q, Filters(game, user_id, from_, to, own), limit)
    return SearchOut(
        query=q, results=[_out(r, urls) for r in results], took_ms=round((time.monotonic() - t0) * 1000), cached=cached
    )


@router.post("/image", response_model=SearchOut)
async def search_image(
    urls: Urls,
    me: OptionalUser,
    image: UploadFile = File(description="A screenshot (JPEG or PNG)"),
    game: str | None = Form(default=None),
    user_id: uuid.UUID | None = Form(default=None),
    limit: int = Form(default=20, ge=1, le=50),
) -> SearchOut:
    """Find the moments that look most like an uploaded screenshot."""
    data = await image.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image too large (max 8 MB)")
    if not data:
        raise HTTPException(422, "Empty image")
    t0 = time.monotonic()
    own = me is not None and user_id == me.id
    results = await _service(cache=False).search_image(data, Filters(game, user_id, include_unpublished=own), limit)
    return SearchOut(
        query=f"image:{image.filename or 'upload'}",
        results=[_out(r, urls) for r in results],
        took_ms=round((time.monotonic() - t0) * 1000),
        cached=False,
    )
