"""Direct-upload highlight generation with no session/database dependency."""

from __future__ import annotations

import shutil
import time
import uuid
import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.ml.gemini_captions import GeminiCaptionEngine
from app.ml.interfaces import Embedder, TranscriptChunk, Transcriber
from app.services.frame_virality import (
    CONTEXTUAL_ALGORITHM_VERSION,
    FrameInput,
    ScoredFrame,
    image_visibility_score,
    prompt_embeddings,
    score_frames,
    select_contextual_highlights,
)
from app.worker import media


log = logging.getLogger(__name__)


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
    """Samples, scores, and renders highlights from one temporary source file."""

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
                scores, windows = select_contextual_highlights(
                    scores,
                    info.duration_ms,
                    count=1,
                )
                if not windows:
                    raise RuntimeError("the video is too short to create a highlight clip")

                clips: list[DirectHighlightClip] = []
                for index, window in enumerate(sorted(windows, key=lambda item: -item.frame.score), 1):
                    frame = window.frame
                    shutil.copyfile(paths_by_id[frame.frame_id], frames_dir / f"{frame.frame_id}.jpg")
                    cues, caption_source = self._caption_cues(
                        source,
                        work_dir,
                        window.start_ms,
                        window.end_ms,
                        info.has_audio,
                    )
                    caption_file = None
                    if cues:
                        caption_file = media.write_ass_captions(
                            [(cue.start_ms, cue.end_ms, cue.text) for cue in cues],
                            work_dir / f"captions-{index}.ass",
                        )
                    media.render_mobile_clip(
                        source,
                        clips_dir / f"{index}.mp4",
                        window.start_ms,
                        window.end_ms,
                        captions=caption_file,
                        width=self.settings.standalone_mobile_width,
                        height=self.settings.standalone_mobile_height,
                        crf=self.settings.transcode_crf,
                    )
                    clips.append(
                        DirectHighlightClip(
                            index=index,
                            title="The viral clip",
                            start_ms=window.start_ms,
                            end_ms=window.end_ms,
                            score=frame.score,
                            frame_id=frame.frame_id,
                            width=self.settings.standalone_mobile_width,
                            height=self.settings.standalone_mobile_height,
                            captions_burned=bool(cues),
                            caption_count=len(cues),
                            caption_source=caption_source,
                        )
                    )
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
    return CONTEXTUAL_ALGORITHM_VERSION
