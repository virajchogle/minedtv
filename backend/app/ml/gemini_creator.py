"""Gemini video-to-content engine used by the creator API.

The engine is independent of FastAPI so workers, scripts, or other clients can
reuse it with a local file path. Small clips are sent inline; larger files use
Gemini's Files API and are deleted remotely after analysis.
"""

import base64
import json
import time
from pathlib import Path

from google import genai
from pydantic import ValidationError

from app.config import Settings
from app.schemas import CreatorPackOut


ANALYSIS_PROMPT = """
Watch and listen to this video, then create factual publishing metadata. Return ONLY valid JSON:
{
  "title_options": ["three compelling titles"],
  "description": "A detailed, literal description of what happens from beginning to end",
  "summary": "A direct 1-2 sentence summary that says what the video is about and what happens",
  "caption": "A natural social caption grounded in the video",
  "youtube": {
    "title": "SEO-friendly title under 100 characters",
    "description": "A ready-to-paste YouTube description",
    "tags": ["8-15 tags"],
    "chapters": [{"timestamp": "00:00", "label": "Chapter name"}]
  },
  "reddit": {
    "title": "Natural, non-clickbait Reddit title",
    "body": "A conversational Reddit post body",
    "suggested_subreddits": ["up to 5 relevant subreddit names without r/"]
  },
  "transcript": [{"timestamp": "00:00", "text": "spoken words or meaningful audio"}],
  "key_moments": [{"timestamp": "00:00", "label": "what happens and why it matters"}],
  "hashtags": ["8-15 hashtags without #"],
  "content_warnings": []
}
Avoid AI-sounding phrases, inflated claims, generic enthusiasm, and unnecessary adjectives. Never use phrases
such as "delve into", "game-changer", "unlock", "in today's fast-paced world", or "whether you're a".
Prefer concrete nouns and verbs. Do not invent speech, timestamps, people, brands, or events. If speech is
unclear, say so instead of guessing. The summary must be plain, specific, and shorter than the description.
"""


class CreatorConfigurationError(RuntimeError):
    """The creator engine is not configured on this deployment."""


class CreatorAnalysisError(RuntimeError):
    """Gemini could not return a usable content pack."""


def extract_json(text: str) -> dict:
    """Parse a JSON response, tolerating a single Markdown code fence."""
    if not isinstance(text, str):
        raise ValueError("Gemini response did not contain text")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:].lstrip()
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("Gemini response must be a JSON object")
    return value


class GeminiCreatorEngine:
    def __init__(self, settings: Settings):
        self.api_key = settings.gemini_api_key
        self.model = settings.gemini_model
        self.inline_limit_bytes = settings.creator_inline_limit_mb * 1024 * 1024
        self.frame_sample_fps = settings.creator_frame_sample_fps
        self.request_timeout_s = settings.creator_request_timeout_s

    def analyze(self, video_path: str | Path, mime_type: str) -> CreatorPackOut:
        if not self.api_key:
            raise CreatorConfigurationError("GEMINI_API_KEY is not configured")

        path = Path(video_path)
        client = genai.Client(api_key=self.api_key)
        uploaded = None

        try:
            if path.stat().st_size <= self.inline_limit_bytes:
                media_input = {
                    "type": "video",
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                    "mime_type": mime_type,
                    "processing": {"type": "static", "fps": self.frame_sample_fps},
                }
            else:
                uploaded = client.files.upload(file=str(path))
                deadline = time.monotonic() + 600
                while uploaded.state and uploaded.state.name == "PROCESSING":
                    if time.monotonic() > deadline:
                        raise TimeoutError("Gemini took too long to process the video")
                    time.sleep(3)
                    uploaded = client.files.get(name=uploaded.name)

                if not uploaded.state or uploaded.state.name != "ACTIVE":
                    state = uploaded.state.name if uploaded.state else "UNKNOWN"
                    raise CreatorAnalysisError(f"Gemini file processing failed with state {state}")

                media_input = {
                    "type": "video",
                    "uri": uploaded.uri,
                    "mime_type": uploaded.mime_type,
                    "processing": {"type": "static", "fps": self.frame_sample_fps},
                }

            interaction = client.interactions.create(
                model=self.model,
                input=[media_input, {"type": "text", "text": ANALYSIS_PROMPT}],
                generation_config={
                    "thinking_level": "minimal",
                    "max_output_tokens": 8192,
                },
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": CreatorPackOut.model_json_schema(),
                },
                timeout=self.request_timeout_s,
            )
            return CreatorPackOut.model_validate(extract_json(interaction.output_text))
        except CreatorAnalysisError:
            raise
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise CreatorAnalysisError("Gemini returned an invalid content pack") from exc
        finally:
            if uploaded and getattr(uploaded, "name", None):
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:  # Best-effort remote cleanup must not hide the analysis result.
                    pass
