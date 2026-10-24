from dataclasses import dataclass

import pytest

from app.services.playlist import build_playlist, segments_in_range, validate_clip_range


@dataclass
class Seg:
    idx: int
    start_ms: int
    duration_ms: int
    storage_key: str


def make_segments(n: int, dur: int = 2000, last: int | None = None) -> list[Seg]:
    segs = [Seg(i, i * dur, dur, f"s/hls/seg_{i:05d}.ts") for i in range(n)]
    if last is not None:
        segs[-1].duration_ms = last
    return segs


def url(key: str) -> str:
    return f"https://cdn.example/{key}"


def test_range_selects_overlapping_segments():
    segs = make_segments(10)
    chosen = segments_in_range(segs, 4500, 9000)
    assert [s.idx for s in chosen] == [2, 3, 4]


def test_range_on_exact_boundaries_excludes_neighbours():
    segs = make_segments(10)
    assert [s.idx for s in segments_in_range(segs, 4000, 8000)] == [2, 3]


def test_playlist_contents():
    segs = make_segments(10, last=1500)
    body = build_playlist(segs, 4500, 9000, url)
    lines = body.splitlines()
    assert lines[0] == "#EXTM3U"
    assert "#EXT-X-MEDIA-SEQUENCE:2" in lines
    assert "#EXT-X-TARGETDURATION:2" in lines
    assert "#EXT-X-START:TIME-OFFSET=0.500,PRECISE=YES" in lines
    assert [l for l in lines if l.startswith("https://")] == [url(f"s/hls/seg_{i:05d}.ts") for i in (2, 3, 4)]
    assert lines[-1] == "#EXT-X-ENDLIST"


def test_playlist_aligned_start_has_no_offset_and_handles_short_last_segment():
    segs = make_segments(5, last=700)
    body = build_playlist(segs, 0, 8700, url)
    assert "TIME-OFFSET" not in body
    assert body.count("#EXTINF:") == 5
    assert "#EXTINF:0.700," in body


def test_playlist_unsorted_input():
    segs = list(reversed(make_segments(4)))
    body = build_playlist(segs, 0, 8000, url)
    assert body.index("seg_00000") < body.index("seg_00003")


def test_playlist_empty_range_raises():
    with pytest.raises(ValueError):
        build_playlist(make_segments(3), 10_000, 12_000, url)


@pytest.mark.parametrize(
    "start,end,dur",
    [
        (0, 5000, 10_000),  # trim
        (0, 10_000, 10_000),  # extend to the very end
        (9000, 10_000, 10_000),  # minimum length at the end
    ],
)
def test_valid_clip_ranges(start, end, dur):
    validate_clip_range(start, end, dur)


@pytest.mark.parametrize(
    "start,end,dur,msg",
    [
        (-1, 5000, 10_000, ">= 0"),
        (5000, 5000, 10_000, "greater than"),
        (6000, 5000, 10_000, "greater than"),
        (0, 10_001, 10_000, "past the end"),
        (1000, 1500, 10_000, "at least"),
        (0, 1000, None, "not been processed"),
    ],
)
def test_invalid_clip_ranges(start, end, dur, msg):
    with pytest.raises(ValueError, match=msg):
        validate_clip_range(start, end, dur)
