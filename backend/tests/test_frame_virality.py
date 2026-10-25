import math
import uuid

import pytest

from app.services.frame_virality import (
    VIRALITY_PROMPTS,
    EventInput,
    FrameInput,
    ScoredFrame,
    TranscriptInput,
    clear_prompt_cache,
    image_visibility_score,
    prompt_embeddings,
    score_frames,
    select_contextual_highlights,
    select_highlights,
)


def _frame(t_ms: int, vector: list[float]) -> FrameInput:
    return FrameInput(uuid.uuid4(), t_ms, vector, f"frames/{t_ms}.jpg")


def test_scores_combine_visual_event_and_reaction_evidence():
    prompts = [[1.0, 0.0]] * (len(VIRALITY_PROMPTS) - 1) + [[0.0, 1.0]]
    frames = [_frame(0, [0.0, 1.0]), _frame(1000, [1.0, 0.0]), _frame(2000, [0.0, 1.0])]

    scores = score_frames(
        frames,
        [EventInput(1000, 1.0, "clutch")],
        [TranscriptInput(800, 1200, "NO WAY! INSANE clutch!")],
        prompts,
    )

    assert [score.t_ms for score in scores] == [0, 1000, 2000]
    assert max(scores, key=lambda score: score.score).t_ms == 1000
    middle = scores[1]
    assert middle.visual_score == 1.0
    assert middle.event_score == 1.0
    assert middle.speech_score > 0.5
    assert all(0 <= value <= 1 for score in scores for value in (
        score.score, score.visual_score, score.novelty_score, score.event_score, score.speech_score,
        score.visibility_score, score.scene_score,
    ))


def test_image_visibility_penalizes_nearly_black_frames():
    dark = b"P5\n8 8\n255\n" + bytes([8] * 64)
    visible = b"P5\n8 8\n255\n" + bytes([150] * 64)

    assert image_visibility_score(dark) < 0.1
    assert image_visibility_score(visible) > 0.7


def test_sustained_visible_scene_beats_an_isolated_semantic_spike():
    prompts = [[1.0, 0.0]] * (len(VIRALITY_PROMPTS) - 1) + [[0.0, 1.0]]
    frames = []
    for index in range(13):
        strong = index == 0 or 7 <= index <= 10
        frames.append(
            FrameInput(
                uuid.uuid4(),
                index * 2000,
                [1.0, 0.0] if strong else [0.0, 1.0],
                visibility_score=1.0,
            )
        )

    scores = score_frames(frames, [], [], prompts)

    assert max(scores, key=lambda score: score.score).t_ms in {14_000, 16_000, 18_000, 20_000}
    assert scores[8].scene_score > scores[0].scene_score


def test_selects_non_overlapping_windows_and_keeps_full_length_at_edges():
    frames = [
        ScoredFrame(uuid.uuid4(), 1000, None, 0.95, 1, 1, 1, 0),
        ScoredFrame(uuid.uuid4(), 2500, None, 0.90, 1, 1, 1, 0),
        ScoredFrame(uuid.uuid4(), 9000, None, 0.85, 1, 1, 1, 0),
    ]

    marked, windows = select_highlights(frames, duration_ms=10_000, count=3, clip_duration_ms=4000)

    assert [(window.start_ms, window.end_ms) for window in windows] == [(0, 4000), (6000, 10_000)]
    assert sum(frame.selected for frame in marked) == 2
    assert {window.frame.t_ms for window in windows} == {1000, 9000}


def test_quiet_video_still_gets_one_best_effort_highlight():
    frames = [
        ScoredFrame(uuid.uuid4(), 1000, None, 0.1, 0, 0, 0, 0),
        ScoredFrame(uuid.uuid4(), 5000, None, 0.2, 0, 0, 0, 0),
    ]
    marked, windows = select_highlights(frames, 8000, 3, 3000, min_score=0.9)
    assert len(windows) == 1 and windows[0].frame.t_ms == 5000
    assert sum(frame.selected for frame in marked) == 1


def test_context_window_keeps_weaker_neighbours_until_a_sustained_valley():
    values = [0.08, 0.10, 0.20, 0.40, 0.62, 0.95, 0.58, 0.48, 0.10, 0.52, 0.42, 0.16, 0.08, 0.07, 0.06]
    frames = [
        ScoredFrame(uuid.uuid4(), index * 2000, None, value, value, 0, 0, 0)
        for index, value in enumerate(values)
    ]

    marked, windows = select_contextual_highlights(frames, duration_ms=30_000, count=1)

    assert len(windows) == 1
    assert windows[0].frame.t_ms == 10_000
    assert windows[0].start_ms <= 7000
    # The dip at 16 seconds is retained because popularity rebounds immediately.
    assert windows[0].end_ms >= 21_000
    # The repeated weak frames after the event establish a boundary.
    assert windows[0].end_ms < 27_000
    assert sum(frame.selected for frame in marked) == 1


def test_contextual_selector_returns_three_distinct_peak_regions():
    frames = []
    for t_ms in range(0, 121_000, 2000):
        score = 0.05 + max(
            0.90 * math.exp(-((t_ms - 20_000) / 5000) ** 2),
            0.82 * math.exp(-((t_ms - 60_000) / 6500) ** 2),
            0.86 * math.exp(-((t_ms - 100_000) / 4500) ** 2),
        )
        frames.append(ScoredFrame(uuid.uuid4(), t_ms, None, score, score, 0, 0, 0))

    marked, windows = select_contextual_highlights(frames, duration_ms=121_000)

    assert len(windows) == 3
    assert {window.frame.t_ms for window in windows} == {20_000, 60_000, 100_000}
    assert all(first.end_ms <= second.start_ms for first, second in zip(windows, windows[1:]))
    assert sum(frame.selected for frame in marked) == 3


def test_prompt_vectors_are_reused_in_worker_process():
    class CountingEmbedder:
        dim = 2
        calls = 0

        def embed_texts(self, texts):
            self.calls += 1
            return [[1.0, 0.0] for _ in texts]

    clear_prompt_cache()
    embedder = CountingEmbedder()
    assert prompt_embeddings(embedder) == prompt_embeddings(embedder)
    assert embedder.calls == 1


def test_rejects_wrong_prompt_vector_count():
    with pytest.raises(ValueError, match="expected"):
        score_frames([_frame(0, [1.0, 0.0])], [], [], [[1.0, 0.0]])
