"""Contracts between this backend and the search / highlight teams' models.

Implement any of these protocols in your own module and point the matching env var at it:

    EMBEDDER_BACKEND=my_pkg.my_module:MyEmbedder
    TRANSCRIBER_BACKEND=my_pkg.my_module:MyTranscriber
    HIGHLIGHT_BACKEND=my_pkg.my_module:MyDetector

The class is constructed with no arguments. Implementations are called from worker
threads and may block.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class TranscriptChunk:
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None


@dataclass
class DetectedEvent:
    t_ms: int
    type: str  # one of KNOWN_EVENT_TYPES where possible, so search can match it
    score: float  # 0..1, higher is more highlight-worthy
    metadata: dict[str, Any] = field(default_factory=dict)


# Event types search knows how to match from a text query. Detectors can emit others;
# they're stored and shown, just not matched by keyword.
KNOWN_EVENT_TYPES = ("kill", "multikill", "headshot", "clutch", "ace", "win", "death", "loud", "funny")


@runtime_checkable
class Embedder(Protocol):
    """Maps images and text into the same vector space (CLIP-style), so text queries find frames.

    Vectors must have length `dim` (== EMBEDDING_DIM) and should be L2-normalized.
    """

    dim: int

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        """images are encoded JPEG/PNG bytes."""
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(self, audio_path: str) -> list[TranscriptChunk]:
        """audio_path is a local mono 16 kHz audio file. Return chunks in time order."""
        ...


@runtime_checkable
class HighlightDetector(Protocol):
    def detect(self, video_path: str, session_id: str) -> list[DetectedEvent]:
        """video_path is the local original upload. Return events in any order."""
        ...
