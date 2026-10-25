"""Session processing pipeline.

Each step is idempotent: it deletes whatever an earlier run of the same step wrote for
the session before writing again. After each step the session row records `last_step`,
so a failed run can resume from the step that failed.
"""

import asyncio
import hashlib
import logging
import shutil
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import (
    PIPELINE_STEPS,
    STEP_STATUS,
    Clip,
    Event,
    Frame,
    NotificationType,
    Segment,
    Session,
    SessionStatus,
    Transcript,
)
from app.db.session import get_sessionmaker
from app.log import bind
from app.ml.interfaces import DetectedEvent, Embedder, HighlightDetector, Transcriber, TranscriptChunk
from app.ml.moderation import ContentPolicyViolation, get_moderator
from app.services.queries import nearest_frame_key
from app.services.social import notify
from app.services.storage import Storage, get_storage
from app.worker import media

log = logging.getLogger("pipeline")


@dataclass
class Deps:
    storage: Storage
    embedder: Embedder
    transcriber: Transcriber
    detector: HighlightDetector
    sessionmaker: async_sessionmaker[AsyncSession]
    settings: Settings

    @classmethod
    def default(cls) -> "Deps":
        from app.ml.registry import get_embedder, get_highlight_detector, get_transcriber

        return cls(
            storage=get_storage(),
            embedder=get_embedder(),
            transcriber=get_transcriber(),
            detector=get_highlight_detector(),
            sessionmaker=get_sessionmaker(),
            settings=get_settings(),
        )


@dataclass
class Ctx:
    session_id: uuid.UUID
    deps: Deps
    workdir: Path
    _source: Path | None = field(default=None, init=False)

    @property
    def settings(self) -> Settings:
        return self.deps.settings

    async def session(self, db: AsyncSession) -> Session:
        s = await db.get(Session, self.session_id, populate_existing=True)
        if s is None:
            raise LookupError(f"session {self.session_id} not found")
        return s

    async def source_path(self) -> Path:
        """The original upload, downloaded once per run."""
        if self._source is None:
            async with self.deps.sessionmaker() as db:
                key = (await self.session(db)).source_key
            path = self.workdir / f"source{Path(key).suffix}"
            t0 = time.monotonic()
            await asyncio.to_thread(self.deps.storage.download_file, key, path)
            log.info("downloaded source", extra={"bytes": path.stat().st_size, "secs": round(time.monotonic() - t0, 2)})
            self._source = path
        return self._source


def _upload_many(storage: Storage, items: list[tuple[str, Path, str]], concurrency: int) -> None:
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda it: storage.put_file(it[0], it[1], it[2]), items))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- steps


async def step_probe(ctx: Ctx) -> None:
    info = await asyncio.to_thread(media.probe, await ctx.source_path())
    max_min = ctx.deps.settings.max_video_minutes
    if info.duration_ms and info.duration_ms > max_min * 60_000:
        raise ValueError(f"Video is {info.duration_ms / 60_000:.0f} minutes long; the limit is {max_min} minutes")
    async with ctx.deps.sessionmaker() as db:
        s = await ctx.session(db)
        s.duration_ms, s.width, s.height, s.fps, s.has_audio = (
            info.duration_ms, info.width, info.height, info.fps, info.has_audio
        )
        await db.commit()
    log.info("probed", extra={"duration_ms": info.duration_ms, "res": f"{info.width}x{info.height}", "fps": info.fps})


async def step_segment(ctx: Ctx) -> None:
    st = ctx.settings
    async with ctx.deps.sessionmaker() as db:
        s = await ctx.session(db)
        prefix, has_audio = s.storage_prefix, bool(s.has_audio)
    out_dir = ctx.workdir / "hls"
    shutil.rmtree(out_dir, ignore_errors=True)
    t0 = time.monotonic()
    segs = await asyncio.to_thread(
        media.transcode_hls,
        await ctx.source_path(),
        out_dir,
        height=st.transcode_height,
        crf=st.transcode_crf,
        segment_s=st.segment_seconds,
        has_audio=has_audio,
    )
    log.info("transcoded", extra={"segments": len(segs), "secs": round(time.monotonic() - t0, 2)})

    await asyncio.to_thread(ctx.deps.storage.delete_prefix, f"{prefix}/hls/")
    keyed = [(f"{prefix}/hls/{seg.path.name}", seg) for seg in segs]
    await asyncio.to_thread(
        _upload_many, ctx.deps.storage, [(k, seg.path, "video/mp2t") for k, seg in keyed], st.upload_concurrency
    )
    hashes = await asyncio.to_thread(lambda: [_sha256(seg.path) for seg in segs])
    rows = [
        dict(session_id=ctx.session_id, idx=seg.idx, start_ms=seg.start_ms, duration_ms=seg.duration_ms, storage_key=k, content_hash=h)
        for (k, seg), h in zip(keyed, hashes, strict=True)
    ]
    async with ctx.deps.sessionmaker() as db:
        await db.execute(delete(Segment).where(Segment.session_id == ctx.session_id))
        await db.execute(insert(Segment), rows)
        # Segments are the source of truth for what's playable.
        (await ctx.session(db)).duration_ms = segs[-1].start_ms + segs[-1].duration_ms
        await db.commit()
    shutil.rmtree(out_dir, ignore_errors=True)


async def step_thumbnails(ctx: Ctx) -> None:
    async with ctx.deps.sessionmaker() as db:
        s = await ctx.session(db)
        prefix, duration_ms = s.storage_prefix, s.duration_ms or 0
    t_s = min(duration_ms * 0.1, 5_000) / 1000  # early enough to be in the action, past any fade-in
    poster = await asyncio.to_thread(media.extract_image, await ctx.source_path(), ctx.workdir / "poster.jpg", t_s, 1280)
    key = f"{prefix}/poster.jpg"
    await asyncio.to_thread(ctx.deps.storage.put_file, key, poster, "image/jpeg")
    async with ctx.deps.sessionmaker() as db:
        (await ctx.session(db)).poster_key = key
        await db.commit()


async def step_frames(ctx: Ctx) -> None:
    st = ctx.settings
    async with ctx.deps.sessionmaker() as db:
        s = await ctx.session(db)
        prefix, duration_ms = s.storage_prefix, s.duration_ms or 0
    out_dir = ctx.workdir / "frames"
    shutil.rmtree(out_dir, ignore_errors=True)
    frames = await asyncio.to_thread(
        media.sample_frames, await ctx.source_path(), out_dir, fps=st.frame_sample_fps, width=st.frame_thumb_width
    )
    frames = [(t, p) for t, p in frames if t < max(duration_ms, 1)]
    log.info("sampled frames", extra={"frames": len(frames)})

    await asyncio.to_thread(ctx.deps.storage.delete_prefix, f"{prefix}/frames/")
    async with ctx.deps.sessionmaker() as db:
        await db.execute(delete(Frame).where(Frame.session_id == ctx.session_id))
        await db.commit()

    for i in range(0, len(frames), st.embed_batch_size):
        batch = frames[i : i + st.embed_batch_size]
        images = [p.read_bytes() for _, p in batch]
        vectors = await asyncio.to_thread(ctx.deps.embedder.embed_images, images)
        keys = [f"{prefix}/frames/{t:09d}.jpg" for t, _ in batch]
        await asyncio.to_thread(
            _upload_many, ctx.deps.storage, [(k, p, "image/jpeg") for k, (_, p) in zip(keys, batch, strict=True)], st.upload_concurrency
        )
        async with ctx.deps.sessionmaker() as db:
            await db.execute(
                insert(Frame),
                [
                    dict(session_id=ctx.session_id, t_ms=t, thumbnail_key=k, embedding=v)
                    for (t, _), k, v in zip(batch, keys, vectors, strict=True)
                ],
            )
            await db.commit()
        log.info("embedded frames", extra={"done": i + len(batch), "total": len(frames)})
    shutil.rmtree(out_dir, ignore_errors=True)


def merge_transcript_chunks(chunks: list[TranscriptChunk], min_ms: int, max_ms: int) -> list[TranscriptChunk]:
    """Group consecutive transcriber chunks into windows of roughly min_ms..max_ms.

    A window closes once it reaches min_ms, or before a chunk would push it past max_ms,
    or when the speaker changes. Single chunks longer than max_ms are kept whole.
    """
    windows: list[TranscriptChunk] = []
    cur: TranscriptChunk | None = None
    for c in sorted(chunks, key=lambda c: c.start_ms):
        text = c.text.strip()
        if not text:
            continue
        if cur is not None and (
            cur.end_ms - cur.start_ms >= min_ms or c.end_ms - cur.start_ms > max_ms or c.speaker != cur.speaker
        ):
            windows.append(cur)
            cur = None
        if cur is None:
            cur = TranscriptChunk(c.start_ms, c.end_ms, text, c.speaker)
        else:
            cur = TranscriptChunk(cur.start_ms, max(cur.end_ms, c.end_ms), f"{cur.text} {text}", cur.speaker)
    if cur is not None:
        windows.append(cur)
    return windows


async def step_audio(ctx: Ctx) -> None:
    st = ctx.settings
    async with ctx.deps.sessionmaker() as db:
        s = await ctx.session(db)
        has_audio = bool(s.has_audio)
        await db.execute(delete(Transcript).where(Transcript.session_id == ctx.session_id))
        await db.commit()
    if not has_audio:
        log.info("no audio stream, skipping transcription")
        return
    audio = await asyncio.to_thread(media.extract_audio, await ctx.source_path(), ctx.workdir / "audio.ogg")
    t0 = time.monotonic()
    chunks = await asyncio.to_thread(ctx.deps.transcriber.transcribe, str(audio))
    windows = merge_transcript_chunks(chunks, st.transcript_min_window_ms, st.transcript_max_window_ms)
    log.info("transcribed", extra={"chunks": len(chunks), "windows": len(windows), "secs": round(time.monotonic() - t0, 2)})
    for i in range(0, len(windows), st.embed_batch_size):
        batch = windows[i : i + st.embed_batch_size]
        vectors = await asyncio.to_thread(ctx.deps.embedder.embed_texts, [w.text for w in batch])
        async with ctx.deps.sessionmaker() as db:
            await db.execute(
                insert(Transcript),
                [
                    dict(session_id=ctx.session_id, start_ms=w.start_ms, end_ms=w.end_ms, speaker=w.speaker, text=w.text, embedding=v)
                    for w, v in zip(batch, vectors, strict=True)
                ],
            )
            await db.commit()


async def step_moderate(ctx: Ctx) -> None:
    """Classify the real transcript. Raises ContentPolicyViolation on severe content,
    which stops the pipeline before finalize — see run_pipeline's except clause."""
    async with ctx.deps.sessionmaker() as db:
        rows = (
            await db.execute(select(Transcript.text).where(Transcript.session_id == ctx.session_id).order_by(Transcript.start_ms))
        ).scalars().all()
    text = " ".join(rows).strip()

    result = await asyncio.to_thread(get_moderator().classify, text)

    async with ctx.deps.sessionmaker() as db:
        s = await ctx.session(db)
        s.moderation_severity = result.severity
        s.moderation_reason = result.reason or None
        s.age_restricted = result.severity in ("mild", "severe")
        await db.commit()
    log.info("moderation classified", extra={"severity": result.severity, "categories": result.categories})

    if result.severity == "severe":
        raise ContentPolicyViolation(result.reason, result.categories)


async def step_highlights(ctx: Ctx) -> None:
    detector = ctx.deps.detector
    events: list[DetectedEvent] = await asyncio.to_thread(detector.detect, str(await ctx.source_path()), str(ctx.session_id))
    async with ctx.deps.sessionmaker() as db:
        duration_ms = (await ctx.session(db)).duration_ms or 0
        await db.execute(delete(Event).where(Event.session_id == ctx.session_id))
        rows = [
            dict(
                session_id=ctx.session_id,
                t_ms=min(max(0, int(e.t_ms)), duration_ms),
                type=e.type.lower(),
                score=float(e.score),
                source=type(detector).__name__,
                metadata_=e.metadata or {},
            )
            for e in events
        ]
        if rows:
            await db.execute(insert(Event), rows)
        await db.commit()
    log.info("detected highlights", extra={"events": len(events)})


def pick_highlight_windows(
    events: list[tuple[int, str, float]], duration_ms: int, half_window_ms: int, count: int
) -> list[tuple[int, int, int, str]]:
    """Top-scoring, non-overlapping windows around events: (start_ms, end_ms, t_ms, type)."""
    chosen: list[tuple[int, int, int, str]] = []
    for t, typ, _ in sorted(events, key=lambda e: -e[2]):
        start, end = max(0, t - half_window_ms), min(duration_ms, t + half_window_ms)
        if end - start < 1000 or any(start < e and end > s for s, e, _, _ in chosen):
            continue
        chosen.append((start, end, t, typ))
        if len(chosen) >= count:
            break
    return sorted(chosen)


async def step_finalize(ctx: Ctx) -> None:
    st = ctx.settings
    async with ctx.deps.sessionmaker() as db:
        s = await ctx.session(db)
        duration_ms = s.duration_ms or 0
        await db.execute(delete(Clip).where(Clip.session_id == s.id, Clip.kind == "auto"))
        events = (await db.execute(select(Event.t_ms, Event.type, Event.score).where(Event.session_id == s.id))).all()
        windows = pick_highlight_windows([tuple(e) for e in events], duration_ms, st.clip_window_ms, st.auto_clip_count)
        base_title = s.title or s.game or "Session"
        if windows:
            for start, end, t, typ in windows:
                db.add(
                    Clip(
                        session_id=s.id,
                        user_id=s.user_id,
                        title=f"{base_title}: {typ} at {t // 60000}:{t // 1000 % 60:02d}",
                        start_ms=start,
                        end_ms=end,
                        thumbnail_key=await nearest_frame_key(db, s.id, t) or s.poster_key,
                        status="ready",
                        kind="auto",
                        publish_state=st.new_clip_publish_state,
                        published_at=func.now() if st.new_clip_publish_state == "published" else None,
                        age_restricted=s.age_restricted,
                    )
                )
        else:
            db.add(
                Clip(
                    session_id=s.id,
                    user_id=s.user_id,
                    title=base_title,
                    start_ms=0,
                    end_ms=duration_ms,
                    thumbnail_key=s.poster_key,
                    status="ready",
                    kind="auto",
                    publish_state=st.new_clip_publish_state,
                    published_at=func.now() if st.new_clip_publish_state == "published" else None,
                    age_restricted=s.age_restricted,
                )
            )
        await db.flush()
        clip_ids = (await db.scalars(select(Clip.id).where(Clip.session_id == s.id, Clip.kind == "auto"))).all()
        # once=True: reprocessing the same upload doesn't notify again.
        await notify(
            db,
            user_id=s.user_id,
            type=NotificationType.UPLOAD_READY,
            session_id=s.id,
            clip_id=clip_ids[0] if clip_ids else None,
            data={"title": base_title, "clip_ids": [str(c) for c in clip_ids]},
            once=True,
        )
        await db.commit()
    log.info("created default clips", extra={"clips": len(windows) or 1})


STEP_FUNCS = {
    "probe": step_probe,
    "segment": step_segment,
    "thumbnails": step_thumbnails,
    "frames": step_frames,
    "audio": step_audio,
    "moderate": step_moderate,
    "highlights": step_highlights,
    "finalize": step_finalize,
}
assert list(STEP_FUNCS) == PIPELINE_STEPS


# ---------------------------------------------------------------- runner


async def run_pipeline(session_id: uuid.UUID | str, *, resume: bool = False, deps: Deps | None = None) -> str:
    """Process a session. Returns the final status ("ready", "failed", or "blocked" for
    severe moderation content); never raises for step errors."""
    session_id = uuid.UUID(str(session_id))
    deps = deps or Deps.default()
    with bind(session_id=str(session_id)):
        async with deps.sessionmaker() as db:
            s = await db.get(Session, session_id)
            if s is None:
                log.error("session not found")
                return SessionStatus.FAILED
            start = PIPELINE_STEPS.index(s.last_step) + 1 if resume and s.last_step in PIPELINE_STEPS else 0
            if start == 0:
                s.last_step = None
            s.failed_step, s.error = None, None
            await db.commit()

        steps = PIPELINE_STEPS[start:]
        log.info("pipeline start", extra={"steps": steps, "resume": resume})
        t_all = time.monotonic()
        workdir = Path(tempfile.mkdtemp(prefix=f"minedtv-{session_id}-"))
        ctx = Ctx(session_id, deps, workdir)
        step = None
        try:
            for step in steps:
                with bind(step=step):
                    async with deps.sessionmaker() as db:
                        (await ctx.session(db)).status = STEP_STATUS[step]
                        await db.commit()
                    t0 = time.monotonic()
                    await STEP_FUNCS[step](ctx)
                    async with deps.sessionmaker() as db:
                        (await ctx.session(db)).last_step = step
                        await db.commit()
                    log.info("step done", extra={"secs": round(time.monotonic() - t0, 2)})
            async with deps.sessionmaker() as db:
                (await ctx.session(db)).status = SessionStatus.READY
                await db.commit()
            log.info("pipeline ready", extra={"secs": round(time.monotonic() - t_all, 2)})
            return SessionStatus.READY
        except ContentPolicyViolation as e:
            with bind(step=step):
                log.warning("pipeline blocked by content policy", extra={"categories": e.categories})
            async with deps.sessionmaker() as db:
                s = await ctx.session(db)
                s.status, s.failed_step, s.error = SessionStatus.BLOCKED, step, e.reason
                await db.commit()
            return SessionStatus.BLOCKED
        except Exception as e:
            with bind(step=step):
                log.exception("pipeline step failed")
            async with deps.sessionmaker() as db:
                s = await ctx.session(db)
                s.status, s.failed_step, s.error = SessionStatus.FAILED, step, f"{type(e).__name__}: {e}"[:2000]
                await db.commit()
            return SessionStatus.FAILED
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
