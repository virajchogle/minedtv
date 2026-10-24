"""Protocol implementations that call the deployed Modal app (modal_app.py).

Needs Modal credentials: `modal setup` locally, or MODAL_TOKEN_ID / MODAL_TOKEN_SECRET
env vars on Cloud Run.
"""

from pathlib import Path

from app.config import get_settings
from app.ml.interfaces import TranscriptChunk

# Keep each remote call's payload modest (frames are small JPEGs, ~10-20 KB each).
_IMAGE_BATCH = 64
_TEXT_BATCH = 256


def _remote(cls_name: str):
    import modal

    return modal.Cls.from_name(get_settings().modal_app_name, cls_name)()


class ModalEmbedder:
    def __init__(self):
        self._remote = _remote("Embedder")
        self.dim = get_settings().embedding_dim

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(images), _IMAGE_BATCH):
            out += self._remote.embed_images.remote(images[i : i + _IMAGE_BATCH])
        return out

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), _TEXT_BATCH):
            out += self._remote.embed_texts.remote(texts[i : i + _TEXT_BATCH])
        return out


class ModalTranscriber:
    def __init__(self):
        self._remote = _remote("Transcriber")

    def transcribe(self, audio_path: str) -> list[TranscriptChunk]:
        path = Path(audio_path)
        chunks = self._remote.transcribe.remote(path.read_bytes(), path.suffix)
        return [TranscriptChunk(**c) for c in chunks]
