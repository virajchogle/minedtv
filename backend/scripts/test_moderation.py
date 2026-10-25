"""Exercise the content moderator directly, with no pipeline/Docker/video needed.

    python -m scripts.test_moderation
    python -m scripts.test_moderation --text "say something custom here"
    python -m scripts.test_moderation --image path/to/screenshot.jpg
    python -m scripts.test_moderation --text "gg ez" --image path/to/screenshot.jpg

Needs GEMINI_API_KEY in backend/.env (or the environment). Without a key, every
case classifies as "none" by design — moderation fails open rather than
blocking uploads when no classifier is configured.

--image sends exactly that file as the one "sampled frame" for a single custom
case; it does not touch the built-in CASES, which are text-only (no sample
images ship with this script).
"""

import argparse
from pathlib import Path

from app.config import get_settings
from app.ml.moderation import ContentModerator

CASES = {
    "clean": "Nice shot, let's push mid and rotate on their jungler.",
    "trash_talk": "You're actually so bad at this game, uninstall, noob.",
    "profanity": "Holy shit that was such a clean headshot, fuck yes!",
    "crude_innuendo": "That's what she said, my guy, ez clap.",
    "severe_sexual": "Explicit description of a sex act goes here for testing purposes.",
    "threat": "I know where you live and I'm going to come hurt you tonight.",
    "empty": "",
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--text", default="", help="Classify one custom string instead of the built-in cases")
    p.add_argument("--image", help="Also send this local image file as a sampled frame")
    args = p.parse_args()

    settings = get_settings()
    moderator = ContentModerator(settings)

    if not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set — every case below will report severity=none (fail-open).\n")

    if args.text or args.image:
        frames = [Path(args.image).read_bytes()] if args.image else []
        result = moderator.classify(args.text, frames)
        label = "custom" + ("+image" if args.image else "")
        print(f"[{label}] severity={result.severity!r} categories={result.categories} reason={result.reason!r}")
        return

    for name, text in CASES.items():
        result = moderator.classify(text)
        print(f"[{name}] severity={result.severity!r} categories={result.categories} reason={result.reason!r}")


if __name__ == "__main__":
    main()
