import uuid

from app.schemas import ClipHighlightsIn, CreatorPackOut
from app.services.frame_virality import HighlightWindow, ScoredFrame
from app.worker.clip_highlights import _select_windows, build_caption_lines, options_hash


def _frame(t_ms: int, score: float) -> ScoredFrame:
    return ScoredFrame(uuid.uuid4(), t_ms, None, score, score, 0.5, 0.0, 0.0, 1.0, score)


def _pack(*, transcript=None, moments=None) -> CreatorPackOut:
    return CreatorPackOut.model_validate(
        {
            "title_options": ["The hook"],
            "description": "A full description.",
            "summary": "A short summary.",
            "caption": "Share caption",
            "youtube": {"title": "Title", "description": "Description", "tags": ["game"], "chapters": []},
            "reddit": {"title": "Title", "body": "Body", "suggested_subreddits": ["gaming"]},
            "transcript": transcript or [],
            "key_moments": moments or [],
            "hashtags": ["Gaming"],
            "content_warnings": [],
        }
    )


def test_highlight_options_are_stable_and_cache_distinct_renders():
    first = ClipHighlightsIn()
    assert options_hash(first) == options_hash(first.model_dump())
    assert options_hash(first) != options_hash(first.model_copy(update={"mode": "montage"}))
    assert options_hash(first) != options_hash(first.model_copy(update={"captions": False}))


def test_single_mode_uses_one_adaptive_window_with_two_second_lead():
    scores = [_frame(0, 0.1), _frame(10_000, 0.3), _frame(20_000, 0.9), _frame(30_000, 0.2)]
    marked, windows = _select_windows(scores, 40_000, "single")

    assert len(windows) == 1
    assert windows[0].frame.t_ms == 20_000
    assert windows[0].start_ms == 18_000
    assert 10_000 <= windows[0].end_ms - windows[0].start_ms <= 25_000
    assert sum(frame.selected for frame in marked) == 1


def test_caption_lines_map_pack_timestamps_and_preserve_hook():
    window = HighlightWindow(3_000, 10_000, _frame(6_000, 0.8))
    pack = _pack(transcript=[{"timestamp": "00:05", "text": "There has to be someone here."}])

    lines = build_caption_lines(pack, [window], include_hook=True, reasons=["Security camera discovery"])

    assert lines[0] == {"start_ms": 0, "end_ms": 2500, "text": "The hook", "kind": "hook"}
    speech = next(line for line in lines if line["kind"] == "speech")
    assert speech["start_ms"] == 2500
    assert speech["text"] == "There has to be someone here."


def test_caption_lines_fall_back_to_key_moment_without_speech():
    window = HighlightWindow(3_000, 10_000, _frame(6_000, 0.8))
    pack = _pack(moments=[{"timestamp": "00:06", "label": "Leon checks the security footage"}])

    lines = build_caption_lines(pack, [window], include_hook=False, reasons=["Fallback reason"])

    assert lines == [
        {
            "start_ms": 3000,
            "end_ms": 5500,
            "text": "Leon checks the security footage",
            "kind": "moment",
        }
    ]
