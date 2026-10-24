"""Stand-ins so the pipeline runs end to end before the real models exist."""

import hashlib
import math
import random

from app.config import get_settings
from app.ml.interfaces import DetectedEvent, TranscriptChunk


def _hash_vector(data: bytes, dim: int) -> list[float]:
    # Deterministic per input (so identical text/images map to identical vectors) and
    # unit-length (zero vectors make cosine distance NaN in pgvector).
    rng = random.Random(hashlib.sha256(data).digest())
    v = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class StubEmbedder:
    def __init__(self, dim: int | None = None):
        self.dim = dim or get_settings().embedding_dim

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        return [_hash_vector(b"img:" + img, self.dim) for img in images]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_hash_vector(b"txt:" + t.strip().lower().encode(), self.dim) for t in texts]


class StubTranscriber:
    def transcribe(self, audio_path: str) -> list[TranscriptChunk]:
        return []


class StubHighlightDetector:
    def detect(self, video_path: str, session_id: str) -> list[DetectedEvent]:
        return []
