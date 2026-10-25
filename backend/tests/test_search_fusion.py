import uuid

import pytest

from app.ml.interfaces import TranscriptChunk
from app.services.search import Filters, Hit, cache_key, event_types_for, fuse, group_by_session, rrf
from app.worker.pipeline import merge_transcript_chunks, pick_highlight_windows


def test_rrf_scores_match_formula():
    scores = rrf([["a", "b", "c"], ["b", "a"]], k=60)
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["c"] == pytest.approx(1 / 63)


def test_rrf_rewards_agreement_over_single_top_rank():
    scores = rrf([["x", "y"], ["y"], ["y"]], k=60)
    assert scores["y"] > scores["x"]


def test_rrf_counts_duplicates_once_per_list():
    scores = rrf([["a", "a", "b"]], k=60)
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 63)


def test_rrf_empty():
    assert rrf([], k=60) == {}
    assert rrf([[], []], k=60) == {}


def test_fuse_buckets_nearby_hits_and_keeps_best_ranked_timestamp():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    lists = {
        "visual": [Hit(s1, 12_300, "visual", 0.9), Hit(s2, 1000, "visual", 0.5)],
        "speech": [Hit(s1, 11_000, "speech", 0.8, "no way he clutched that")],
        "keyword": [],
        "event": [Hit(s2, 40_000, "event", 0.99)],
    }
    moments = fuse(lists, k=60, window_ms=5000)
    top = moments[0]
    assert top.session_id == s1
    assert top.signals == {"visual", "speech"}
    assert top.t_ms == 12_300  # both rank it #1; visual is processed first so it anchors
    assert top.snippet == "no way he clutched that"
    grouped = group_by_session(moments)
    assert [g.best.session_id for g in grouped] == [s1, s2]
    assert len(grouped[1].others) == 1


def test_event_type_matching():
    assert event_types_for("the clutch on Bind") == ["clutch"]
    assert set(event_types_for("when my friend screamed after the ace")) == {"ace", "loud"}
    assert event_types_for("sunset over the map") == []


def test_cache_key_normalizes_query():
    f = Filters(game="Valorant")
    assert cache_key("  The Clutch  on bind", f, 20) == cache_key("the clutch on bind", Filters(game="valorant"), 20)
    assert cache_key("the clutch", f, 20) != cache_key("the clutch", f, 10)


def test_merge_transcript_chunks_into_windows():
    chunks = [
        TranscriptChunk(0, 2000, "one"),
        TranscriptChunk(2000, 4000, "two"),
        TranscriptChunk(4000, 6000, "three"),
        TranscriptChunk(6000, 8000, "four"),
        TranscriptChunk(8000, 20_000, "long monologue"),
        TranscriptChunk(20_000, 21_000, "  "),
    ]
    windows = merge_transcript_chunks(chunks, 5000, 10_000)
    assert [(w.start_ms, w.end_ms, w.text) for w in windows] == [
        (0, 6000, "one two three"),
        (6000, 8000, "four"),
        (8000, 20_000, "long monologue"),
    ]


def test_merge_transcript_chunks_splits_on_speaker():
    chunks = [TranscriptChunk(0, 1000, "hi", "a"), TranscriptChunk(1000, 2000, "yo", "b")]
    assert len(merge_transcript_chunks(chunks, 5000, 10_000)) == 2


def test_pick_highlight_windows_non_overlapping_top_scores():
    events = [(5000, "kill", 0.5), (6000, "ace", 0.9), (30_000, "clutch", 0.7), (59_000, "win", 0.6)]
    windows = pick_highlight_windows(events, 60_000, 3000, 3)
    assert windows == [(3000, 9000, 6000, "ace"), (27_000, 33_000, 30_000, "clutch"), (56_000, 60_000, 59_000, "win")]


def test_fuse_merges_hits_across_fixed_bucket_boundaries():
    s = uuid.uuid4()
    lists = {"keyword": [Hit(s, 14_000, "keyword", 1.0, "that clutch")], "event": [Hit(s, 15_000, "event", 0.9)]}
    moments = fuse(lists, k=60, window_ms=5000)
    assert len(moments) == 1
    assert moments[0].signals == {"keyword", "event"}
    assert moments[0].score == pytest.approx(2 / 61)


def test_drop_weak_keeps_exact_signals_and_strong_semantic_hits():
    from app.services.search import Thresholds, drop_weak

    s = uuid.uuid4()
    lists = {
        "visual": [Hit(s, 1000, "visual", 0.30), Hit(s, 2000, "visual", 0.18)],
        "speech": [Hit(s, 3000, "speech", 0.08), Hit(s, 4000, "speech", 0.001)],
        "keyword": [Hit(s, 5000, "keyword", 0.01)],
        "event": [Hit(s, 6000, "event", 0.2, label="kill")],
    }
    kept = drop_weak(lists, Thresholds(visual=0.22, speech=0.03))
    assert [h.t_ms for h in kept["visual"]] == [1000]
    assert [h.t_ms for h in kept["speech"]] == [3000]
    assert len(kept["keyword"]) == 1 and len(kept["event"]) == 1


def test_confidence_rises_with_agreement_and_strength():
    from app.services.search import Thresholds, confidence

    th = Thresholds()
    weak_visual = confidence({"visual": 0.04}, th)
    strong_visual = confidence({"visual": 0.09}, th)
    assert 0.0 < weak_visual < strong_visual <= 1.0
    assert confidence({"visual": 0.06, "speech": 0.08}, th) > max(confidence({"visual": 0.06}, th), confidence({"speech": 0.08}, th))
    assert confidence({"keyword": 0.1}, th) == pytest.approx(0.85)
    assert confidence({}, th) == 0.0


def test_fuse_tracks_strength_and_event_label():
    s = uuid.uuid4()
    lists = {"speech": [Hit(s, 10_000, "speech", 0.8, "gg")], "event": [Hit(s, 10_500, "event", 0.9, label="clutch")]}
    m = fuse(lists, k=60, window_ms=5000)[0]
    assert m.label == "clutch" and m.strength == {"speech": 0.8, "event": 0.9}



def test_relative_cutoff_drops_lookalikes():
    from app.services.search import Thresholds, drop_weak

    knife, gun, gun2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # Contrastive scores measured on real clips for "knife" (default relative cutoff 0.75).
    lists = {"visual": [Hit(knife, 1000, "visual", 0.063), Hit(gun, 2000, "visual", 0.033), Hit(gun2, 3000, "visual", 0.032)]}
    kept = drop_weak(lists, Thresholds())
    assert [h.session_id for h in kept["visual"]] == [knife]


def test_mean_unit_is_normalized():
    from app.services.search import mean_unit

    v = mean_unit([[1.0, 0.0], [0.0, 1.0]])
    assert abs(sum(x * x for x in v) - 1) < 1e-9 and abs(v[0] - v[1]) < 1e-9



def test_lone_weak_speech_dropped_but_backed_speech_kept():
    from app.services.search import Moment, Thresholds, drop_lone_weak_speech

    s = uuid.uuid4()
    lone_weak = Moment(s, 0, 0.1, {"speech"}, strength={"speech": 0.04})
    lone_strong = Moment(s, 10_000, 0.1, {"speech"}, strength={"speech": 0.08})
    backed = Moment(s, 20_000, 0.1, {"speech", "keyword"}, strength={"speech": 0.04, "keyword": 0.1})
    kept = drop_lone_weak_speech([lone_weak, lone_strong, backed], Thresholds())
    assert kept == [lone_strong, backed]


def test_rank_moments_by_confidence_then_fusion_score():
    from app.services.search import Moment, rank_moments

    s = uuid.uuid4()
    a = Moment(s, 0, score=0.033, confidence=0.56)  # top by fusion score only
    b = Moment(s, 1, score=0.016, confidence=0.59)
    c = Moment(s, 2, score=0.020, confidence=0.59)
    assert rank_moments([a, b, c]) == [c, b, a]
