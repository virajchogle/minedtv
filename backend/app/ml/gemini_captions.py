"""Focused Gemini caption extraction for short, already-selected clips."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from google import genai
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.ml.gemini_creator import CreatorAnalysisError, CreatorConfigurationError, extract_json
from app.ml.interfaces import TranscriptChunk


class CaptionCue(BaseModel):
    start_ms: int = Field(ge=0, description="Integer milliseconds from audio start; 1.25 seconds is 1250")
    end_ms: int = Field(gt=0, description="Integer milliseconds from audio start; 3 seconds is 3000")
    text: str = Field(min_length=1, max_length=160)


class CaptionResult(BaseModel):
    cues: list[CaptionCue]


CAPTION_PROMPT = """
Listen carefully to this short audio clip and return complete timed captions as JSON. Transcribe every word
that is clearly audible; never guess unclear dialogue or song lyrics. Also caption distinct, meaningful sounds
with concise accessibility cues such as [Zombie growls], [Gunfire], [Door creaks], [Laughter], or [Music].
Use integer MILLISECONDS relative to the beginning of this audio (for example, 1.25 seconds must be 1250,
not 1). Keep each cue short enough to read on a phone,
do not overlap cues, and do not omit non-speech audio merely because there is no dialogue. Return an empty
cues list only when the audio is silent.
"""


class GeminiCaptionEngine:
    """Generate transcript/accessibility cues without running the full creator-pack prompt."""

    def __init__(self, settings: Settings):
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self.inline_limit_bytes = settings.creator_inline_limit_mb * 1024 * 1024
        self.request_timeout_s = settings.creator_request_timeout_s

    def transcribe_audio(self, audio_path: str | Path, duration_ms: int | None = None) -> list[TranscriptChunk]:
        if not self.api_key:
            raise CreatorConfigurationError("GEMINI_API_KEY is not configured")

        path = Path(audio_path)
        client = genai.Client(api_key=self.api_key)
        uploaded = None
        try:
            if path.stat().st_size <= self.inline_limit_bytes:
                media_input = {
                    "type": "audio",
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                    "mime_type": "audio/opus",
                }
            else:
                uploaded = client.files.upload(file=str(path))
                deadline = time.monotonic() + 600
                while uploaded.state and uploaded.state.name == "PROCESSING":
                    if time.monotonic() > deadline:
                        raise TimeoutError("Gemini took too long to process the caption audio")
                    time.sleep(3)
                    uploaded = client.files.get(name=uploaded.name)
                if not uploaded.state or uploaded.state.name != "ACTIVE":
                    state = uploaded.state.name if uploaded.state else "UNKNOWN"
                    raise CreatorAnalysisError(f"Gemini caption audio processing failed with state {state}")
                media_input = {
                    "type": "audio",
                    "uri": uploaded.uri,
                    "mime_type": uploaded.mime_type,
                }

            interaction = client.interactions.create(
                model=self.model,
                input=[media_input, {"type": "text", "text": CAPTION_PROMPT}],
                generation_config={"thinking_level": "minimal", "max_output_tokens": 2048},
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": CaptionResult.model_json_schema(),
                },
                timeout=self.request_timeout_s,
            )
            result = CaptionResult.model_validate(extract_json(interaction.output_text))
            cues = [
                TranscriptChunk(start_ms=cue.start_ms, end_ms=cue.end_ms, text=cue.text)
                for cue in result.cues
                if cue.end_ms > cue.start_ms
            ]
            # Gemini occasionally labels integer seconds as *_ms despite explicit
            # instructions. Detect that response shape using the known clip duration
            # so captions do not all collapse into the first few milliseconds.
            if cues and duration_ms and duration_ms >= 10_000:
                largest_end = max(cue.end_ms for cue in cues)
                duration_s = duration_ms / 1000
                if largest_end <= duration_s + 2:
                    cues = [
                        TranscriptChunk(
                            start_ms=cue.start_ms * 1000,
                            end_ms=cue.end_ms * 1000,
                            text=cue.text,
                            speaker=cue.speaker,
                        )
                        for cue in cues
                    ]
            return cues
        except CreatorAnalysisError:
            raise
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise CreatorAnalysisError("Gemini returned invalid caption cues") from exc
        finally:
            if uploaded and getattr(uploaded, "name", None):
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:
                    pass
