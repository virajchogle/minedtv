"""Rebuild the demo from a folder of videos with one command.

    python -m scripts.seed ./demo_videos --reset

Layout: subfolders name the game, e.g.

    demo_videos/
      Valorant/ranked-bind.mp4
      Fortnite/last-circle.mov
      random-clip.mp4            # top-level files get --default-game

Videos are dealt round-robin to the demo users (created if missing), uploaded to the
configured storage, and run through the full pipeline in this process (or queued for
the worker with --queue). Uses whatever DATABASE_URL / storage / ML backends are configured.
"""

import argparse
import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db.models import Session, SessionStatus, User
from app.db.session import get_engine, get_sessionmaker
from app.log import setup_logging
from app.services.storage import get_storage

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".flv"}
DEMO_USERS = ["ShadowSniper", "NovaQueen", "xPixel"]
log = logging.getLogger("seed")


def find_videos(root: Path, default_game: str) -> list[tuple[Path, str]]:
    found = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in VIDEO_EXT and not p.name.startswith("."):
            game = p.parent.name if p.parent != root else default_game
            found.append((p, game))
    return found


def title_from(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").strip().capitalize()


async def reset() -> None:
    async with get_engine().begin() as conn:
        await conn.execute(text("TRUNCATE users, sessions, segments, clips, frames, transcripts, events, likes CASCADE"))
    removed = await asyncio.to_thread(get_storage().delete_prefix, "sessions/")
    try:
        from app.services.redis import get_redis

        r = get_redis()
        keys = [k async for k in r.scan_iter("search:*")] + [k async for k in r.scan_iter("counters:*")]
        if keys:
            await r.delete(*keys)
    except Exception:  # noqa: BLE001 - redis is optional for seeding
        log.warning("could not clear redis caches")
    log.info("reset database and storage", extra={"objects_removed": removed})


async def ensure_users(names: list[str]) -> list[User]:
    users = []
    async with get_sessionmaker()() as db:
        for name in names:
            user = await db.scalar(select(User).where(User.username == name))
            if user is None:
                user = User(username=name, avatar_url=f"https://api.dicebear.com/9.x/bottts/png?seed={name}")
                db.add(user)
            users.append(user)
        await db.commit()
    return users


async def create_session(path: Path, game: str, user: User) -> Session:
    async with get_sessionmaker()() as db:
        s = Session(
            user_id=user.id,
            game=game,
            title=title_from(path),
            started_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
            storage_prefix="",
            source_key="",
            status=SessionStatus.UPLOADING,
        )
        db.add(s)
        await db.flush()
        s.storage_prefix = f"sessions/{s.id}"
        s.source_key = f"{s.storage_prefix}/source{path.suffix.lower()}"
        await db.commit()
    t0 = time.monotonic()
    await asyncio.to_thread(get_storage().put_file, s.source_key, path, "video/mp4")
    log.info("uploaded", extra={"session_id": str(s.id), "file": path.name, "secs": round(time.monotonic() - t0, 1)})
    async with get_sessionmaker()() as db:
        row = await db.get(Session, s.id)
        row.status = SessionStatus.QUEUED
        await db.commit()
    return s


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--reset", action="store_true", help="wipe ALL sessions/clips/users and stored media first")
    parser.add_argument("--users", default=",".join(DEMO_USERS), help="comma-separated demo usernames")
    parser.add_argument("--default-game", default="Valorant", help="game for videos not in a game subfolder")
    parser.add_argument("--queue", action="store_true", help="enqueue for the worker instead of processing here")
    parser.add_argument("--jobs", type=int, default=1, help="videos to process in parallel (inline mode)")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level, json_logs=False)
    videos = find_videos(args.folder, args.default_game)
    if not videos:
        raise SystemExit(f"no videos found in {args.folder}")

    db_url = make_url(settings.database_url)
    log.info(
        "seeding",
        extra={"videos": len(videos), "db": f"{db_url.host}:{db_url.port}/{db_url.database}", "storage": settings.storage_backend,
               "embedder": settings.embedder_backend, "transcriber": settings.transcriber_backend},
    )
    if args.reset:
        await reset()

    users = await ensure_users([u.strip() for u in args.users.split(",") if u.strip()])
    sessions = [await create_session(path, game, users[i % len(users)]) for i, (path, game) in enumerate(videos)]

    if args.queue:
        from app.worker.enqueue import enqueue_pipeline

        for s in sessions:
            enqueue_pipeline(s.id)
        log.info("queued for the worker", extra={"sessions": len(sessions)})
        return

    from app.worker.pipeline import run_pipeline

    sem = asyncio.Semaphore(max(1, args.jobs))

    async def process(s: Session) -> str:
        async with sem:
            return await run_pipeline(s.id)

    t0 = time.monotonic()
    statuses = await asyncio.gather(*(process(s) for s in sessions))
    ok = statuses.count(SessionStatus.READY)
    log.info("done", extra={"ready": ok, "failed": len(statuses) - ok, "secs": round(time.monotonic() - t0, 1)})
    for s, st in zip(sessions, statuses, strict=True):
        print(f"  {st:6}  {s.id}  {s.game:12}  {s.title}")
    await get_engine().dispose()
    if ok < len(statuses):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
