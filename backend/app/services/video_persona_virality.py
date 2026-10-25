"""Frame-aware evidence for direct-upload persona virality simulations.

The expensive work is deliberately local: sample the source once, embed frames in
batches, then reuse the frame-virality curve and adaptive context selection from the
highlight features. Gemini still creates one persona panel; there is never one model
request per frame or per persona.
"""

from __future__ import annotations

import math
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.config import Settings
from app.ml.interfaces import Embedder
from app.schemas import CreatorPackOut, VideoViralityEvidenceOut, VideoViralityMomentOut
from app.services.frame_virality import (
    EventInput,
    FrameInput,
    TranscriptInput,
    image_visibility_score,
    prompt_embeddings,
    score_frames,
    select_contextual_highlights,
)
from app.worker import media


ALGORITHM_VERSION = "persona-frame-virality-v2-calibrated"
# The underlying frame scorer reserves 28% for detector events and 12% for
# excited speech. A visually excellent silent clip therefore tops out around
# 0.60-0.70 instead of 1.0. Normalize that practical ceiling before blending
# the frame evidence with the persona score.
FRAME_SCORE_REFERENCE_CEILING = 0.70


@dataclass(frozen=True)
class PreparedVideoFrames:
    duration_ms: int
    frames: tuple[FrameInput, ...]


def _timestamp_ms(value: str) -> int | None:
    """Parse creator timestamps such as MM:SS, HH:MM:SS, or plain seconds."""
    try:
        parts = [float(part) for part in value.strip().split(":")]
    except (TypeError, ValueError):
        return None
    if not parts or len(parts) > 3 or any(part < 0 for part in parts):
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return round(seconds * 1000)


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(1.0, max(0.0, quantile)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _moment_weight(label: str) -> float:
    normalized = label.lower()
    high_signal = (
        "ace", "boss", "clutch", "crash", "escape", "finish", "funny", "goal",
        "kill", "reveal", "save", "scare", "twist", "win", "victory",
    )
    return 0.95 if any(word in normalized for word in high_signal) else 0.78


def _calibrate_frame_score(raw_score: float) -> float:
    """Map the scorer's practical 0..0.70 range onto the public 0..100 index."""
    return 100 * min(1.0, max(0.0, raw_score) / FRAME_SCORE_REFERENCE_CEILING)


def _analysis_events(analysis: CreatorPackOut, duration_ms: int) -> list[EventInput]:
    events = []
    for moment in analysis.key_moments:
        timestamp = _timestamp_ms(moment.timestamp)
        if timestamp is not None and 0 <= timestamp < duration_ms:
            events.append(EventInput(timestamp, _moment_weight(moment.label), moment.label))
    return events


def _analysis_transcript(analysis: CreatorPackOut, duration_ms: int) -> list[TranscriptInput]:
    cues: list[tuple[int, str]] = []
    for cue in analysis.transcript:
        timestamp = _timestamp_ms(cue.timestamp)
        if timestamp is not None and 0 <= timestamp < duration_ms and cue.text.strip():
            cues.append((timestamp, cue.text.strip()))
    cues.sort()
    return [
        TranscriptInput(
            start,
            min(duration_ms, max(start + 1500, cues[index + 1][0] if index + 1 < len(cues) else start + 3500)),
            text,
        )
        for index, (start, text) in enumerate(cues)
    ]


class VideoPersonaViralityEngine:
    """Prepare frame embeddings once and convert them into audience evidence."""

    def __init__(self, settings: Settings, embedder: Embedder):
        self.settings = settings
        self.embedder = embedder

    def prepare(self, source: Path) -> PreparedVideoFrames:
        if not media.tools_available():
            raise RuntimeError("video virality requires ffmpeg and ffprobe on the API host")
        info = media.probe(source)
        run_namespace = uuid.uuid4()
        inputs: list[FrameInput] = []
        duration_seconds = max(0.001, info.duration_ms / 1000)
        effective_fps = min(
            self.settings.creator_virality_sample_fps,
            self.settings.creator_virality_max_frames / duration_seconds,
        )
        with tempfile.TemporaryDirectory(prefix="minedtv-persona-frames-") as directory:
            sampled = media.sample_frames(
                source,
                Path(directory),
                fps=effective_fps,
                width=self.settings.frame_thumb_width,
            )
            sampled = [(t_ms, path) for t_ms, path in sampled if t_ms < info.duration_ms]
            if not sampled:
                raise RuntimeError("the uploaded video did not produce any frames")

            for offset in range(0, len(sampled), self.settings.embed_batch_size):
                batch = sampled[offset : offset + self.settings.embed_batch_size]
                images = [path.read_bytes() for _, path in batch]
                vectors = self.embedder.embed_images(images)
                if len(vectors) != len(batch):
                    raise RuntimeError("embedder returned the wrong number of frame vectors")
                for (t_ms, _), vector, image in zip(batch, vectors, images, strict=True):
                    inputs.append(
                        FrameInput(
                            frame_id=uuid.uuid5(run_namespace, str(t_ms)),
                            t_ms=t_ms,
                            embedding=vector,
                            visibility_score=image_visibility_score(image),
                        )
                    )
        return PreparedVideoFrames(info.duration_ms, tuple(inputs))

    def evidence(self, prepared: PreparedVideoFrames, analysis: CreatorPackOut) -> VideoViralityEvidenceOut:
        scores = score_frames(
            prepared.frames,
            _analysis_events(analysis, prepared.duration_ms),
            _analysis_transcript(analysis, prepared.duration_ms),
            prompt_embeddings(self.embedder),
        )
        if not scores:
            raise RuntimeError("the uploaded video did not produce a frame score")

        candidate_count = max(1, min(5, (prepared.duration_ms + 29_999) // 30_000))
        scores, windows = select_contextual_highlights(
            scores,
            prepared.duration_ms,
            count=candidate_count,
            min_clip_ms=min(4_000, prepared.duration_ms),
            max_clip_ms=min(12_000, prepared.duration_ms),
        )
        if windows:
            peak_window_score = max(window.frame.score for window in windows)
            meaningful_floor = max(0.22, peak_window_score * 0.68)
            windows = [window for window in windows if window.frame.score >= meaningful_floor] or [
                max(windows, key=lambda window: window.frame.score)
            ]
        values = [frame.score for frame in scores]
        peak = max(values)
        sustained = _percentile(values, 0.75)
        opening_limit = min(prepared.duration_ms, max(5_000, round(prepared.duration_ms * 0.15)))
        opening = [frame.score for frame in scores if frame.t_ms <= opening_limit]
        hook = max(opening or values)
        visibility = sum(frame.visibility_score for frame in scores) / len(scores)
        novelty = _percentile([frame.novelty_score for frame in scores], 0.75)
        strong_floor = max(0.42, peak * 0.68)
        coverage = sum(frame.score >= strong_floor for frame in scores) / len(scores)
        coverage_strength = min(1.0, coverage / 0.25)
        raw_frame_score = (
            0.32 * peak
            + 0.20 * sustained
            + 0.18 * hook
            + 0.12 * visibility
            + 0.10 * novelty
            + 0.08 * coverage_strength
        )
        frame_score = _calibrate_frame_score(raw_frame_score)

        moments = [
            VideoViralityMomentOut(
                t_ms=window.frame.t_ms,
                context_start_ms=window.start_ms,
                context_end_ms=window.end_ms,
                score=round(window.frame.score * 100, 1),
                visual_score=round(window.frame.visual_score * 100, 1),
                novelty_score=round(window.frame.novelty_score * 100, 1),
                speech_score=round(window.frame.speech_score * 100, 1),
                visibility_score=round(window.frame.visibility_score * 100, 1),
                scene_score=round(window.frame.scene_score * 100, 1),
            )
            for window in windows
        ]
        return VideoViralityEvidenceOut(
            algorithm_version=ALGORITHM_VERSION,
            duration_ms=prepared.duration_ms,
            frames_analyzed=len(scores),
            frame_score=round(min(100.0, max(0.0, frame_score)), 1),
            peak_score=round(peak * 100, 1),
            hook_score=round(hook * 100, 1),
            sustained_score=round(sustained * 100, 1),
            coverage=round(coverage, 4),
            moments=moments,
        )
