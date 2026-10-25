"""Direct-upload highlight generation with no session/database dependency."""

from __future__ import annotations

import shutil
import time
import uuid
import logging
from dataclasses import dataclass, replace
from pathlib import Path

from app.config import Settings
from app.ml.gemini_captions import GeminiCaptionEngine
from app.ml.interfaces import Embedder, TranscriptChunk, Transcriber
from app.services.frame_virality import (
    FrameInput,
    ScoredFrame,
    image_visibility_score,
    prompt_embeddings,
    score_frames,
    select_contextual_highlights,
)
from app.worker import media


log = logging.getLogger(__name__)
MONTAGE_ALGORITHM_VERSION = "frame-virality-v4-highlight-montage"


@dataclass(frozen=True)
class DirectHighlightMoment:
    index: int
    start_ms: int
    end_ms: int
    score: float
    frame_id: uuid.UUID


@dataclass(frozen=True)
class DirectHighlightClip:
    index: int
    title: str
    start_ms: int
    end_ms: int
    score: float
    frame_id: uuid.UUID
    width: int
    height: int
    captions_burned: bool
    caption_count: int
    caption_source: str
    moments: tuple[DirectHighlightMoment, ...] = ()


@dataclass(frozen=True)
class DirectHighlightRun:
    run_id: uuid.UUID
    filename: str
    duration_ms: int
    width: int
    height: int
    scores: list[ScoredFrame]
    clips: list[DirectHighlightClip]


class StandaloneHighlightEngine:
    """Samples once, ranks major moments, and renders a combined highlight montage."""

    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        transcriber: Transcriber | None = None,
        caption_engine: GeminiCaptionEngine | None = None,
    ):
        self.settings = settings
        self.embedder = embedder
        self.transcriber = transcriber
        self.caption_engine = caption_engine
        self.root = Path(settings.standalone_highlight_dir).resolve()

    def _caption_cues(
        self,
        source: Path,
        work_dir: Path,
        start_ms: int,
        end_ms: int,
        has_audio: bool,
    ) -> tuple[list[TranscriptChunk], str]:
        """Caption only the chosen window, keeping frame-scoring latency unchanged."""
        if not has_audio or (self.transcriber is None and self.caption_engine is None):
            return [], "none"

        audio = work_dir / "caption-audio.opus"
        media.extract_audio_range(source, audio, start_ms, end_ms)
        cues: list[TranscriptChunk] = []
        source_name = "none"

        if self.transcriber is not None:
            try:
                cues = self.transcriber.transcribe(str(audio))
                if cues:
                    source_name = "transcriber"
            except Exception:
                log.warning("Configured caption transcriber failed; trying Gemini fallback", exc_info=True)

        if not cues and self.caption_engine is not None:
            try:
                cues = self.caption_engine.transcribe_audio(audio, duration_ms=end_ms - start_ms)
                if cues:
                    source_name = "gemini"
            except Exception:
                # A caption provider outage should not discard a successfully selected clip.
                log.warning("Gemini caption generation failed; rendering without captions", exc_info=True)

        duration_ms = end_ms - start_ms
        cleaned: list[TranscriptChunk] = []
        for cue in sorted(cues, key=lambda item: (item.start_ms, item.end_ms)):
            cue_start = max(0, min(duration_ms, int(cue.start_ms)))
            cue_end = max(cue_start + 500, min(duration_ms, int(cue.end_ms)))
            text = " ".join(cue.text.split()).strip()
            if text and cue_start < duration_ms:
                cleaned.append(TranscriptChunk(cue_start, min(cue_end, duration_ms), text, cue.speaker))
        return cleaned, source_name

    def _cleanup_expired(self) -> None:
        if not self.root.exists():
            return
        cutoff = time.time() - self.settings.standalone_highlight_ttl_s
        for directory in self.root.iterdir():
            if directory.is_dir() and directory.stat().st_mtime < cutoff:
                shutil.rmtree(directory, ignore_errors=True)

    def process(
        self,
        source: Path,
        filename: str,
    ) -> DirectHighlightRun:
        if not media.tools_available():
            raise RuntimeError("ffmpeg and ffprobe are required for direct highlight generation")

        info = media.probe(source)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cleanup_expired()
        run_id = uuid.uuid4()
        run_dir = self.root / str(run_id)
        clips_dir = run_dir / "clips"
        frames_dir = run_dir / "frames"
        work_dir = run_dir / "_work"
        clips_dir.mkdir(parents=True)
        frames_dir.mkdir()
        work_dir.mkdir()

        try:
            try:
                sampled_dir = work_dir / "frames"
                sampled = media.sample_frames(
                    source,
                    sampled_dir,
                    fps=self.settings.standalone_highlight_sample_fps,
                    width=self.settings.frame_thumb_width,
                )
                sampled = [(t_ms, path) for t_ms, path in sampled if t_ms < info.duration_ms]
                if not sampled:
                    raise RuntimeError("the uploaded video did not produce any frames")

                inputs: list[FrameInput] = []
                paths_by_id: dict[uuid.UUID, Path] = {}
                for offset in range(0, len(sampled), self.settings.embed_batch_size):
                    batch = sampled[offset : offset + self.settings.embed_batch_size]
                    images = [path.read_bytes() for _, path in batch]
                    vectors = self.embedder.embed_images(images)
                    if len(vectors) != len(batch):
                        raise RuntimeError("embedder returned the wrong number of frame vectors")
                    for (t_ms, path), vector, image in zip(batch, vectors, images, strict=True):
                        frame_id = uuid.uuid5(run_id, str(t_ms))
                        inputs.append(
                            FrameInput(
                                frame_id,
                                t_ms,
                                vector,
                                visibility_score=image_visibility_score(image),
                            )
                        )
                        paths_by_id[frame_id] = path

                scores = score_frames(inputs, [], [], prompt_embeddings(self.embedder))
                # Scale the number of candidates with source length while keeping the
                # finished montage concise. Each selected scene carries a little setup
                # and payoff, but no scene may consume more than ten seconds.
                candidate_count = max(1, min(6, (info.duration_ms + 29_999) // 30_000))
                scores, windows = select_contextual_highlights(
                    scores,
                    info.duration_ms,
                    count=candidate_count,
                    min_clip_ms=4_000,
                    max_clip_ms=10_000,
                )
                if not windows:
                    raise RuntimeError("the video is too short to create a highlight montage")

                # Do not pad the montage with weak local maxima just to hit a fixed
                # count. Always retain the best scene; include the rest only when they
                # are materially competitive with it.
                peak_score = max(window.frame.score for window in windows)
                threshold = max(0.22, peak_score * 0.68)
                significant = [window for window in windows if window.frame.score >= threshold]
                windows = significant or [max(windows, key=lambda item: item.frame.score)]
                windows = sorted(windows, key=lambda item: item.start_ms)

                selected_ids = {window.frame.frame_id for window in windows}
                scores = [replace(frame, selected=frame.frame_id in selected_ids) for frame in scores]
                marked_by_id = {frame.frame_id: frame for frame in scores}
                windows = [replace(window, frame=marked_by_id[window.frame.frame_id]) for window in windows]

                segments_dir = work_dir / "segments"
                segments_dir.mkdir()
                segments: list[Path] = []
                moments: list[DirectHighlightMoment] = []
                for index, window in enumerate(windows, 1):
                    frame = window.frame
                    shutil.copyfile(paths_by_id[frame.frame_id], frames_dir / f"{frame.frame_id}.jpg")
                    segment = segments_dir / f"{index:02d}.mp4"
                    media.render_mobile_clip(
                        source,
                        segment,
                        window.start_ms,
                        window.end_ms,
                        width=self.settings.standalone_mobile_width,
                        height=self.settings.standalone_mobile_height,
                        crf=self.settings.transcode_crf,
                    )
                    segments.append(segment)
                    moments.append(
                        DirectHighlightMoment(index, window.start_ms, window.end_ms, frame.score, frame.frame_id)
                    )

                uncaptioned = work_dir / "montage-uncaptioned.mp4"
                media.concatenate_mp4_segments(segments, uncaptioned)
                montage_duration_ms = sum(moment.end_ms - moment.start_ms for moment in moments)

                # Caption the assembled audio once, so timestamps naturally match the
                # montage and multiple selected source ranges do not trigger repeated
                # model calls.
                cues, caption_source = self._caption_cues(
                    uncaptioned,
                    work_dir,
                    0,
                    montage_duration_ms,
                    info.has_audio,
                )
                output = clips_dir / "1.mp4"
                if cues:
                    caption_file = media.write_ass_captions(
                        [(cue.start_ms, cue.end_ms, cue.text) for cue in cues],
                        work_dir / "montage-captions.ass",
                    )
                    media.burn_ass_captions(
                        uncaptioned,
                        output,
                        caption_file,
                        crf=self.settings.transcode_crf,
                    )
                else:
                    shutil.move(uncaptioned, output)

                representative = max(windows, key=lambda item: item.frame.score).frame
                clips = [
                    DirectHighlightClip(
                        index=1,
                        title="The highlight montage",
                        start_ms=0,
                        end_ms=montage_duration_ms,
                        score=representative.score,
                        frame_id=representative.frame_id,
                        width=self.settings.standalone_mobile_width,
                        height=self.settings.standalone_mobile_height,
                        captions_burned=bool(cues),
                        caption_count=len(cues),
                        caption_source=caption_source,
                        moments=tuple(moments),
                    )
                ]
            finally:
                # Windows can briefly retain FFmpeg handles; cleanup must not turn a
                # successfully rendered response into a 502.
                shutil.rmtree(work_dir, ignore_errors=True)

            return DirectHighlightRun(
                run_id=run_id,
                filename=filename,
                duration_ms=info.duration_ms,
                width=info.width,
                height=info.height,
                scores=scores,
                clips=clips,
            )
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise

    def clip_path(self, run_id: uuid.UUID, index: int) -> Path:
        return self.root / str(run_id) / "clips" / f"{index}.mp4"

    def frame_path(self, run_id: uuid.UUID, frame_id: uuid.UUID) -> Path:
        return self.root / str(run_id) / "frames" / f"{frame_id}.jpg"


def algorithm_version() -> str:
    return MONTAGE_ALGORITHM_VERSION
