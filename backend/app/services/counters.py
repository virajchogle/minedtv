"""View and like counters.

Increments land in Redis hashes (clip_id -> pending delta) and are flushed into
clips.view_count / clips.like_count periodically. Displayed counts are the DB value
plus whatever is still pending, so they're live even between flushes.

Each flush atomically RENAMEs the hash before reading it, so increments that arrive
mid-flush go into a fresh hash and nothing is counted twice across API instances.
"""

import asyncio
import logging
import uuid

from redis.exceptions import ResponseError
from sqlalchemy import update

from app.db.models import Clip
from app.db.session import get_sessionmaker
from app.services.redis import get_redis

log = logging.getLogger(__name__)

VIEWS_KEY = "counters:views"
LIKES_KEY = "counters:likes"
_COLUMNS = {VIEWS_KEY: Clip.view_count, LIKES_KEY: Clip.like_count}


async def incr_view(clip_id: uuid.UUID) -> None:
    await get_redis().hincrby(VIEWS_KEY, str(clip_id), 1)


async def incr_like(clip_id: uuid.UUID, delta: int) -> None:
    await get_redis().hincrby(LIKES_KEY, str(clip_id), delta)


async def pending(clip_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """(pending_views, pending_likes) per clip. Missing Redis degrades to zeros."""
    if not clip_ids:
        return {}
    fields = [str(c) for c in clip_ids]
    try:
        pipe = get_redis().pipeline(transaction=False)
        pipe.hmget(VIEWS_KEY, fields)
        pipe.hmget(LIKES_KEY, fields)
        views, likes = await pipe.execute()
    except Exception:  # noqa: BLE001 - counts are best-effort
        log.warning("redis unavailable for pending counters", exc_info=True)
        return {c: (0, 0) for c in clip_ids}
    return {c: (int(v or 0), int(l or 0)) for c, v, l in zip(clip_ids, views, likes, strict=True)}


async def flush() -> int:
    """Move pending deltas into Postgres. Returns the number of clip rows updated."""
    r = get_redis()
    updated = 0
    for key, column in _COLUMNS.items():
        tmp = f"{key}:flushing:{uuid.uuid4().hex}"
        try:
            await r.rename(key, tmp)
        except ResponseError:  # key doesn't exist: nothing pending
            continue
        deltas = {k: int(v) for k, v in (await r.hgetall(tmp)).items() if int(v) != 0}
        try:
            async with get_sessionmaker()() as db:
                for clip_id, delta in deltas.items():
                    await db.execute(update(Clip).where(Clip.id == uuid.UUID(clip_id)).values({column: column + delta}))
                await db.commit()
            updated += len(deltas)
            await r.delete(tmp)
        except Exception:
            # Put the deltas back so they're retried next flush.
            pipe = r.pipeline(transaction=False)
            for clip_id, delta in deltas.items():
                pipe.hincrby(key, clip_id, delta)
            pipe.delete(tmp)
            await pipe.execute()
            raise
    if updated:
        log.info("flushed counters", extra={"clips": updated})
    return updated


async def flush_loop(interval_s: int) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            await flush()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.warning("counter flush failed", exc_info=True)
