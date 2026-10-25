"""Asynchronous AI-share highlights for clips already stored by MinedIt.

The job reuses the clip export, creator pack, sampled frame embeddings, events, and
transcript produced by the normal pipeline. Only the final portrait render is new.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from sqlalchemy import select

from app.db.models import Clip, Event, Frame, Session, Transcript
from app.schemas import ClipHighlightsIn, CreatorPackOut
from app.services.frame_virality import (
    EventInput,
    FrameInput,
    HighlightWindow,
    TranscriptInput,
    image_visibility_score,
    prompt_embeddings,
    score_frames,
    select_contextual_highlights,
)
from app.services.music_catalog import MusicCatalog, infer_music_profile
from app.worker import media
from app.worker.creator_pack import build_creator_pack, pack_key
from app.worker.export import export_clip
from app.worker.pipeline import Deps


log = logging.getLogger("clip_highlights")
ALGORITHM_VERSION = "stored-ai-share-v4-public-r2-music"
STATUS_TTL_S = 24 * 3600


def _options_dict(options: ClipHighlightsIn | dict) -> dict:
    return options.model_dump(mode="json") if isinstance(options, ClipHighlightsIn) else ClipHighlightsIn.model_validate(options).model_dump(mode="json")


def options_hash(options: ClipHighlightsIn | dict) -> str:
    payload = json.dumps(
        {"algorithm_version": ALGORITHM_VERSION, **_options_dict(options)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def highlight_result_key(
    clip_id: uuid.UUID | str,
    start_ms: int,
    end_ms: int,
    options: ClipHighlightsIn | dict,
) -> str:
    return f"highlights/{clip_id}/{start_ms}-{end_ms}-{options_hash(options)}.json"


def highlight_video_key(
    clip_id: uuid.UUID | str,
    start_ms: int,
    end_ms: int,
    options: ClipHighlightsIn | dict,
) -> str:
    return f"highlights/{clip_id}/{start_ms}-{end_ms}-{options_hash(options)}.mp4"


def highlight_status_key(
    clip_id: uuid.UUID | str,
    start_ms: int,
    end_ms: int,
    options: ClipHighlightsIn | dict,
) -> str:
    return f"clip-highlights:{clip_id}:{start_ms}-{end_ms}:{options_hash(options)}"


def status_payload(status: str, stage: str, progress: float, error: str | None = None) -> str:
    return json.dumps(
        {
            "status": status,
            "stage": stage,
            "progress": round(min(1.0, max(0.0, progress)), 3),
            "error": error,
        },
        separators=(",", ":"),
    )


def _timestamp_ms(value: str) -> int | None:
    try:
        parts = [float(part) for part in value.strip().split(":")]
    except (AttributeError, TypeError, ValueError):
        return None
    if not parts or len(parts) > 3 or any(part < 0 for part in parts):
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return round(seconds * 1000)


def _pack_moments(pack: CreatorPackOut, duration_ms: int) -> list[tuple[int, str]]:
    moments = []
    for moment in pack.key_moments:
        timestamp = _timestamp_ms(moment.timestamp)
        if timestamp is not None and 0 <= timestamp < duration_ms and moment.label.strip():
            moments.append((timestamp, " ".join(moment.label.split())))
    return sorted(moments)


def _pack_transcript(pack: CreatorPackOut, duration_ms: int) -> list[TranscriptInput]:
    starts = []
    for cue in pack.transcript:
        timestamp = _timestamp_ms(cue.timestamp)
        if timestamp is not None and 0 <= timestamp < duration_ms and cue.text.strip():
            starts.append((timestamp, " ".join(cue.text.split())))
    starts.sort()
    return [
        TranscriptInput(
            start,
            min(duration_ms, max(start + 1500, starts[index + 1][0] if index + 1 < len(starts) else start + 3500)),
            text,
        )
        for index, (start, text) in enumerate(starts)
    ]


def _select_windows(scores, duration_ms: int, mode: str):
    if mode == "single":
        marked, windows = select_contextual_highlights(
            scores,
            duration_ms,
            count=1,
            min_clip_ms=min(duration_ms, 10_000),
            max_clip_ms=min(duration_ms, 25_000),
        )
        if windows:
            window = windows[0]
            length = window.end_ms - window.start_ms
            start = max(0, window.frame.t_ms - 2_000)
            end = min(duration_ms, start + length)
            windows = [replace(window, start_ms=start, end_ms=end)]
        return marked, windows

    count = max(1, min(6, (duration_ms + 29_999) // 30_000))
    marked, windows = select_contextual_highlights(
        scores,
        duration_ms,
        count=count,
        min_clip_ms=min(duration_ms, 4_000),
        max_clip_ms=min(duration_ms, 10_000),
    )
    if windows:
        peak = max(window.frame.score for window in windows)
        floor = max(0.22, peak * 0.68)
        windows = [window for window in windows if window.frame.score >= floor] or [
            max(windows, key=lambda window: window.frame.score)
        ]
        selected = {window.frame.frame_id for window in windows}
        marked = [replace(frame, selected=frame.frame_id in selected) for frame in marked]
    return marked, sorted(windows, key=lambda window: window.start_ms)


def _moment_reason(
    window: HighlightWindow,
    pack_moments: list[tuple[int, str]],
    events: list[EventInput],
) -> str:
    inside = [(abs(t_ms - window.frame.t_ms), label) for t_ms, label in pack_moments if window.start_ms <= t_ms <= window.end_ms]
    if inside:
        return min(inside)[1]
    nearby = [(abs(t_ms - window.frame.t_ms), label) for t_ms, label in pack_moments]
    if nearby and min(nearby)[0] <= 8_000:
        return min(nearby)[1]
    event = min(events, key=lambda item: abs(item.t_ms - window.frame.t_ms), default=None)
    if event is not None and abs(event.t_ms - window.frame.t_ms) <= 8_000:
        return event.type.replace("_", " ").capitalize()
    seconds = window.frame.t_ms // 1000
    return f"Strong sustained moment around {seconds // 60}:{seconds % 60:02d}"


def build_caption_lines(
    pack: CreatorPackOut,
    windows: list[HighlightWindow],
    *,
    include_hook: bool,
    reasons: list[str],
) -> list[dict]:
    """Map creator-pack timestamps from source time onto the rendered montage timeline."""
    duration_ms = max((window.end_ms for window in windows), default=0)
    transcript = _pack_transcript(pack, duration_ms)
    key_moments = _pack_moments(pack, duration_ms)
    lines: list[dict] = []
    rendered_duration = sum(window.end_ms - window.start_ms for window in windows)
    hook_end = min(2_500, rendered_duration)
    if include_hook and hook_end >= 500 and pack.title_options:
        lines.append({"start_ms": 0, "end_ms": hook_end, "text": pack.title_options[0], "kind": "hook"})

    output_offset = 0
    speech_count = 0
    for window in windows:
        for cue in transcript:
            if cue.start_ms >= window.end_ms or cue.end_ms <= window.start_ms:
                continue
            start = output_offset + max(cue.start_ms, window.start_ms) - window.start_ms
            end = output_offset + min(cue.end_ms, window.end_ms) - window.start_ms
            if include_hook:
                start = max(start, hook_end)
            if end - start >= 400:
                lines.append({"start_ms": start, "end_ms": end, "text": cue.text, "kind": "speech"})
                speech_count += 1
        output_offset += window.end_ms - window.start_ms

    if speech_count == 0:
        output_offset = 0
        for index, window in enumerate(windows):
            labels = [(t_ms, label) for t_ms, label in key_moments if window.start_ms <= t_ms < window.end_ms]
            if not labels:
                labels = [(window.start_ms + 500, reasons[index])]
            for t_ms, label in labels[:2]:
                start = output_offset + max(0, t_ms - window.start_ms)
                if include_hook:
                    start = max(start, hook_end)
                end = min(output_offset + (window.end_ms - window.start_ms), start + 2_500)
                if end - start >= 400:
                    lines.append({"start_ms": start, "end_ms": end, "text": label, "kind": "moment"})
            output_offset += window.end_ms - window.start_ms

    unique = {}
    for line in lines:
        text = " ".join(str(line["text"]).split()).strip()
        if text:
            unique[(line["start_ms"], line["end_ms"], text, line["kind"])] = {**line, "text": text}
    return sorted(unique.values(), key=lambda line: (line["start_ms"], line["end_ms"], line["kind"]))


def _sample_export_frames(source: Path, workdir: Path, deps: Deps, duration_ms: int) -> list[FrameInput]:
    """Fallback for legacy clips whose pipeline did not persist frame embeddings."""
    duration_seconds = max(0.001, duration_ms / 1000)
    fps = min(
        deps.settings.standalone_highlight_sample_fps,
        deps.settings.standalone_highlight_max_frames / duration_seconds,
    )
    sampled = media.sample_frames(source, workdir / "fallback-frames", fps=fps, width=deps.settings.frame_thumb_width)
    namespace = uuid.uuid4()
    result = []
    for offset in range(0, len(sampled), deps.settings.embed_batch_size):
        batch = sampled[offset : offset + deps.settings.embed_batch_size]
        images = [path.read_bytes() for _, path in batch]
        vectors = deps.embedder.embed_images(images)
        for (t_ms, _), image, vector in zip(batch, images, vectors, strict=True):
            if t_ms < duration_ms:
                result.append(
                    FrameInput(
                        uuid.uuid5(namespace, str(t_ms)),
                        t_ms,
                        vector,
                        visibility_score=image_visibility_score(image),
                    )
                )
    return result


async def run_clip_highlights(
    clip_id: uuid.UUID | str,
    deps: Deps,
    options: ClipHighlightsIn | dict,
    redis=None,
) -> str:
    """Build or reuse one stored-clip highlight and return its manifest key."""
    clip_id = uuid.UUID(str(clip_id))
    options = ClipHighlightsIn.model_validate(options)
    async with deps.sessionmaker() as db:
        clip = await db.get(Clip, clip_id)
        if clip is None:
            raise LookupError(f"clip {clip_id} not found")
        session = await db.get(Session, clip.session_id)
        if session is None:
            raise LookupError(f"session {clip.session_id} not found")
        start, end = clip.start_ms, clip.end_ms
        duration_ms = end - start
        frame_rows = (
            await db.scalars(
                select(Frame)
                .where(Frame.session_id == clip.session_id, Frame.t_ms >= start, Frame.t_ms < end)
                .order_by(Frame.t_ms)
            )
        ).all()
        event_rows = (
            await db.scalars(
                select(Event)
                .where(Event.session_id == clip.session_id, Event.t_ms >= start, Event.t_ms < end)
                .order_by(Event.t_ms)
            )
        ).all()
        transcript_rows = (
            await db.scalars(
                select(Transcript)
                .where(Transcript.session_id == clip.session_id, Transcript.start_ms < end, Transcript.end_ms > start)
                .order_by(Transcript.start_ms)
            )
        ).all()

    max_duration_ms = deps.settings.stored_highlight_max_minutes * 60_000
    if duration_ms > max_duration_ms:
        raise ValueError(f"clip is longer than the {deps.settings.stored_highlight_max_minutes}-minute highlight limit")

    result_key = highlight_result_key(clip_id, start, end, options)
    video_key = highlight_video_key(clip_id, start, end, options)
    skey = highlight_status_key(clip_id, start, end, options)
    if await asyncio.to_thread(deps.storage.exists, result_key):
        if redis is not None:
            await redis.set(skey, status_payload("ready", "rendering", 1.0), ex=STATUS_TTL_S)
        return result_key

    stage = "queued"

    async def set_status(status: str, next_stage: str, progress: float, error: str | None = None):
        nonlocal stage
        stage = next_stage
        if redis is not None:
            await redis.set(skey, status_payload(status, next_stage, progress, error), ex=STATUS_TTL_S)

    workdir = Path(tempfile.mkdtemp(prefix=f"minedtv-highlights-{clip_id}-"))
    try:
        await set_status("processing", "exporting", 0.08)
        mp4_key = await export_clip(clip_id, deps, redis)
        source = workdir / "source.mp4"
        await asyncio.to_thread(deps.storage.download_file, mp4_key, source)
        source_size_mb = source.stat().st_size / (1024 * 1024)
        if source_size_mb > deps.settings.stored_highlight_max_source_mb:
            raise ValueError(
                f"clip export exceeds the {deps.settings.stored_highlight_max_source_mb} MB highlight limit"
            )

        await set_status("processing", "analyzing", 0.28)
        pack_storage_key = await build_creator_pack(clip_id, deps, redis)
        pack_body = json.loads(await asyncio.to_thread(deps.storage.get_bytes, pack_storage_key))
        pack = CreatorPackOut.model_validate(pack_body["pack"])

        await set_status("processing", "selecting", 0.52)
        frames = [
            FrameInput(
                row.id,
                row.t_ms - start,
                tuple(row.embedding),
                row.thumbnail_key,
                row.visibility_score if row.visibility_score is not None else 1.0,
            )
            for row in frame_rows
            if row.embedding is not None
        ]
        if not frames:
            frames = await asyncio.to_thread(_sample_export_frames, source, workdir, deps, duration_ms)
        if not frames:
            raise ValueError("clip contains no frames that can be scored")

        events = [EventInput(row.t_ms - start, row.score, row.type) for row in event_rows]
        pack_moments = _pack_moments(pack, duration_ms)
        events.extend(EventInput(t_ms, 0.95, label) for t_ms, label in pack_moments)
        transcripts = [
            TranscriptInput(max(0, row.start_ms - start), min(duration_ms, row.end_ms - start), row.text)
            for row in transcript_rows
            if row.text.strip() and row.end_ms > start and row.start_ms < end
        ] or _pack_transcript(pack, duration_ms)
        prompts = prompt_embeddings(deps.embedder)
        scores = await asyncio.to_thread(
            score_frames,
            frames,
            events,
            transcripts,
            prompts,
        )
        scores, windows = _select_windows(scores, duration_ms, options.mode)
        if not windows:
            raise ValueError("clip is too short to create a highlight")
        reasons = [_moment_reason(window, pack_moments, events) for window in windows]

        await set_status("processing", "captioning", 0.68)
        caption_lines = (
            build_caption_lines(pack, windows, include_hook=options.hook, reasons=reasons)
            if options.captions
            else []
        )

        await set_status("processing", "rendering", 0.76)
        segments_dir = workdir / "segments"
        segments_dir.mkdir()
        segments = []
        for index, window in enumerate(windows, 1):
            segment = segments_dir / f"{index:02d}.mp4"
            await asyncio.to_thread(
                media.render_mobile_clip,
                source,
                segment,
                window.start_ms,
                window.end_ms,
                width=deps.settings.standalone_mobile_width,
                height=deps.settings.standalone_mobile_height,
                crf=deps.settings.transcode_crf,
            )
            segments.append(segment)

        uncaptioned = workdir / "highlight-uncaptioned.mp4"
        await asyncio.to_thread(media.concatenate_mp4_segments, segments, uncaptioned)
        output = workdir / "highlight.mp4"
        rendered = workdir / "highlight-rendered.mp4" if options.music else output
        if caption_lines:
            ass = await asyncio.to_thread(
                media.write_ass_captions,
                [(line["start_ms"], line["end_ms"], line["text"]) for line in caption_lines],
                workdir / "captions.ass",
                style=options.caption_style,
            )
            await asyncio.to_thread(
                media.burn_ass_captions,
                uncaptioned,
                rendered,
                ass,
                crf=deps.settings.transcode_crf,
            )
        else:
            shutil.move(uncaptioned, rendered)

        selected_music = None
        if options.music:
            try:
                selected_ids = {window.frame.frame_id for window in windows}
                music_text = " ".join(
                    [pack.description, pack.summary, pack.caption, *(label for _, label in pack_moments)]
                )
                mood, energy = infer_music_profile(frames, selected_ids, prompts, text=music_text)
                catalog = MusicCatalog(deps.settings.highlight_music_catalog_url)
                track = await asyncio.to_thread(catalog.select, mood, energy, str(clip_id))
                music_file = await asyncio.to_thread(catalog.download, track, workdir / f"music-{track.id}.mp3")
                rendered_duration = sum(window.end_ms - window.start_ms for window in windows)
                await asyncio.to_thread(
                    media.mix_background_music,
                    rendered,
                    music_file,
                    output,
                    duration_ms=rendered_duration,
                    volume=deps.settings.highlight_music_volume,
                    speech_volume=deps.settings.highlight_music_speech_volume,
                    speech_intervals_ms=[
                        (line["start_ms"], line["end_ms"])
                        for line in caption_lines
                        if line["kind"] == "speech"
                    ],
                )
                selected_music = track.response(mood)
            except Exception:
                log.warning("Background music unavailable; returning stored highlight without it", exc_info=True)
                output.unlink(missing_ok=True)
                shutil.move(rendered, output)

        await set_status("processing", "rendering", 0.94)
        await asyncio.to_thread(deps.storage.put_file, video_key, output, "video/mp4")
        rendered_duration = sum(window.end_ms - window.start_ms for window in windows)
        manifest = {
            "algorithm_version": ALGORITHM_VERSION,
            "video_key": video_key,
            "width": deps.settings.standalone_mobile_width,
            "height": deps.settings.standalone_mobile_height,
            "duration_ms": rendered_duration,
            "frames_analyzed": len(scores),
            "captions_burned": bool(caption_lines),
            "music_mixed": selected_music is not None,
            "music": selected_music,
            "moments": [
                {
                    "source_start_ms": window.start_ms,
                    "source_end_ms": window.end_ms,
                    "score": window.frame.score,
                    "reason": reasons[index],
                }
                for index, window in enumerate(windows)
            ],
            "captions": caption_lines,
            "summary": pack.summary,
            "suggested_caption": pack.caption,
            "hashtags": [tag.lstrip("#") for tag in pack.hashtags if tag.strip()],
            "options": options.model_dump(mode="json"),
        }
        await asyncio.to_thread(
            deps.storage.put_bytes,
            result_key,
            json.dumps(manifest, ensure_ascii=False).encode(),
            "application/json",
        )
        await set_status("ready", "rendering", 1.0)
        log.info(
            "stored clip highlight ready",
            extra={"clip_id": str(clip_id), "mode": options.mode, "duration_ms": rendered_duration},
        )
        return result_key
    except Exception as exc:
        await set_status("failed", stage, 0.0, f"{type(exc).__name__}: {exc}"[:500])
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
