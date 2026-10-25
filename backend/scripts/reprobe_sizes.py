"""Re-read every upload's display size, now that probing applies the phone rotation flag.

Uploads processed before that fix stored portrait phone videos as landscape (e.g. 1920x1080 instead
of 1080x1920), so they never count as shorts. This re-probes each source file and fixes the
session's width/height. The HLS renditions don't need redoing: ffmpeg rotated them correctly.

    python -m scripts.reprobe_sizes            # show what would change
    python -m scripts.reprobe_sizes --apply    # write it
"""

import argparse
import asyncio

from sqlalchemy import select

from app.db.models import Session, SessionStatus
from app.db.session import get_sessionmaker
from app.services.storage import get_storage
from app.worker import media


async def main(apply: bool) -> None:
    storage = get_storage()
    async with get_sessionmaker()() as db:
        sessions = (await db.scalars(select(Session).where(Session.status == SessionStatus.READY))).all()
        changed = 0
        for s in sessions:
            try:
                info = await asyncio.to_thread(media.probe, storage.url_for(s.source_key))
            except Exception as e:  # noqa: BLE001 - report and keep going
                print(f"skip {s.id} ({s.title}): {e}")
                continue
            if (info.width, info.height) != (s.width, s.height):
                changed += 1
                print(f"{s.id} {s.title!r}: {s.width}x{s.height} -> {info.width}x{info.height}")
                s.width, s.height = info.width, info.height
        if apply:
            await db.commit()
        print(f"{changed} of {len(sessions)} uploads {'fixed' if apply else 'would change (pass --apply)'}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    asyncio.run(main(p.parse_args().apply))
