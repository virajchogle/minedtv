"""Real model implementations (CLIP + faster-whisper).

Used inside the Modal GPU containers (modal_app.py), and directly for local CPU dev:

    pip install -r requirements-ml.txt
    EMBEDDER_BACKEND=app.ml.models:ClipEmbedder
    TRANSCRIBER_BACKEND=app.ml.models:WhisperTranscriber

Only imports torch/transformers/faster_whisper, never app.config, so the Modal image
doesn't need the API's dependencies.
"""

import io
import os

from app.ml.interfaces import TranscriptChunk

# ViT-L/14 -> 768-dim vectors, matching the default EMBEDDING_DIM.
# (PixelPull's ViT-B/32 is 512-dim; switching needs EMBEDDING_DIM=512 and a fresh migration.)
CLIP_MODEL = os.environ.get("CLIP_MODEL", "openai/clip-vit-large-patch14")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3-turbo")


def _device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


class ClipEmbedder:
    def __init__(self, model_name: str = CLIP_MODEL, device: str | None = None):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        self.device = device or _device()
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.model = CLIPModel.from_pretrained(model_name, torch_dtype=dtype).to(self.device).eval()
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.dim = self.model.config.projection_dim

    def _normalize(self, feats) -> list[list[float]]:
        feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.float().cpu().tolist()

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        import torch
        from PIL import Image

        if not images:
            return []
        pil = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
        inputs = self.processor(images=pil, return_tensors="pt").to(self.device)
        with torch.no_grad():
            feats = self.model.get_image_features(pixel_values=inputs["pixel_values"].to(self.model.dtype))
        return self._normalize(feats)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import torch

        if not texts:
            return []
        # CLIP's text encoder caps at 77 tokens; longer transcript windows are truncated.
        inputs = self.processor(text=texts, return_tensors="pt", padding=True, truncation=True, max_length=77).to(self.device)
        with torch.no_grad():
            feats = self.model.get_text_features(input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"])
        return self._normalize(feats)


class WhisperTranscriber:
    def __init__(self, model_name: str = WHISPER_MODEL, device: str | None = None):
        from faster_whisper import WhisperModel

        device = device or _device()
        compute = "float16" if device == "cuda" else "int8"
        self.model = WhisperModel(model_name, device=device, compute_type=compute)

    def transcribe(self, audio_path: str) -> list[TranscriptChunk]:
        # VAD skips the long silences in gameplay audio, which also stops Whisper hallucinating text there.
        segments, _info = self.model.transcribe(audio_path, vad_filter=True, beam_size=5)
        return [
            TranscriptChunk(start_ms=int(s.start * 1000), end_ms=int(s.end * 1000), text=s.text.strip())
            for s in segments
            if s.text.strip()
        ]
