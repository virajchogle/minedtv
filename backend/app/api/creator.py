"""Video-to-content metadata endpoint for creator-facing clients."""

import logging
import tempfile
from functools import lru_cache
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.config import get_settings
from app.ml.audience_simulator import GeminiAudienceSimulator
from app.ml.gemini_creator import (
    CreatorAnalysisError,
    CreatorConfigurationError,
    GeminiCreatorEngine,
)
from app.schemas import AudienceSimulationOut, CreatorPackOut, CreatorPlatform

router = APIRouter(prefix="/creator", tags=["creator"])
log = logging.getLogger(__name__)

_ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mpeg", ".mpg"}
_CHUNK_SIZE = 1024 * 1024


@lru_cache
def get_creator_engine() -> GeminiCreatorEngine:
    return GeminiCreatorEngine(get_settings())


@lru_cache
def get_audience_simulator() -> GeminiAudienceSimulator:
    return GeminiAudienceSimulator(get_settings())


def _video_metadata(video: UploadFile) -> tuple[str, str]:
    filename = video.filename or "video.mp4"
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in _ALLOWED_EXT:
        raise HTTPException(422, f"Unsupported file type {suffix or '(none)'}")

    mime_type = video.content_type or "video/mp4"
    if not mime_type.startswith("video/"):
        raise HTTPException(422, "The uploaded file must have a video content type")
    return suffix, mime_type


async def _save_video(video: UploadFile, suffix: str) -> Path:
    settings = get_settings()
    max_bytes = settings.creator_max_upload_mb * 1024 * 1024
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)
            size = 0
            while chunk := await video.read(_CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"Video exceeds the {settings.creator_max_upload_mb} MB limit")
                temp_file.write(chunk)
        if not size:
            raise HTTPException(422, "The uploaded video is empty")
        return temp_path
    except Exception:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        raise


@router.post("/analyze", response_model=CreatorPackOut)
async def analyze_video(video: UploadFile = File(description="Video file to analyze")) -> CreatorPackOut:
    """Generate transcripts, summaries, and platform-ready metadata from one video."""
    suffix, mime_type = _video_metadata(video)

    temp_path: Path | None = None

    try:
        temp_path = await _save_video(video, suffix)
        return await run_in_threadpool(get_creator_engine().analyze, temp_path, mime_type)
    except CreatorConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, str(exc)) from exc
    except CreatorAnalysisError as exc:
        log.exception("Gemini creator analysis failed")
        raise HTTPException(502, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Creator analysis failed")
        raise HTTPException(502, "Video analysis failed") from exc
    finally:
        await video.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)


@router.post("/simulate", response_model=AudienceSimulationOut)
async def simulate_audience(
    video: UploadFile = File(description="Video file to analyze and test with synthetic audience personas"),
    platform: CreatorPlatform = Form(default="general"),
    target_audience: str | None = Form(default=None, max_length=500),
    persona_count: int | None = Form(default=None, ge=3, le=15),
) -> AudienceSimulationOut:
    """Analyze a video, collect persona reviews, and model its sharing cascade."""
    suffix, mime_type = _video_metadata(video)
    selected_count = persona_count or get_settings().creator_persona_count
    temp_path: Path | None = None

    try:
        temp_path = await _save_video(video, suffix)
        analysis = await run_in_threadpool(get_creator_engine().analyze, temp_path, mime_type)
        return await run_in_threadpool(
            get_audience_simulator().simulate,
            analysis,
            platform,
            target_audience,
            selected_count,
        )
    except CreatorConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, str(exc)) from exc
    except CreatorAnalysisError as exc:
        log.exception("Gemini audience simulation failed")
        raise HTTPException(502, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Audience simulation failed")
        raise HTTPException(502, "Audience simulation failed") from exc
    finally:
        await video.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)
