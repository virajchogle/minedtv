"""Virality check for an unpublished clip: Nihal's synthetic audience panel run on the clip's
creator pack. Results are keyed by clip range + options, so re-running with the same settings
is instant and trimming the clip produces a fresh result.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Callable

from app.config import Settings
from app.db.models import UNPUBLISHED_STATES, Clip, NotificationType
from app.schemas import CreatorPackOut
from app.services.social import notify
from app.worker.creator_pack import build_creator_pack
from app.worker.export import STATUS_TTL_S
from app.worker.pipeline import Deps

log = logging.getLogger("virality")


class ClipAlreadyPublished(RuntimeError):
    pass


def _options_hash(platform: str, target_audience: str | None, persona_count: int | None) -> str:
    raw = json.dumps([platform, (target_audience or "").strip().lower(), persona_count])
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def virality_key(clip_id, start_ms: int, end_ms: int, platform: str, target_audience: str | None, persona_count: int | None) -> str:
    return f"virality/{clip_id}/{start_ms}-{end_ms}-{_options_hash(platform, target_audience, persona_count)}.json"


def virality_status_key(clip_id, start_ms: int, end_ms: int, platform: str, target_audience: str | None, persona_count: int | None) -> str:
    return f"virality:{clip_id}:{start_ms}-{end_ms}:{_options_hash(platform, target_audience, persona_count)}"


async def run_virality(
    clip_id: uuid.UUID | str,
    deps: Deps,
    platform: str = "general",
    target_audience: str | None = None,
    persona_count: int | None = None,
    redis=None,
    simulator_factory: Callable[[Settings], object] | None = None,
    engine_factory: Callable[[Settings], object] | None = None,
) -> str:
    """Simulate audience reactions for an unpublished clip. Returns the result's storage key."""
    clip_id = uuid.UUID(str(clip_id))
    async with deps.sessionmaker() as db:
        clip = await db.get(Clip, clip_id)
        if clip is None:
            raise LookupError(f"clip {clip_id} not found")
        start, end, state, owner_id = clip.start_ms, clip.end_ms, clip.publish_state, clip.user_id
    args = (clip_id, start, end, platform, target_audience, persona_count)
    key, skey = virality_key(*args), virality_status_key(*args)

    async def set_status(value: str):
        if redis is not None:
            await redis.set(skey, value, ex=STATUS_TTL_S)

    if state not in UNPUBLISHED_STATES:
        await set_status("failed:clip is already published")
        raise ClipAlreadyPublished(f"clip {clip_id} is {state}")
    if await asyncio.to_thread(deps.storage.exists, key):
        await set_status("ready")
        return key

    await set_status("processing")
    try:
        pack_key = await build_creator_pack(clip_id, deps, redis, engine_factory)
        body = json.loads(await asyncio.to_thread(deps.storage.get_bytes, pack_key))
        analysis = CreatorPackOut.model_validate(body["pack"])
        if simulator_factory is None:
            from app.ml.audience_simulator import GeminiAudienceSimulator

            simulator_factory = GeminiAudienceSimulator
        simulator = simulator_factory(deps.settings)
        count = persona_count or deps.settings.creator_persona_count
        result = await asyncio.to_thread(simulator.simulate, analysis, platform, target_audience, count)
        await asyncio.to_thread(
            deps.storage.put_bytes, key, result.model_dump_json().encode(), "application/json"
        )
        await set_status("ready")
        try:
            async with deps.sessionmaker() as db:
                await notify(
                    db,
                    user_id=owner_id,
                    type=NotificationType.VIRALITY_READY,
                    clip_id=clip_id,
                    data={
                        "platform": platform,
                        "virality_score": getattr(result, "virality_score", None),
                        "verdict": getattr(result, "verdict", None),
                    },
                )
                await db.commit()
        except Exception:  # noqa: BLE001 - the result is saved; a missed notification isn't a failure
            log.warning("could not record virality notification", exc_info=True)
        log.info("virality ready", extra={"clip_id": str(clip_id), "score": getattr(result, "virality_score", None)})
        return key
    except Exception as e:
        await set_status(f"failed:{type(e).__name__}: {e}"[:500])
        raise
