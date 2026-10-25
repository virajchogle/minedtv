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

The built-in cases carry [Xs] timestamp markers, same as the real pipeline
builds (see worker/pipeline.py:step_moderate), so this also exercises whether
the model correctly cites a timestamp per violation.
"""

import argparse
from pathlib import Path

from app.config import get_settings
from app.ml.moderation import ContentModerator

CASES = {
    "clean": "[0.0s] Nice shot, let's push mid. [4.2s] rotate on their jungler.",
    "trash_talk": "[0.0s] You're actually so bad at this game. [3.1s] uninstall, noob.",
    "profanity": "[0.0s] Just farming lanes. [12.3s] Holy shit that was such a clean headshot, fuck yes!",
    "crude_innuendo": "[0.0s] gg. [5.0s] That's what she said, my guy, ez clap.",
    "severe_sexual": "[0.0s] Normal chat. [8.7s] Explicit description of a sex act goes here for testing purposes.",
    "threat": "[0.0s] gg wp. [20.0s] I know where you live and I'm going to come hurt you tonight.",
    "empty": "",
}


def _print(label: str, result) -> None:
    print(f"[{label}] severity={result.severity!r} categories={result.categories} reason={result.reason!r}")
    for v in result.violations:
        t = f"{v.timestamp_ms / 1000:.1f}s" if v.timestamp_ms is not None else "no specific moment"
        print(f"    - at {t}: {v.category} — {v.note}")


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
        frames = [(0, Path(args.image).read_bytes())] if args.image else []
        result = moderator.classify(args.text, frames)
        _print("custom" + ("+image" if args.image else ""), result)
        return

    for name, text in CASES.items():
        _print(name, moderator.classify(text))


if __name__ == "__main__":
    main()
