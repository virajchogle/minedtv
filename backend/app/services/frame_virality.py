"""Rank already-sampled video frames and turn the strongest peaks into clip windows.

The scorer deliberately consumes artifacts produced by the normal upload pipeline:
CLIP embeddings, detected events, and transcript windows. It never decodes or uploads
the source video again.
"""

from __future__ import annotations

import math
import threading
import uuid
from io import BytesIO
from dataclasses import dataclass, replace
from typing import Sequence

from PIL import Image, ImageStat

from app.ml.interfaces import Embedder

ALGORITHM_VERSION = "frame-virality-v2-visibility"
CONTEXTUAL_ALGORITHM_VERSION = "frame-virality-v3-visibility-context"

# These are embedded once per worker process. The final prompt is the deliberately
# boring baseline used for a contrastive visual score.
VIRALITY_PROMPTS = (
    "an exciting climactic gaming highlight with intense action",
    "an impressive skillful play worth sharing",
    "a surprising funny or emotional gaming reaction",
    "a dramatic win, clutch, celebration, or payoff",
    "ordinary uneventful gameplay with nothing happening",
)

_PROMPT_CACHE: dict[tuple[type, int], tuple[tuple[float, ...], ...]] = {}
_PROMPT_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class FrameInput:
    frame_id: uuid.UUID
    t_ms: int
    embedding: Sequence[float]
    thumbnail_key: str | None = None
    visibility_score: float = 1.0


@dataclass(frozen=True)
class EventInput:
    t_ms: int
    score: float
    type: str = "event"


@dataclass(frozen=True)
class TranscriptInput:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class ScoredFrame:
    frame_id: uuid.UUID
    t_ms: int
    thumbnail_key: str | None
    score: float
    visual_score: float
    novelty_score: float
    event_score: float
    speech_score: float
    visibility_score: float = 1.0
    scene_score: float = 0.0
    selected: bool = False


@dataclass(frozen=True)
class HighlightWindow:
    start_ms: int
    end_ms: int
    frame: ScoredFrame


def _unit(values: Sequence[float]) -> tuple[float, ...]:
    vector = tuple(float(v) for v in values)
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return tuple(v / norm for v in vector)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _mean_unit(vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    if not vectors:
        return ()
    return _unit([sum(items) / len(vectors) for items in zip(*vectors, strict=True)])


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _smoothstep(low: float, high: float, value: float) -> float:
    if high <= low:
        return float(value >= high)
    position = _clamp((value - low) / (high - low))
    return position * position * (3.0 - 2.0 * position)


def image_visibility_score(image: bytes) -> float:
    """Estimate whether viewers can understand a frame without boosting bright title cards.

    Mean luminance supplies the strongest signal, while visible-area and contrast terms
    preserve legitimately dark scenes that still contain readable subjects and detail.
    The result is absolute rather than ranked within one video, so a mostly black frame
    cannot become "high quality" merely because the rest of the upload is also dark.
    """
    with Image.open(BytesIO(image)) as source:
        grayscale = source.convert("L")
        grayscale.thumbnail((96, 96))
        histogram = grayscale.histogram()
        pixels = max(1, sum(histogram))
        mean = sum(level * count for level, count in enumerate(histogram)) / pixels / 255.0
        deviation = ImageStat.Stat(grayscale).stddev[0] / 255.0
        dark_fraction = sum(histogram[:32]) / pixels

    brightness = _smoothstep(0.07, 0.32, mean)
    contrast = _smoothstep(0.035, 0.18, deviation)
    visible_area = _smoothstep(0.15, 0.80, 1.0 - dark_fraction)
    score = 0.55 * brightness + 0.25 * visible_area + 0.20 * contrast
    if mean < 0.045:
        score *= 0.25
    return round(_clamp(score), 6)


def prompt_embeddings(embedder: Embedder) -> tuple[tuple[float, ...], ...]:
    """Return cached prompt vectors; repeated jobs do not make repeated model calls."""
    key = (type(embedder), int(embedder.dim))
    with _PROMPT_CACHE_LOCK:
        cached = _PROMPT_CACHE.get(key)
        if cached is not None:
            return cached
        # Keep the lock through the model call so two simultaneous jobs cannot both
        # warm the exact same prompt set.
        embedded = tuple(_unit(v) for v in embedder.embed_texts(list(VIRALITY_PROMPTS)))
        if len(embedded) != len(VIRALITY_PROMPTS):
            raise ValueError("embedder returned the wrong number of virality prompt vectors")
        _PROMPT_CACHE[key] = embedded
        return embedded


def _percentile_ranks(values: Sequence[float]) -> list[float]:
    """Average-rank percentiles, with ties neutral instead of arbitrarily ordered."""
    if not values:
        return []
    if len(values) == 1:
        return [0.5]
    ordered = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and math.isclose(values[ordered[j]], values[ordered[i]], rel_tol=1e-9, abs_tol=1e-12):
            j += 1
        percentile = ((i + j - 1) / 2) / (len(values) - 1)
        for k in range(i, j):
            result[ordered[k]] = percentile
        i = j
    return result


_REACTION_WORDS = {
    "ace", "amazing", "clutch", "crazy", "insane", "legendary", "no way", "omg",
    "unbelievable", "wow", "wtf", "yes", "let's go", "lets go",
}


def _reaction_strength(text: str) -> float:
    normalized = " ".join(text.lower().split())
    hits = sum(phrase in normalized for phrase in _REACTION_WORDS)
    punctuation = min(0.2, text.count("!") * 0.08 + text.count("?") * 0.04)
    uppercase_words = sum(len(word) >= 3 and word.isupper() for word in text.split())
    return min(1.0, hits * 0.22 + punctuation + min(0.2, uppercase_words * 0.08))


def _distance_to_range(t_ms: int, start_ms: int, end_ms: int) -> int:
    if t_ms < start_ms:
        return start_ms - t_ms
    if t_ms > end_ms:
        return t_ms - end_ms
    return 0


def score_frames(
    frames: Sequence[FrameInput],
    events: Sequence[EventInput],
    transcripts: Sequence[TranscriptInput],
    prompts: Sequence[Sequence[float]],
) -> list[ScoredFrame]:
    """Calculate a 0..1 virality score and explainable components for every frame."""
    if not frames:
        return []
    if len(prompts) != len(VIRALITY_PROMPTS):
        raise ValueError(f"expected {len(VIRALITY_PROMPTS)} prompt embeddings")

    ordered = sorted(frames, key=lambda f: f.t_ms)
    image_vectors = [_unit(frame.embedding) for frame in ordered]
    positive = _mean_unit([_unit(v) for v in prompts[:-1]])
    baseline = _unit(prompts[-1])
    visual_raw = [_dot(vector, positive) - _dot(vector, baseline) for vector in image_vectors]
    visual = _percentile_ranks(visual_raw)
    visibility = [_clamp(frame.visibility_score) for frame in ordered]

    novelty_raw: list[float] = []
    for i, vector in enumerate(image_vectors):
        neighbours = []
        if i:
            neighbours.append(max(0.0, 1.0 - _dot(vector, image_vectors[i - 1])))
        if i + 1 < len(image_vectors):
            neighbours.append(max(0.0, 1.0 - _dot(vector, image_vectors[i + 1])))
        novelty_raw.append(sum(neighbours) / len(neighbours) if neighbours else 0.0)
    novelty = _percentile_ranks(novelty_raw)

    event_signal: list[float] = []
    speech_signal: list[float] = []
    speech_strengths = [
        (cue, strength)
        for cue in transcripts
        if (strength := _reaction_strength(cue.text)) > 0
    ]
    for frame in ordered:
        event_signal.append(
            max(
                (max(0.0, min(1.0, event.score)) * math.exp(-abs(frame.t_ms - event.t_ms) / 1800) for event in events),
                default=0.0,
            )
        )
        speech_signal.append(
            max(
                (
                    strength * math.exp(-_distance_to_range(frame.t_ms, cue.start_ms, cue.end_ms) / 2500)
                    for cue, strength in speech_strengths
                ),
                default=0.0,
            )
        )

    # A shareable moment should remain understandable for more than one isolated
    # sample. Build a wider scene signal from nearby visible frames so sustained
    # action beats title cards, cuts, and single flashlight flashes.
    moment_strength = [
        (0.78 * visual[i] + 0.22 * novelty[i]) * (0.15 + 0.85 * visibility[i])
        for i in range(len(ordered))
    ]
    scene_signal: list[float] = []
    for i, frame in enumerate(ordered):
        weighted = total_weight = 0.0
        for j, neighbour in enumerate(ordered):
            distance = abs(neighbour.t_ms - frame.t_ms)
            if distance > 8000:
                continue
            weight = math.exp(-distance / 5000)
            weighted += moment_strength[j] * weight
            total_weight += weight
        scene_signal.append(weighted / total_weight if total_weight else moment_strength[i])

    # Visibility gates only the purely visual evidence. A verified detector event or
    # excited speech may still rescue a dim but meaningful scene. The wider scene
    # signal rewards coherent action instead of an isolated high-contrast frame.
    base = [
        (0.15 + 0.85 * visibility[i]) * (0.25 * visual[i] + 0.05 * novelty[i])
        + 0.30 * scene_signal[i]
        + 0.28 * event_signal[i]
        + 0.12 * speech_signal[i]
        for i in range(len(ordered))
    ]
    smoothed: list[float] = []
    for i, frame in enumerate(ordered):
        weighted = total_weight = 0.0
        j = i
        while j >= 0 and frame.t_ms - ordered[j].t_ms <= 2000:
            weight = math.exp(-(frame.t_ms - ordered[j].t_ms) / 1500)
            weighted += base[j] * weight
            total_weight += weight
            j -= 1
        j = i + 1
        while j < len(ordered) and ordered[j].t_ms - frame.t_ms <= 2000:
            weight = math.exp(-(ordered[j].t_ms - frame.t_ms) / 1500)
            weighted += base[j] * weight
            total_weight += weight
            j += 1
        local = weighted / total_weight if total_weight else base[i]
        smoothed.append(min(1.0, max(0.0, 0.75 * base[i] + 0.25 * local)))

    return [
        ScoredFrame(
            frame_id=frame.frame_id,
            t_ms=frame.t_ms,
            thumbnail_key=frame.thumbnail_key,
            score=round(smoothed[i], 6),
            visual_score=round(visual[i], 6),
            novelty_score=round(novelty[i], 6),
            event_score=round(event_signal[i], 6),
            speech_score=round(speech_signal[i], 6),
            visibility_score=round(visibility[i], 6),
            scene_score=round(scene_signal[i], 6),
        )
        for i, frame in enumerate(ordered)
    ]


def _window_around(t_ms: int, duration_ms: int, clip_duration_ms: int) -> tuple[int, int]:
    length = min(duration_ms, clip_duration_ms)
    # A little more room after the peak preserves the payoff/reaction.
    start = max(0, t_ms - round(length * 0.4))
    end = min(duration_ms, start + length)
    start = max(0, end - length)
    return start, end


def select_highlights(
    scores: Sequence[ScoredFrame],
    duration_ms: int,
    count: int,
    clip_duration_ms: int,
    min_score: float = 0.42,
) -> tuple[list[ScoredFrame], list[HighlightWindow]]:
    """Choose high-scoring, non-overlapping peaks and preserve full clip length at edges."""
    if not scores or duration_ms <= 0 or count <= 0:
        return list(scores), []

    chosen: list[HighlightWindow] = []
    for frame in sorted(scores, key=lambda item: (-item.score, item.t_ms)):
        if chosen and frame.score < min_score:
            break
        start, end = _window_around(frame.t_ms, duration_ms, clip_duration_ms)
        if end - start < 1000 or any(start < old.end_ms and end > old.start_ms for old in chosen):
            continue
        chosen.append(HighlightWindow(start, end, frame))
        if len(chosen) == count:
            break

    # Even quiet videos should return one best-effort highlight rather than no result.
    if not chosen:
        frame = max(scores, key=lambda item: (item.score, -item.t_ms))
        start, end = _window_around(frame.t_ms, duration_ms, clip_duration_ms)
        if end - start >= 1000:
            chosen.append(HighlightWindow(start, end, frame))

    selected_ids = {window.frame.frame_id for window in chosen}
    marked = [replace(frame, selected=frame.frame_id in selected_ids) for frame in scores]
    marked_by_id = {frame.frame_id: frame for frame in marked}
    windows = [replace(window, frame=marked_by_id[window.frame.frame_id]) for window in chosen]
    return marked, sorted(windows, key=lambda window: window.start_ms)


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _sample_interval_ms(scores: Sequence[ScoredFrame]) -> int:
    gaps = [
        later.t_ms - earlier.t_ms
        for earlier, later in zip(scores, scores[1:])
        if later.t_ms > earlier.t_ms
    ]
    return max(250, round(_percentile(gaps, 0.5))) if gaps else 1000


def _context_boundary(
    ordered: Sequence[ScoredFrame],
    peak_index: int,
    direction: int,
    *,
    baseline: float,
    minimum_context_ms: int,
    maximum_context_ms: int,
) -> int:
    """Walk a score curve until a sustained valley separates the peak from context."""
    peak = ordered[peak_index]
    span = max(0.08, peak.score - baseline)
    index = peak_index
    last_included = peak_index
    low_run = 0

    while True:
        index += direction
        if index < 0 or index >= len(ordered):
            break
        distance = abs(ordered[index].t_ms - peak.t_ms)
        if distance > maximum_context_ms:
            break

        relative_score = max(0.0, (ordered[index].score - baseline) / span)
        proximity = math.exp(-distance / 12_000)
        support = 0.72 * relative_score + 0.28 * proximity

        # Setup and payoff are always retained. Outside that core, a one-sample
        # dip is allowed; only two weak samples in a row establish a true valley.
        if distance <= minimum_context_ms or support >= 0.30:
            last_included = index
            low_run = 0
        else:
            low_run += 1
            if low_run == 1:
                last_included = index
            else:
                break

    return last_included


def _adaptive_window(
    ordered: Sequence[ScoredFrame],
    peak_index: int,
    duration_ms: int,
    baseline: float,
    *,
    min_clip_ms: int,
    max_clip_ms: int,
) -> tuple[int, int]:
    peak = ordered[peak_index]
    interval = _sample_interval_ms(ordered)
    before_limit = round(max_clip_ms * 0.42)
    after_limit = max_clip_ms - before_limit
    left = _context_boundary(
        ordered,
        peak_index,
        -1,
        baseline=baseline,
        minimum_context_ms=min(5000, round(min_clip_ms * 0.42)),
        maximum_context_ms=before_limit,
    )
    right = _context_boundary(
        ordered,
        peak_index,
        1,
        baseline=baseline,
        minimum_context_ms=min(7000, min_clip_ms - round(min_clip_ms * 0.42)),
        maximum_context_ms=after_limit,
    )

    start = max(0, ordered[left].t_ms - interval // 2)
    end = min(duration_ms, ordered[right].t_ms + interval // 2)
    if end - start < min_clip_ms:
        start, end = _window_around(peak.t_ms, duration_ms, min_clip_ms)
    if end - start > max_clip_ms:
        start, end = _window_around(peak.t_ms, duration_ms, max_clip_ms)
    return start, end


def select_contextual_highlights(
    scores: Sequence[ScoredFrame],
    duration_ms: int,
    count: int = 3,
    *,
    min_clip_ms: int = 10_000,
    max_clip_ms: int = 45_000,
) -> tuple[list[ScoredFrame], list[HighlightWindow]]:
    """Select distinct peaks and derive clip lengths from their surrounding score curves.

    The peak is not treated as an isolated frame. Each side expands while nearby
    frames retain enough relative popularity, and a brief low-scoring transition is
    kept as context. A sustained valley separates one highlight from the next.
    """
    if not scores or duration_ms <= 0 or count <= 0:
        return list(scores), []

    ordered = sorted(scores, key=lambda item: item.t_ms)
    baseline = _percentile([frame.score for frame in ordered], 0.25)
    local_maxima = [
        index
        for index, frame in enumerate(ordered)
        if (index == 0 or frame.score >= ordered[index - 1].score)
        and (index == len(ordered) - 1 or frame.score > ordered[index + 1].score)
    ]
    ranked = sorted(
        local_maxima or range(len(ordered)),
        key=lambda index: (-ordered[index].score, ordered[index].t_ms),
    )

    chosen: list[HighlightWindow] = []
    for index in ranked:
        frame = ordered[index]
        start, end = _adaptive_window(
            ordered,
            index,
            duration_ms,
            baseline,
            min_clip_ms=min(min_clip_ms, duration_ms),
            max_clip_ms=min(max_clip_ms, duration_ms),
        )
        if end - start < 1000:
            continue
        # Avoid near-duplicate clips. A new peak must sit outside previous context,
        # and its adaptive window may overlap at most 20% with an existing one.
        duplicate = False
        for old in chosen:
            overlap = max(0, min(end, old.end_ms) - max(start, old.start_ms))
            shorter = max(1, min(end - start, old.end_ms - old.start_ms))
            if old.start_ms <= frame.t_ms <= old.end_ms or overlap / shorter > 0.20:
                duplicate = True
                break
        if duplicate:
            continue
        chosen.append(HighlightWindow(start, end, frame))
        if len(chosen) == count:
            break

    if not chosen:
        peak_index = max(range(len(ordered)), key=lambda index: (ordered[index].score, -ordered[index].t_ms))
        start, end = _adaptive_window(
            ordered,
            peak_index,
            duration_ms,
            baseline,
            min_clip_ms=min(min_clip_ms, duration_ms),
            max_clip_ms=min(max_clip_ms, duration_ms),
        )
        if end - start >= 1000:
            chosen.append(HighlightWindow(start, end, ordered[peak_index]))

    selected_ids = {window.frame.frame_id for window in chosen}
    marked = [replace(frame, selected=frame.frame_id in selected_ids) for frame in ordered]
    marked_by_id = {frame.frame_id: frame for frame in marked}
    windows = [replace(window, frame=marked_by_id[window.frame.frame_id]) for window in chosen]
    return marked, sorted(windows, key=lambda window: window.start_ms)


def clear_prompt_cache() -> None:
    """Test helper."""
    with _PROMPT_CACHE_LOCK:
        _PROMPT_CACHE.clear()
