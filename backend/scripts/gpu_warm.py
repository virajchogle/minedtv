"""Keep the Modal GPU containers warm (no cold starts) for a demo, then turn it back off.

    python -m scripts.gpu_warm on        # 1 warm Embedder container (~$0.60/hour on a T4)
    python -m scripts.gpu_warm on --transcriber   # also keep Whisper warm
    python -m scripts.gpu_warm off       # back to scale-to-zero
    python -m scripts.gpu_warm status

Leaving it on for the whole hackathon would cost more than Modal's $30 monthly credit,
so switch it on shortly before the demo and off right after.
"""

import argparse

import modal

from app.config import get_settings


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["on", "off", "status"])
    p.add_argument("--transcriber", action="store_true", help="also apply to the Whisper transcriber")
    args = p.parse_args()

    app_name = get_settings().modal_app_name
    names = ["Embedder"] + (["Transcriber"] if args.transcriber or args.mode == "off" else [])
    for name in names:
        obj = modal.Cls.from_name(app_name, name)()
        if args.mode == "status":
            print(f"{name}: see https://modal.com/apps for live container counts")
            continue
        warm = 1 if args.mode == "on" else 0
        obj.update_autoscaler(min_containers=warm)
        print(f"{name}: min_containers={warm}")
    if args.mode == "on":
        # Trigger a container now rather than waiting for the autoscaler.
        modal.Cls.from_name(app_name, "Embedder")().embed_texts.remote(["warm up"])
        print("Embedder is warm")


if __name__ == "__main__":
    main()
