"""GPU inference on Modal: CLIP embeddings and Whisper transcription on a T4.

    modal deploy modal_app.py          # deploy (re-run after changing models)
    modal run modal_app.py             # smoke test: embeds a string, prints the dim

Then set EMBEDDER_BACKEND=modal and/or TRANSCRIBER_BACKEND=modal; the adapter in
app/ml/modal_adapter.py calls these by name. Containers scale to zero after
SCALEDOWN_S idle seconds, so the first call after a quiet period cold-starts (~30-60 s).
"""

import os
import tempfile

import modal

APP_NAME = os.environ.get("MODAL_APP_NAME", "minedtv-ml")
SCALEDOWN_S = 300

image = (
    # cuDNN from the base image is what faster-whisper (CTranslate2) needs on GPU.
    modal.Image.from_registry("nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04", add_python="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "torch==2.5.1",
        "transformers==4.46.3",
        "pillow==11.0.0",
        "faster-whisper==1.1.0",
        "numpy<2.2",
    )
    .env({"HF_HOME": "/cache/hf"})
    .add_local_python_source("app")
)

app = modal.App(APP_NAME, image=image)
cache = modal.Volume.from_name("minedtv-model-cache", create_if_missing=True)


@app.cls(gpu="T4", volumes={"/cache": cache}, scaledown_window=SCALEDOWN_S, timeout=600)
class Embedder:
    @modal.enter()
    def load(self):
        from app.ml.models import ClipEmbedder

        self.model = ClipEmbedder(device="cuda")
        cache.commit()

    @modal.method()
    def dim(self) -> int:
        return self.model.dim

    @modal.method()
    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        return self.model.embed_images(images)

    @modal.method()
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.model.embed_texts(texts)


@app.cls(gpu="T4", volumes={"/cache": cache}, scaledown_window=SCALEDOWN_S, timeout=1800)
class Transcriber:
    @modal.enter()
    def load(self):
        from app.ml.models import WhisperTranscriber

        self.model = WhisperTranscriber(device="cuda")
        cache.commit()

    @modal.method()
    def transcribe(self, audio: bytes, suffix: str = ".ogg") -> list[dict]:
        """Takes the audio file's bytes (the worker's disk isn't visible here)."""
        with tempfile.NamedTemporaryFile(suffix=suffix) as f:
            f.write(audio)
            f.flush()
            chunks = self.model.transcribe(f.name)
        return [{"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text, "speaker": c.speaker} for c in chunks]


@app.local_entrypoint()
def smoke_test():
    vecs = Embedder().embed_texts.remote(["a clutch 1v3 on Bind"])
    print(f"embedder ok: dim={len(vecs[0])}")
