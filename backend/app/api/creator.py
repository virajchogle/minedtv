"""Video-to-content metadata endpoint for creator-facing clients."""

import asyncio
import logging
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.config import get_settings
from app.ml.audience_simulator import GeminiAudienceSimulator
from app.ml.gemini_creator import (
    CreatorAnalysisError,
    CreatorConfigurationError,
    GeminiCreatorEngine,
)
from app.schemas import (
    AudienceSimulationIn,
    AudienceSimulationOut,
    CreatorPackOut,
    CreatorPlatform,
    DirectHighlightClipOut,
    DirectHighlightFrameOut,
    DirectHighlightMomentOut,
    DirectHighlightsOut,
    DirectMusicOut,
    HighlightCaptionStyle,
    HighlightMusicOut,
    HighlightMode,
)
from app.services.standalone_highlights import StandaloneHighlightEngine, algorithm_version
from app.services.video_persona_virality import VideoPersonaViralityEngine
from app.worker import media

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


@lru_cache
def get_standalone_highlight_engine() -> StandaloneHighlightEngine:
    from app.ml.gemini_captions import GeminiCaptionEngine
    from app.ml.registry import get_embedder, get_transcriber
    from app.services.music_catalog import MusicCatalog

    settings = get_settings()
    caption_engine = GeminiCaptionEngine(settings) if settings.gemini_api_key else None
    music_catalog = MusicCatalog(settings.highlight_music_catalog_url)
    return StandaloneHighlightEngine(settings, get_embedder(), get_transcriber(), caption_engine, music_catalog)


@lru_cache
def get_video_persona_virality_engine() -> VideoPersonaViralityEngine:
    from app.ml.registry import get_embedder

    return VideoPersonaViralityEngine(get_settings(), get_embedder())


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


def _direct_asset_url(request: Request, run_id: uuid.UUID, path: str) -> str:
    configured = get_settings().public_api_base_url
    base = (configured or str(request.base_url)).rstrip("/")
    return f"{base}/creator/highlights/{run_id}/{path}"


def _direct_music_url(request: Request, run_id: uuid.UUID, *, download: bool = False) -> str:
    configured = get_settings().public_api_base_url
    base = (configured or str(request.base_url)).rstrip("/")
    suffix = "?download=true" if download else ""
    return f"{base}/creator/music/{run_id}.mp4{suffix}"


@router.post("/music", response_model=DirectMusicOut)
async def add_adaptive_music(
    request: Request,
    video: UploadFile = File(description="Video that should receive context-matched background music"),
) -> DirectMusicOut:
    """Add adaptive music to the complete upload without cutting it or adding captions."""
    suffix, _ = _video_metadata(video)
    temp_path: Path | None = None
    try:
        if not media.tools_available():
            raise HTTPException(503, "Adaptive music requires ffmpeg and ffprobe on the API host")
        temp_path = await _save_video(video, suffix)
        result = await run_in_threadpool(
            get_standalone_highlight_engine().process_music,
            temp_path,
            video.filename or f"video{suffix}",
        )
        return DirectMusicOut(
            run_id=result.run_id,
            filename=result.filename,
            duration_ms=result.duration_ms,
            width=result.width,
            height=result.height,
            speech_cue_count=result.speech_cue_count,
            transcript_source=result.transcript_source,
            music_mixed=True,
            music=HighlightMusicOut.model_validate(result.music),
            video_url=_direct_music_url(request, result.run_id),
            download_url=_direct_music_url(request, result.run_id, download=True),
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Adaptive music generation failed")
        raise HTTPException(502, f"Adaptive music generation failed: {exc}") from exc
    finally:
        await video.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)


@router.get("/music/{run_id}.mp4", response_class=FileResponse)
async def get_adaptive_music_video(run_id: uuid.UUID, download: bool = False) -> FileResponse:
    path = get_standalone_highlight_engine().clip_path(run_id, 1)
    if not path.is_file():
        raise HTTPException(404, "Music-enhanced video not found or expired")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename="music-enhanced.mp4" if download else None,
    )


@router.post("/highlights", response_model=DirectHighlightsOut)
async def create_direct_highlights(
    request: Request,
    video: UploadFile = File(description="Video to score and cut into highlights"),
    mode: HighlightMode = Form(default="montage"),
    captions: bool = Form(default=True),
    caption_style: HighlightCaptionStyle = Form(default="bold"),
    music: bool = Form(default=True),
) -> DirectHighlightsOut:
    """Upload one video and render its major moments as one contextualized montage.

    This does not create a user/session and does not require Postgres, Redis, or the persona simulator.
    """
    suffix, _ = _video_metadata(video)
    temp_path: Path | None = None
    try:
        if not media.tools_available():
            raise HTTPException(503, "Direct highlights require ffmpeg and ffprobe on the API host")
        temp_path = await _save_video(video, suffix)
        result = await run_in_threadpool(
            get_standalone_highlight_engine().process,
            temp_path,
            video.filename or f"video{suffix}",
            mode=mode,
            captions=captions,
            caption_style=caption_style,
            music=music,
        )
        selected_ids = {frame.frame_id for frame in result.scores if frame.selected}
        scores = [
            DirectHighlightFrameOut(
                frame_id=frame.frame_id,
                t_ms=frame.t_ms,
                score=frame.score,
                visual_score=frame.visual_score,
                novelty_score=frame.novelty_score,
                visibility_score=frame.visibility_score,
                scene_score=frame.scene_score,
                selected=frame.frame_id in selected_ids,
                thumbnail_url=(
                    _direct_asset_url(request, result.run_id, f"frames/{frame.frame_id}.jpg")
                    if frame.frame_id in selected_ids
                    else None
                ),
            )
            for frame in result.scores
        ]
        clips = [
            DirectHighlightClipOut(
                index=clip.index,
                title=clip.title,
                start_ms=clip.start_ms,
                end_ms=clip.end_ms,
                duration_ms=clip.end_ms - clip.start_ms,
                score=clip.score,
                video_url=_direct_asset_url(request, result.run_id, f"clips/{clip.index}.mp4"),
                download_url=_direct_asset_url(request, result.run_id, f"clips/{clip.index}.mp4?download=true"),
                thumbnail_url=_direct_asset_url(request, result.run_id, f"frames/{clip.frame_id}.jpg"),
                width=clip.width,
                height=clip.height,
                captions_burned=clip.captions_burned,
                caption_count=clip.caption_count,
                caption_source=clip.caption_source,
                music_mixed=clip.music_mixed,
                music=HighlightMusicOut.model_validate(clip.music) if clip.music else None,
                moments=[
                    DirectHighlightMomentOut(
                        index=moment.index,
                        source_start_ms=moment.start_ms,
                        source_end_ms=moment.end_ms,
                        duration_ms=moment.end_ms - moment.start_ms,
                        score=moment.score,
                        thumbnail_url=_direct_asset_url(
                            request,
                            result.run_id,
                            f"frames/{moment.frame_id}.jpg",
                        ),
                    )
                    for moment in clip.moments
                ],
            )
            for clip in result.clips
        ]
        return DirectHighlightsOut(
            run_id=result.run_id,
            filename=result.filename,
            duration_ms=result.duration_ms,
            width=result.width,
            height=result.height,
            frames_analyzed=len(result.scores),
            algorithm_version=algorithm_version(),
            scores=scores,
            clips=clips,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Standalone highlight generation failed")
        raise HTTPException(502, f"Highlight generation failed: {exc}") from exc
    finally:
        await video.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)


@router.get("/highlights/{run_id}/clips/{index}.mp4", response_class=FileResponse)
async def get_direct_highlight_clip(run_id: uuid.UUID, index: int, download: bool = False) -> FileResponse:
    path = get_standalone_highlight_engine().clip_path(run_id, index)
    if index < 1 or not path.is_file():
        raise HTTPException(404, "Highlight clip not found or expired")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"highlight-{index}.mp4" if download else None,
    )


@router.get("/highlights/{run_id}/frames/{frame_id}.jpg", response_class=FileResponse)
async def get_direct_highlight_frame(run_id: uuid.UUID, frame_id: uuid.UUID) -> FileResponse:
    path = get_standalone_highlight_engine().frame_path(run_id, frame_id)
    if not path.is_file():
        raise HTTPException(404, "Highlight frame not found or expired")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/analyze", response_model=CreatorPackOut)
async def analyze_video(video: UploadFile = File(description="Video file to analyze")) -> CreatorPackOut:
    """Generate transcripts, summaries, and platform-ready metadata from one video."""
    # Keep this hot path identical to the original analyzer implementation.
    # Persona-specific helpers and services are never invoked from this route.
    filename = video.filename or "video.mp4"
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in _ALLOWED_EXT:
        raise HTTPException(422, f"Unsupported file type {suffix or '(none)'}")

    mime_type = video.content_type or "video/mp4"
    if not mime_type.startswith("video/"):
        raise HTTPException(422, "The uploaded file must have a video content type")

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


@router.post("/virality", response_model=AudienceSimulationOut)
async def calculate_video_virality(
    video: UploadFile = File(description="Video file to score with frame evidence and audience personas"),
    platform: CreatorPlatform = Form(default="general"),
    target_audience: str | None = Form(default=None, max_length=500),
    persona_count: int | None = Form(default=None, ge=3, le=15),
) -> AudienceSimulationOut:
    """Calculate frame-aware video virality with one video analysis and one persona-panel call.

    Frame extraction/embedding runs locally in parallel with the Gemini content analysis.
    The resulting score curve is passed into the single persona request and blended with
    the deterministic audience cascade; no per-frame or per-persona API calls are made.
    """
    suffix, mime_type = _video_metadata(video)
    selected_count = persona_count or get_settings().creator_persona_count
    temp_path: Path | None = None
    try:
        if not media.tools_available():
            raise HTTPException(503, "Video virality requires ffmpeg and ffprobe on the API host")
        temp_path = await _save_video(video, suffix)
        analysis_result, prepared_result = await asyncio.gather(
            run_in_threadpool(get_creator_engine().analyze, temp_path, mime_type),
            run_in_threadpool(get_video_persona_virality_engine().prepare, temp_path),
            return_exceptions=True,
        )
        if isinstance(analysis_result, BaseException):
            raise analysis_result
        if isinstance(prepared_result, BaseException):
            raise prepared_result
        evidence = await run_in_threadpool(
            get_video_persona_virality_engine().evidence,
            prepared_result,
            analysis_result,
        )
        return await run_in_threadpool(
            get_audience_simulator().simulate,
            analysis_result,
            platform,
            target_audience,
            selected_count,
            evidence,
        )
    except CreatorConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, str(exc)) from exc
    except CreatorAnalysisError as exc:
        log.exception("Frame-aware video virality failed")
        raise HTTPException(502, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Frame-aware video virality failed")
        raise HTTPException(502, f"Video virality failed: {exc}") from exc
    finally:
        await video.close()
        if temp_path:
            temp_path.unlink(missing_ok=True)


@router.post("/simulate-analysis", response_model=AudienceSimulationOut)
async def simulate_analyzed_video(body: AudienceSimulationIn) -> AudienceSimulationOut:
    """Run the persona cascade using an existing /creator/analyze result."""
    selected_count = body.persona_count or get_settings().creator_persona_count
    try:
        return await run_in_threadpool(
            get_audience_simulator().simulate,
            body.analysis,
            body.platform,
            body.target_audience,
            selected_count,
        )
    except CreatorConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, str(exc)) from exc
    except CreatorAnalysisError as exc:
        log.exception("Gemini audience simulation failed")
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        log.exception("Audience simulation failed")
        raise HTTPException(502, "Audience simulation failed") from exc
