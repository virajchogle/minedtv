"""Transcript content moderation.

Runs once per session, in the pipeline, over the real Whisper transcript —
not a second video upload to Gemini. Classifies spoken content into
none / mild / severe:

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

import logging
from functools import lru_cache
from typing import Literal

from google import genai
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.ml.gemini_creator import extract_json

log = logging.getLogger(__name__)

Severity = Literal["none", "mild", "severe"]

# Internal only. Not exposed through any schema or API response.
_POLICY = """You are a content moderator for short gameplay clips. Classify the TRANSCRIPT below.

SEVERE (always blocks publishing) — any of:
- Explicit sexual content, descriptions of sex acts, or sexual solicitation
- Any sexual content involving a minor, in any form (zero tolerance)
- A credible, specific threat of violence against a real, identifiable person
- Promotion or encouragement of self-harm or suicide
- Slurs or hate speech targeting a protected group (race, religion, gender, sexuality, disability, etc.)

MILD (warning + 18+ flag, upload still allowed) — any of:
- Profanity / swearing (e.g. "fuck", "shit", "bitch", "ass") that doesn't rise to the above
- Crude sexual humor or innuendo that stops short of explicit description
- Graphic description of violence typical of normal gameplay commentary

NONE — everything else, including competitive trash talk, mild insults ("idiot", "noob",
"trash"), and ordinary gaming language. Default to NONE when in doubt; only escalate on
clear evidence in the text itself.

Judge only the words actually present in the transcript. Do not infer intent beyond what
is written, and do not flag a word just because it is loud or excited.

Return ONLY this JSON shape, no other text:
{"severity": "none"|"mild"|"severe", "categories": ["short tags, e.g. profanity, sexual_content"], "reason": "one factual sentence explaining the verdict, no quotes of the transcript"}
"""


class ModerationResult(BaseModel):
    severity: Severity = "none"
    categories: list[str] = Field(default_factory=list)
    reason: str = ""


class ContentPolicyViolation(RuntimeError):
    """Raised by the pipeline's moderate step to stop processing before finalize."""

    def __init__(self, reason: str, categories: list[str]):
        self.reason = reason or "Content violates community guidelines"
        self.categories = categories
        super().__init__(self.reason)


class TranscriptModerator:
    def __init__(self, settings: Settings):
        self.api_key = settings.gemini_api_key
        self.model = settings.moderation_model

    def classify(self, transcript_text: str) -> ModerationResult:
        text = transcript_text.strip()
        if not text:
            return ModerationResult(severity="none")

        if not self.api_key:
            # No Gemini configured (local dev / stub env): fail open rather than
            # block every upload when there is no classifier available at all.
            log.warning("moderation skipped: GEMINI_API_KEY not configured")
            return ModerationResult(severity="none")

        try:
            # Keep a strong local reference to the client for the duration of the
            # call — see the same note in audience_simulator.py.
            client = genai.Client(api_key=self.api_key)
            interaction = client.interactions.create(
                model=self.model,
                system_instruction=_POLICY,
                input=f"TRANSCRIPT:\n{text[:8000]}",
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
            return ModerationResult(severity="none")
        except Exception:
            log.exception("moderation classification failed, failing open")
            return ModerationResult(severity="none")


@lru_cache
def get_moderator() -> TranscriptModerator:
    return TranscriptModerator(get_settings())
