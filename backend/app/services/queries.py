import uuid

from sqlalchemy import func, select

from app.db.models import Frame


async def nearest_frame_key(db, session_id: uuid.UUID, t_ms: int) -> str | None:
    """Thumbnail of the sampled frame closest to t_ms."""
    return await db.scalar(
        select(Frame.thumbnail_key)
        .where(Frame.session_id == session_id, Frame.thumbnail_key.is_not(None))
        .order_by(func.abs(Frame.t_ms - t_ms))
        .limit(1)
    )
