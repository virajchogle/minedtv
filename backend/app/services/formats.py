"""Short (vertical, reel-length) vs long clips: one rule, used in Python and in SQL.

short = the video is taller than it is wide and the clip is at most `short_max_duration_s` long.
Width and height are the display size (rotation applied), stored on the session at probe time.
"""

from typing import Literal

from sqlalchemy import ColumnElement, and_, not_

from app.config import get_settings
from app.db.models import Clip, Session

ClipFormat = Literal["short", "long"]


def clip_format(width: int | None, height: int | None, duration_ms: int) -> ClipFormat:
    vertical = bool(width and height and height > width)
    return "short" if vertical and duration_ms <= get_settings().short_max_duration_s * 1000 else "long"


def is_short() -> ColumnElement[bool]:
    """SQL twin of clip_format() == "short", over a query that joins Clip and Session."""
    return and_(
        Session.width.is_not(None),
        Session.height > Session.width,
        (Clip.end_ms - Clip.start_ms) <= get_settings().short_max_duration_s * 1000,
    )


def format_filter(fmt: ClipFormat | None) -> ColumnElement[bool] | None:
    if fmt is None:
        return None
    return is_short() if fmt == "short" else not_(is_short())
