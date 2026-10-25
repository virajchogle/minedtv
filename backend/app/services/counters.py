"""View and like counters.

Increments land in Redis hashes (clip_id -> pending delta) and are flushed into
clips.view_count / clips.like_count periodically. Displayed counts are the DB value
plus whatever is still pending, so they're live even between flushes.

Each flush atomically RENAMEs the hash before reading it, so increments that arrive
mid-flush go into a fresh hash and nothing is counted twice across API instances.

Views are also counted per UTC day ("clip_id|YYYY-MM-DD" fields) into clip_daily_views,
which is what analytics charts read.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, date, datetime

from redis.exceptions import ResponseError
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import Clip, ClipDailyViews
from app.db.session import get_sessionmaker
from app.services.redis import get_redis

log = logging.getLogger(__name__)

VIEWS_KEY = "counters:views"
LIKES_KEY = "counters:likes"
DAILY_VIEWS_KEY = "counters:daily_views"
_COLUMNS = {VIEWS_KEY: Clip.view_count, LIKES_KEY: Clip.like_count}


def today() -> date:
    return datetime.now(UTC).date()


async def incr_view(clip_id: uuid.UUID, viewer: str | None = None, dedup_s: int = 1800) -> bool:
    """Count a view. With a viewer key, repeat views by that viewer within dedup_s count once.
    Returns whether it was counted."""
    r = get_redis()
    if viewer is not None:
        digest = hashlib.sha256(viewer.encode()).hexdigest()[:24]
        if not await r.set(f"viewed:{clip_id}:{digest}", 1, nx=True, ex=dedup_s):
            return False
    pipe = r.pipeline(transaction=False)
    pipe.hincrby(VIEWS_KEY, str(clip_id), 1)
    pipe.hincrby(DAILY_VIEWS_KEY, f"{clip_id}|{today().isoformat()}", 1)
    await pipe.execute()
    return True


async def pending_daily_views(clip_ids: set[uuid.UUID]) -> dict[tuple[uuid.UUID, date], int]:
    """Daily views not flushed yet, for these clips. Missing Redis degrades to none."""
    try:
        raw = await get_redis().hgetall(DAILY_VIEWS_KEY)
    except Exception:  # noqa: BLE001 - counts are best-effort
        log.warning("redis unavailable for pending daily views", exc_info=True)
        return {}
    out: dict[tuple[uuid.UUID, date], int] = {}
    for field, value in raw.items():
        clip_id, _, day = field.partition("|")
        cid = uuid.UUID(clip_id)
        if cid in clip_ids:
            out[(cid, date.fromisoformat(day))] = int(value)
    return out


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
    updated += await _flush_daily(r)
    if updated:
        log.info("flushed counters", extra={"rows": updated})
    return updated


async def _flush_daily(r) -> int:
    tmp = f"{DAILY_VIEWS_KEY}:flushing:{uuid.uuid4().hex}"
    try:
        await r.rename(DAILY_VIEWS_KEY, tmp)
    except ResponseError:
        return 0
    deltas = {k: int(v) for k, v in (await r.hgetall(tmp)).items() if int(v) != 0}
    try:
        async with get_sessionmaker()() as db:
            for field, delta in deltas.items():
                clip_id, _, day = field.partition("|")
                stmt = pg_insert(ClipDailyViews).values(clip_id=uuid.UUID(clip_id), day=date.fromisoformat(day), views=delta)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[ClipDailyViews.clip_id, ClipDailyViews.day],
                    set_={"views": ClipDailyViews.views + delta},
                )
                # A clip deleted since the view was counted has nothing to attach the row to.
                try:
                    async with db.begin_nested():
                        await db.execute(stmt)
                except IntegrityError:
                    log.info("skipping daily views for a missing clip", extra={"clip_id": clip_id})
            await db.commit()
        await r.delete(tmp)
        return len(deltas)
    except Exception:
        pipe = r.pipeline(transaction=False)
        for field, delta in deltas.items():
            pipe.hincrby(DAILY_VIEWS_KEY, field, delta)
        pipe.delete(tmp)
        await pipe.execute()
        raise


async def flush_loop(interval_s: int) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            await flush()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.warning("counter flush failed", exc_info=True)
