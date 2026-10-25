"""Content moderation: transcript plus a sample of the video's own frames.

Runs once per session, in the pipeline, over the real Whisper transcript and
a handful of frames `step_frames` already extracted — not a second video
upload to Gemini. Judges both together (spoken content AND on-screen
text/imagery) into none / mild / severe:

  - mild   -> the clip is allowed to finish processing but is flagged
              age_restricted, and the owner sees a short warning.
  - severe -> `ContentPolicyViolation` is raised; the pipeline stops before
              `finalize`, so no clip is ever created for this session. That
              is the practical equivalent of "not allowed to upload": by the
              time a transcript exists the bytes are already in storage, so
              what can actually be prevented is the session ever becoming a
              public clip, not the upload itself.

The policy text below is server-only: it is never returned by any endpoint,
never logged in full, and nothing here echoes the transcript back to a
client. Only the generated verdict (severity, categories, one-line reason)
is ever exposed, through SessionOut/ClipOut.
"""

import base64
import logging
from functools import lru_cache
from typing import Literal

from google import genai
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.ml.gemini_creator import extract_json

log = logging.getLogger(__name__)

Severity = Literal["none", "mild", "severe"]

# Internal only. Not exposed through any schema or API response.
_POLICY = """You are a content moderator for short gameplay clips. You are given the
spoken TRANSCRIPT and a handful of frames sampled across the video. Judge both together
— spoken words AND anything on screen (HUD text, chat overlays, imagery).

SEVERE (always blocks publishing) — any of:
- Explicit sexual content: spoken, written on screen, or shown in a frame
- Any sexual content involving a minor, in any form (zero tolerance)
- A credible, specific threat of violence against a real, identifiable person
- Promotion or encouragement of self-harm or suicide
- Slurs, hate speech, or hate symbols — spoken, in on-screen text/chat, or shown in a frame — targeting a protected group (race, religion, gender, sexuality, disability, etc.)
- Real-world gore or graphic violence that is not ordinary game combat (e.g. real footage, gratuitous realistic mutilation)

MILD (warning + 18+ flag, upload still allowed) — any of:
- Profanity / swearing (e.g. "fuck", "shit", "bitch", "ass") — spoken or in on-screen text/chat — that doesn't rise to the above
- Crude sexual humor or innuendo, spoken or on screen, that stops short of explicit description
- Normal in-game violence/gore typical of an M-rated shooter or horror game (blood, combat, death animations) — this is expected gameplay content, not a real-world depiction

NONE — everything else, including competitive trash talk, mild insults ("idiot", "noob",
"trash"), ordinary gaming language, and normal gameplay footage (shooting, explosions,
HUD/chat text with no slurs or profanity). Default to NONE when in doubt; only escalate
on clear evidence actually present in the transcript or a frame. Ordinary game violence is
not severe or even mild just for being violent — games are violent by genre.

Return ONLY this JSON shape, no other text:
{"severity": "none"|"mild"|"severe", "categories": ["short tags, e.g. profanity, sexual_content, visual_gore, hate_symbol, on_screen_text"], "reason": "one factual sentence explaining the verdict, no quotes of the transcript"}
"""


class ModerationResult(BaseModel):
    # No Python-side defaults: Pydantic's generated JSON schema only marks a
    # field "required" when it has none, and Gemini's structured-output mode
    # only reliably fills fields the schema requires. With defaults here,
    # Gemini was correctly matching severity but silently omitting
    # categories/reason since the schema told it they were optional.
    severity: Severity
    categories: list[str]
    reason: str


class ContentPolicyViolation(RuntimeError):
    """Raised by the pipeline's moderate step to stop processing before finalize."""

    def __init__(self, reason: str, categories: list[str]):
        self.reason = reason or "Content violates community guidelines"
        self.categories = categories
        super().__init__(self.reason)


def _none() -> ModerationResult:
    return ModerationResult(severity="none", categories=[], reason="")


class ContentModerator:
    def __init__(self, settings: Settings):
        self.api_key = settings.gemini_api_key
        self.model = settings.moderation_model

    def classify(self, transcript_text: str, frames: list[bytes] | None = None) -> ModerationResult:
        text = transcript_text.strip()
        frames = frames or []
        if not text and not frames:
            return _none()

        if not self.api_key:
            # No Gemini configured (local dev / stub env): fail open rather than
            # block every upload when there is no classifier available at all.
            log.warning("moderation skipped: GEMINI_API_KEY not configured")
            return _none()

        try:
            # Keep a strong local reference to the client for the duration of the
            # call — see the same note in audience_simulator.py.
            client = genai.Client(api_key=self.api_key)
            content: list[dict] = [
                {"type": "image", "data": base64.b64encode(frame).decode("ascii"), "mime_type": "image/jpeg"}
                for frame in frames
            ]
            content.append(
                {
                    "type": "text",
                    "text": f"TRANSCRIPT:\n{text[:8000] if text else '(no speech detected)'}",
                }
            )
            interaction = client.interactions.create(
                model=self.model,
                system_instruction=_POLICY,
                input=content,
                generation_config={"thinking_level": "minimal", "max_output_tokens": 300},
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": ModerationResult.model_json_schema(),
                },
            )
            return ModerationResult.model_validate(extract_json(interaction.output_text))
        except (ValidationError, ValueError, KeyError) as exc:
            log.warning("moderation returned an unusable response, failing open: %s", exc)
            return _none()
        except Exception:
            log.exception("moderation classification failed, failing open")
            return _none()


@lru_cache
def get_moderator() -> ContentModerator:
    return ContentModerator(get_settings())
