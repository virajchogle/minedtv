"""On-demand frame virality analysis and highlight clip generation."""

import asyncio
import logging
import uuid

from sqlalchemy import delete, func, insert, or_, select, update

from app.db.models import (
    Clip,
    Event,
    Frame,
    FrameHighlightRun,
    FrameViralityScore,
    Session,
    SessionStatus,
    Transcript,
)
from app.services.frame_virality import (
    ALGORITHM_VERSION,
    EventInput,
    FrameInput,
    TranscriptInput,
    image_visibility_score,
    prompt_embeddings,
    score_frames,
    select_highlights,
)
from app.worker.pipeline import Deps

log = logging.getLogger("frame_highlights")
EVENT_SOURCE = "FrameViralityScorer"


async def _backfill_visibility(frame_rows, deps: Deps) -> list[FrameInput]:
    """Calculate legacy-frame visibility once, then persist it for later runs."""
    semaphore = asyncio.Semaphore(8)

    async def calculate(thumbnail_key: str | None) -> float:
        if not thumbnail_key:
            return 0.5
        async with semaphore:
            image = await asyncio.to_thread(deps.storage.get_bytes, thumbnail_key)
        return await asyncio.to_thread(image_visibility_score, image)

    missing = [row for row in frame_rows if row.visibility_score is None]
    calculated = await asyncio.gather(*(calculate(row.thumbnail_key) for row in missing))
    backfilled = {row.id: value for row, value in zip(missing, calculated, strict=True)}
    if backfilled:
        async with deps.sessionmaker() as db:
            for frame_id, visibility in backfilled.items():
                await db.execute(
                    update(Frame).where(Frame.id == frame_id).values(visibility_score=visibility)
                )
            await db.commit()

    return [
        FrameInput(
            row.id,
            row.t_ms,
            row.embedding,
            row.thumbnail_key,
            row.visibility_score if row.visibility_score is not None else backfilled[row.id],
        )
        for row in frame_rows
    ]


async def _mark_failed(session_id: uuid.UUID, deps: Deps, error: Exception) -> None:
    async with deps.sessionmaker() as db:
        run = await db.get(FrameHighlightRun, session_id)
        if run is not None:
            run.status = "failed"
            run.error = f"{type(error).__name__}: {error}"[:1000]
            run.updated_at = func.now()
            await db.commit()


async def run_frame_highlights(
    session_id: uuid.UUID | str,
    deps: Deps,
    requested_count: int | None = None,
    clip_duration_ms: int | None = None,
) -> str:
    """Score existing frames, replace prior frame-generated clips, and return the session id."""
    session_id = uuid.UUID(str(session_id))
    count = requested_count or deps.settings.frame_highlight_count
    clip_duration = clip_duration_ms or deps.settings.frame_highlight_duration_ms

    try:
        async with deps.sessionmaker() as db:
            session = await db.get(Session, session_id)
            if session is None:
                raise LookupError(f"session {session_id} not found")
            if session.status != SessionStatus.READY or not session.duration_ms:
                raise RuntimeError(f"session {session_id} is not ready")

            run = await db.get(FrameHighlightRun, session_id)
            if run is None:
                run = FrameHighlightRun(
                    session_id=session_id,
                    status="processing",
                    requested_count=count,
                    clip_duration_ms=clip_duration,
                    algorithm_version=ALGORITHM_VERSION,
                )
                db.add(run)
            else:
                run.status = "processing"
                run.requested_count = count
                run.clip_duration_ms = clip_duration
                run.algorithm_version = ALGORITHM_VERSION
                run.error = None
                run.updated_at = func.now()
            await db.commit()

            frame_rows = (
                await db.execute(
                    select(
                        Frame.id,
                        Frame.t_ms,
                        Frame.embedding,
                        Frame.thumbnail_key,
                        Frame.visibility_score,
                    )
                    .where(Frame.session_id == session_id, Frame.embedding.is_not(None))
                    .order_by(Frame.t_ms)
                )
            ).all()
            event_rows = (
                await db.execute(
                    select(Event.t_ms, Event.score, Event.type).where(
                        Event.session_id == session_id,
                        or_(Event.source.is_(None), Event.source != EVENT_SOURCE),
                    )
                )
            ).all()
            transcript_rows = (
                await db.execute(
                    select(Transcript.start_ms, Transcript.end_ms, Transcript.text)
                    .where(Transcript.session_id == session_id)
                    .order_by(Transcript.start_ms)
                )
            ).all()
            duration_ms = session.duration_ms
            user_id = session.user_id
            base_title = session.title or session.game or "Session"
            poster_key = session.poster_key

        if not frame_rows:
            raise RuntimeError("session has no extracted frames to score")

        prompts = await asyncio.to_thread(prompt_embeddings, deps.embedder)
        frame_inputs = await _backfill_visibility(frame_rows, deps)
        scores = score_frames(
            frame_inputs,
            [EventInput(*row) for row in event_rows],
            [TranscriptInput(*row) for row in transcript_rows],
            prompts,
        )
        scores, windows = select_highlights(
            scores,
            duration_ms,
            count,
            clip_duration,
            deps.settings.frame_virality_min_score,
        )
        if not windows:
            raise RuntimeError("video is too short to create a highlight clip")

        async with deps.sessionmaker() as db:
            await db.execute(delete(FrameViralityScore).where(FrameViralityScore.session_id == session_id))
            await db.execute(delete(Event).where(Event.session_id == session_id, Event.source == EVENT_SOURCE))
            await db.execute(
                delete(Clip).where(
                    Clip.session_id == session_id,
                    Clip.generation_source == "frame_virality",
                )
            )
            await db.execute(
                insert(FrameViralityScore),
                [
                    dict(
                        session_id=session_id,
                        frame_id=frame.frame_id,
                        t_ms=frame.t_ms,
                        score=frame.score,
                        visual_score=frame.visual_score,
                        novelty_score=frame.novelty_score,
                        event_score=frame.event_score,
                        speech_score=frame.speech_score,
                        visibility_score=frame.visibility_score,
                        scene_score=frame.scene_score,
                        selected=frame.selected,
                    )
                    for frame in scores
                ],
            )
            for rank, window in enumerate(sorted(windows, key=lambda item: -item.frame.score), 1):
                frame = window.frame
                db.add(
                    Event(
                        session_id=session_id,
                        t_ms=frame.t_ms,
                        type="viral_moment",
                        score=frame.score,
                        source=EVENT_SOURCE,
                        metadata_={
                            "rank": rank,
                            "visual_score": frame.visual_score,
                            "novelty_score": frame.novelty_score,
                            "event_score": frame.event_score,
                            "speech_score": frame.speech_score,
                            "visibility_score": frame.visibility_score,
                            "scene_score": frame.scene_score,
                            "algorithm_version": ALGORITHM_VERSION,
                        },
                    )
                )
                db.add(
                    Clip(
                        session_id=session_id,
                        user_id=user_id,
                        title=f"{base_title}: AI highlight #{rank}",
                        start_ms=window.start_ms,
                        end_ms=window.end_ms,
                        thumbnail_key=frame.thumbnail_key or poster_key,
                        status="ready",
                        kind="auto",
                        generation_source="frame_virality",
                        publish_state=deps.settings.new_clip_publish_state,
                        published_at=func.now() if deps.settings.new_clip_publish_state == "published" else None,
                    )
                )

            run = await db.get(FrameHighlightRun, session_id)
            if run is None:
                raise RuntimeError("frame highlight run disappeared")
            run.status = "ready"
            run.error = None
            run.updated_at = func.now()
            await db.commit()

        log.info(
            "frame highlights ready",
            extra={"session_id": str(session_id), "frames": len(scores), "clips": len(windows)},
        )
        return str(session_id)
    except Exception as error:
        await _mark_failed(session_id, deps, error)
        raise
