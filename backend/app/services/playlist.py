"""HLS playlists built on the fly from a session's segments ("clips as views")."""

import math
from collections.abc import Callable, Sequence
from typing import Protocol


class SegmentLike(Protocol):
    idx: int
    start_ms: int
    duration_ms: int
    storage_key: str


def segments_in_range(segments: Sequence[SegmentLike], start_ms: int, end_ms: int) -> list[SegmentLike]:
    """Segments overlapping [start_ms, end_ms), in order."""
    return sorted(
        (s for s in segments if s.start_ms < end_ms and s.start_ms + s.duration_ms > start_ms),
        key=lambda s: s.idx,
    )


def build_playlist(
    segments: Sequence[SegmentLike],
    start_ms: int,
    end_ms: int,
    url_for: Callable[[str], str],
) -> str:
    """A VOD media playlist covering start_ms..end_ms.

    Playback is segment-granular (2 s), so the playlist starts at the segment containing
    start_ms. EXT-X-START tells players to begin at the exact start_ms within it.
    """
    chosen = segments_in_range(segments, start_ms, end_ms)
    if not chosen:
        raise ValueError(f"no segments cover {start_ms}..{end_ms}")
    target = max(math.ceil(s.duration_ms / 1000) for s in chosen)
    offset_s = max(0, start_ms - chosen[0].start_ms) / 1000
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:6",
        f"#EXT-X-TARGETDURATION:{target}",
        f"#EXT-X-MEDIA-SEQUENCE:{chosen[0].idx}",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-INDEPENDENT-SEGMENTS",
    ]
    if offset_s > 0:
        lines.append(f"#EXT-X-START:TIME-OFFSET={offset_s:.3f},PRECISE=YES")
    for s in chosen:
        lines.append(f"#EXTINF:{s.duration_ms / 1000:.3f},")
        lines.append(url_for(s.storage_key))
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


MIN_CLIP_MS = 1000


def validate_clip_range(start_ms: int, end_ms: int, session_duration_ms: int | None) -> None:
    """Raise ValueError if a clip range isn't valid for its session."""
    if session_duration_ms is None:
        raise ValueError("session has not been processed yet")
    if start_ms < 0:
        raise ValueError("start_ms must be >= 0")
    if end_ms <= start_ms:
        raise ValueError("end_ms must be greater than start_ms")
    if end_ms > session_duration_ms:
        raise ValueError(f"end_ms {end_ms} is past the end of the session ({session_duration_ms} ms)")
    if end_ms - start_ms < MIN_CLIP_MS:
        raise ValueError(f"clip must be at least {MIN_CLIP_MS} ms long")
