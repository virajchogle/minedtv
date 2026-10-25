"""A clip's virality from the frame scorer's per-frame scores (see services/frame_virality.py).

The upload is scored once (automatically after processing); any clip of it then gets its score
from the frames inside its time range, with no extra model calls.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clip, FrameHighlightRun, FrameViralityScore
from app.schemas import ClipViralityOut, ViralityComponentsOut, ViralityPointOut, ViralitySummaryOut

TOP_FRAMES = 3
# Same cut-offs the old persona panel used, on the 0–100 scale.
CUTOFFS = ((75, "strong"), (55, "promising"), (35, "mixed"))


def verdict_for(score: float) -> str:
    return next((name for cut, name in CUTOFFS if score >= cut), "weak")


async def clip_virality(db: AsyncSession, clip: Clip) -> ClipViralityOut:
    base = dict(clip_id=clip.id, start_ms=clip.start_ms, end_ms=clip.end_ms)
    rows = (
        await db.scalars(
            select(FrameViralityScore)
            .where(
                FrameViralityScore.session_id == clip.session_id,
                FrameViralityScore.t_ms >= clip.start_ms,
                FrameViralityScore.t_ms < clip.end_ms,
            )
            .order_by(FrameViralityScore.t_ms)
        )
    ).all()
    run = await db.get(FrameHighlightRun, clip.session_id)
    version = run.algorithm_version if run else None
    if not rows:
        if run is not None and run.status == "processing":
            return ClipViralityOut(**base, status="processing", algorithm_version=version)
        if run is not None and run.status == "failed":
            return ClipViralityOut(**base, status="failed", error=run.error, algorithm_version=version)
        return ClipViralityOut(**base, status="none", algorithm_version=version)

    top = sorted(rows, key=lambda r: -r.score)[:TOP_FRAMES]

    def avg(attr: str) -> float:
        return round(100 * sum(getattr(r, attr) for r in top) / len(top), 1)

    score = avg("score")
    return ClipViralityOut(
        **base,
        status="ready",
        score=score,
        verdict=verdict_for(score),
        peak_offset_ms=top[0].t_ms - clip.start_ms,
        components=ViralityComponentsOut(
            visual=avg("visual_score"),
            novelty=avg("novelty_score"),
            event=avg("event_score"),
            speech=avg("speech_score"),
            visibility=avg("visibility_score"),
            scene=avg("scene_score"),
        ),
        curve=[ViralityPointOut(offset_ms=r.t_ms - clip.start_ms, score=round(100 * r.score, 1)) for r in rows],
        algorithm_version=version,
    )


async def clip_virality_summary(db: AsyncSession, clip: Clip) -> ViralitySummaryOut:
    v = await clip_virality(db, clip)
    return ViralitySummaryOut(status=v.status, score=v.score, verdict=v.verdict)
