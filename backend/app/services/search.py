"""Hybrid search over frames, speech and highlight events.

Four signals run in parallel (each on its own DB connection), are merged with
reciprocal rank fusion, grouped by session, and resolved to the clip containing the
best moment (or a suggested window around it).
"""

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select, exists, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Clip, Event, Frame, Session, SessionStatus, Transcript, User
from app.ml.interfaces import Embedder

log = logging.getLogger(__name__)

SIGNALS = ("visual", "speech", "keyword", "event")

# Query words that map to event types the highlight detector emits.
EVENT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "kill": ("kill", "kills", "killed", "frag", "frags", "elim", "elims", "eliminated", "elimination"),
    "multikill": ("multikill", "multi", "double", "triple", "quad", "quadra", "penta", "spray", "wipe", "squad"),
    "headshot": ("headshot", "headshots", "hs", "onetap", "tap"),
    "clutch": ("clutch", "clutched", "1v2", "1v3", "1v4", "1v5", "comeback"),
    "ace": ("ace", "aced"),
    "win": ("win", "won", "victory", "winning", "dub"),
    "death": ("death", "died", "die", "dead", "killed me", "got killed"),
    "loud": ("scream", "screamed", "screaming", "yell", "yelled", "loud", "shout", "shouted", "hype", "reaction"),
    "funny": ("funny", "lol", "laugh", "laughing", "fail", "bug", "glitch", "troll"),
}


# CLIP matches a phrased description better than a bare word, so visual queries are embedded
# with these templates and averaged. The baseline describes "any gameplay frame"; subtracting
# its similarity removes what every FPS/game frame shares, so the query's subject decides.
VISUAL_TEMPLATES = (
    "{}",
    "a screenshot of a video game showing {}",
    "a first-person view of a player holding {} in a video game",
    "gameplay footage with {}",
)
VISUAL_BASELINE_PROMPTS = (
    "a screenshot of a video game",
    "gameplay footage",
    "a first-person shooter game screenshot",
)
# Same idea for voice chat: CLIP's text encoder rates short utterances ("Yeah", "Ah") ~0.8 similar
# to any short query, so speech is scored relative to "generic talking" too.
SPEECH_BASELINE_PROMPTS = (
    "someone talking",
    "people talking while playing a video game",
    "background music",
)
# Shorter lines are filler for semantic matching (still found by exact keyword search).
SPEECH_MIN_WORDS = 3


def mean_unit(vectors: list[list[float]]) -> list[float]:
    m = [sum(c) / len(vectors) for c in zip(*vectors, strict=True)]
    norm = sum(x * x for x in m) ** 0.5 or 1.0
    return [x / norm for x in m]


@dataclass
class Filters:
    game: str | None = None
    user_id: uuid.UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    # Only set when the caller searches their own clips: drafts and "ready" clips are included.
    include_unpublished: bool = False


@dataclass
class Hit:
    session_id: uuid.UUID
    t_ms: int
    signal: str
    raw_score: float
    snippet: str | None = None
    label: str | None = None  # event type, for event hits


@dataclass
class Moment:
    session_id: uuid.UUID
    t_ms: int
    score: float
    signals: set[str] = field(default_factory=set)
    snippet: str | None = None
    label: str | None = None
    # Strongest raw score seen per signal (cosine similarity, ts_rank, or event score).
    strength: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class Thresholds:
    """Minimum scores for semantic hits to count (CLIP ViT-L/14, measured on real gameplay).

    Both semantic signals are contrastive: similarity to the query minus similarity to a generic
    baseline. Visual: the right clip ~0.05-0.10, lookalikes (gun clips for "knife") ~0.02-0.035.
    Speech: the right line ~0.03-0.14, unrelated lines <= 0.001.
    """

    visual: float = 0.035
    speech: float = 0.03
    visual_full: float = 0.10  # score treated as full confidence
    speech_full: float = 0.12
    # Drop visual hits scoring below this fraction of the query's best visual hit.
    visual_relative: float = 0.75
    # A moment matched by speech alone (no keyword/visual/event) needs this stronger speech score,
    # so a query like "knife kills" doesn't surface a voice line that only says "one shot".
    speech_only: float = 0.06


def drop_weak(hit_lists: dict[str, list[Hit]], th: Thresholds) -> dict[str, list[Hit]]:
    """Remove semantic hits below threshold. Keyword and event hits are exact matches and always kept."""
    out = dict(hit_lists)
    visual = [h for h in hit_lists.get("visual", []) if h.raw_score >= th.visual]
    if visual and th.visual_relative > 0:
        floor = max(h.raw_score for h in visual) * th.visual_relative
        visual = [h for h in visual if h.raw_score >= floor]
    out["visual"] = visual
    out["speech"] = [h for h in hit_lists.get("speech", []) if h.raw_score >= th.speech]
    return out


def drop_lone_weak_speech(moments: list["Moment"], th: Thresholds) -> list["Moment"]:
    return [m for m in moments if m.signals != {"speech"} or m.strength.get("speech", 0.0) >= th.speech_only]


def rank_moments(moments: list["Moment"]) -> list["Moment"]:
    """Most confident first; the fusion score breaks ties. Results take their session's best moment."""
    return sorted(moments, key=lambda m: (-m.confidence, -m.score, m.t_ms))


def _ramp(x: float, lo: float, hi: float) -> float:
    return max(0.0, min(1.0, (x - lo) / (hi - lo))) if hi > lo else float(x >= lo)


def confidence(strength: dict[str, float], th: Thresholds) -> float:
    """0..1: how sure we are this moment matches. Each signal gives its own 0..1 and they
    combine like independent evidence (1 - product of misses), so agreement raises it."""
    parts = []
    if "visual" in strength:
        parts.append(0.4 + 0.6 * _ramp(strength["visual"], th.visual, th.visual_full))
    if "speech" in strength:
        parts.append(0.5 + 0.5 * _ramp(strength["speech"], th.speech, th.speech_full))
    if "keyword" in strength:
        parts.append(0.85)
    if "event" in strength:
        parts.append(max(0.5, min(1.0, strength["event"])))
    miss = 1.0
    for p in parts:
        miss *= 1.0 - p
    return round(1.0 - miss, 3)


def normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def event_types_for(q: str) -> list[str]:
    nq = normalize_query(q)
    words = set(re.findall(r"[a-z0-9]+", nq))
    return [t for t, syns in EVENT_SYNONYMS.items() if t in words or any((s in words) if " " not in s else (s in nq) for s in syns)]


def rrf(ranked_lists: Sequence[Sequence[Hashable]], k: int = 60) -> dict[Hashable, float]:
    """Reciprocal rank fusion: score(d) = sum over lists of 1 / (k + rank), rank starting at 1.

    A key appearing more than once in one list only counts at its best rank.
    """
    scores: dict[Hashable, float] = defaultdict(float)
    for ranked in ranked_lists:
        seen = set()
        for rank, key in enumerate(ranked, start=1):
            if key in seen:
                continue
            seen.add(key)
            scores[key] += 1.0 / (k + rank)
    return dict(scores)


def fuse(hit_lists: dict[str, list[Hit]], k: int, window_ms: int) -> list[Moment]:
    """RRF over moments. Hits in the same session within window_ms/2 of a moment's anchor
    count as that moment; the anchor is the best-ranked hit (rank 1 of every signal first,
    then rank 2, ...), so its timestamp is the one we seek to."""
    tolerance = window_ms // 2
    anchors: dict[uuid.UUID, list[tuple[int, int]]] = defaultdict(list)  # session -> [(t_ms, moment_id)]
    moments: list[Moment] = []
    keyed: dict[str, list[int]] = {signal: [] for signal in hit_lists}

    depth = max((len(v) for v in hit_lists.values()), default=0)
    for rank in range(depth):
        for signal in SIGNALS:
            hits = hit_lists.get(signal, [])
            if rank >= len(hits):
                continue
            h = hits[rank]
            mid = next((m for t, m in anchors[h.session_id] if abs(t - h.t_ms) <= tolerance), None)
            if mid is None:
                mid = len(moments)
                moments.append(Moment(h.session_id, h.t_ms, 0.0))
                anchors[h.session_id].append((h.t_ms, mid))
            keyed[signal].append(mid)
            m = moments[mid]
            m.signals.add(signal)
            m.strength[signal] = max(m.strength.get(signal, float("-inf")), h.raw_score)
            if h.snippet and m.snippet is None:
                m.snippet = h.snippet
            if h.label and m.label is None:
                m.label = h.label

    for mid, score in rrf(list(keyed.values()), k).items():
        moments[mid].score = score
    return sorted(moments, key=lambda m: (-m.score, m.t_ms))


@dataclass
class SessionHit:
    best: Moment
    others: list[Moment]


def group_by_session(moments: list[Moment], max_others: int = 3) -> list[SessionHit]:
    grouped: dict[uuid.UUID, SessionHit] = {}
    for m in moments:  # already sorted best-first
        if m.session_id not in grouped:
            grouped[m.session_id] = SessionHit(m, [])
        elif len(grouped[m.session_id].others) < max_others:
            grouped[m.session_id].others.append(m)
    return list(grouped.values())


def cache_key(q: str, f: Filters, limit: int) -> str:
    payload = json.dumps(
        [normalize_query(q), (f.game or "").lower(), str(f.user_id or ""), str(f.date_from or ""), str(f.date_to or ""),
         limit, f.include_unpublished]
    )
    return "search:v3:" + hashlib.sha1(payload.encode()).hexdigest()


# ---------------------------------------------------------------- signal queries


def _filtered(stmt: Select, f: Filters) -> Select:
    stmt = stmt.where(Session.status == SessionStatus.READY)
    if not f.include_unpublished:
        # Public search only looks at sessions that have something published.
        stmt = stmt.where(
            exists().where(Clip.session_id == Session.id, Clip.publish_state == "published", Clip.status == "ready")
        )
    if f.game:
        stmt = stmt.where(func.lower(Session.game) == f.game.lower())
    if f.user_id:
        stmt = stmt.where(Session.user_id == f.user_id)
    when = func.coalesce(Session.started_at, Session.created_at)
    if f.date_from:
        stmt = stmt.where(when >= f.date_from)
    if f.date_to:
        stmt = stmt.where(when <= f.date_to)
    return stmt


async def visual_hits(
    db: AsyncSession, vec: list[float], f: Filters, limit: int, baseline: list[float] | None = None
) -> list[Hit]:
    """Nearest frames to vec. With a baseline, score = sim(query) - sim(baseline): candidates
    come from the vector index (5x the limit), then are re-ranked by that contrastive score."""
    dist = Frame.embedding.cosine_distance(vec)
    cols = [Frame.session_id, Frame.t_ms, (1 - dist).label("sim")]
    if baseline is not None:
        cols.append((1 - Frame.embedding.cosine_distance(baseline)).label("base"))
    stmt = _filtered(select(*cols).join(Session, Session.id == Frame.session_id), f).order_by(dist)
    rows = (await db.execute(stmt.limit(limit * 5 if baseline is not None else limit))).all()
    if baseline is None:
        return [Hit(r.session_id, r.t_ms, "visual", float(r.sim)) for r in rows]
    hits = [Hit(r.session_id, r.t_ms, "visual", float(r.sim) - float(r.base)) for r in rows]
    return sorted(hits, key=lambda h: -h.raw_score)[:limit]


async def speech_hits(
    db: AsyncSession, vec: list[float], f: Filters, limit: int, baseline: list[float] | None = None
) -> list[Hit]:
    """Transcript lines nearest to vec, skipping filler (< SPEECH_MIN_WORDS words). With a
    baseline, score = sim(query) - sim(baseline), re-ranked like visual_hits."""
    dist = Transcript.embedding.cosine_distance(vec)
    cols = [Transcript.session_id, Transcript.start_ms, Transcript.text, (1 - dist).label("sim")]
    if baseline is not None:
        cols.append((1 - Transcript.embedding.cosine_distance(baseline)).label("base"))
    words = func.array_length(func.regexp_split_to_array(func.trim(Transcript.text), r"\s+"), 1)
    stmt = (
        _filtered(select(*cols).join(Session, Session.id == Transcript.session_id), f)
        .where(words >= SPEECH_MIN_WORDS)
        .order_by(dist)
    )
    rows = (await db.execute(stmt.limit(limit * 5 if baseline is not None else limit))).all()
    if baseline is None:
        return [Hit(r.session_id, r.start_ms, "speech", float(r.sim), r.text) for r in rows]
    hits = [Hit(r.session_id, r.start_ms, "speech", float(r.sim) - float(r.base), r.text) for r in rows]
    return sorted(hits, key=lambda h: -h.raw_score)[:limit]


async def keyword_hits(db: AsyncSession, q: str, f: Filters, limit: int) -> list[Hit]:
    tsq = func.websearch_to_tsquery("english", q)
    rank = func.ts_rank_cd(Transcript.text_tsv, tsq)
    stmt = (
        _filtered(
            select(Transcript.session_id, Transcript.start_ms, Transcript.text, rank.label("rank")).join(
                Session, Session.id == Transcript.session_id
            ),
            f,
        )
        .where(Transcript.text_tsv.op("@@")(tsq))
        .order_by(rank.desc())
        .limit(limit)
    )
    return [Hit(r.session_id, r.start_ms, "keyword", float(r.rank), r.text) for r in await db.execute(stmt)]


async def event_hits(db: AsyncSession, types: list[str], f: Filters, limit: int) -> list[Hit]:
    if not types:
        return []
    stmt = (
        _filtered(
            select(Event.session_id, Event.t_ms, Event.score, Event.type).join(Session, Session.id == Event.session_id), f
        )
        .where(Event.type.in_(types))
        .order_by(Event.score.desc())
        .limit(limit)
    )
    return [Hit(r.session_id, r.t_ms, "event", float(r.score), label=r.type) for r in await db.execute(stmt)]


# ---------------------------------------------------------------- resolution


@dataclass
class Resolved:
    """A search result before URLs are attached (so it can be cached)."""

    kind: str
    clip_id: uuid.UUID | None
    session_id: uuid.UUID
    match_t_ms: int
    start_ms: int
    end_ms: int
    score: float
    confidence: float
    signals: list[str]
    thumbnail_key: str | None
    transcript_snippet: str | None
    game: str | None
    title: str | None
    user: dict
    other_moments_ms: list[int]
    # Best moment first, then the others: {t_ms, confidence, signals, label, snippet, thumbnail_key}
    moments: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        d = self.__dict__.copy()
        d["clip_id"] = str(self.clip_id) if self.clip_id else None
        d["session_id"] = str(self.session_id)
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Resolved":
        d = dict(d)
        d["clip_id"] = uuid.UUID(d["clip_id"]) if d["clip_id"] else None
        d["session_id"] = uuid.UUID(d["session_id"])
        return cls(**d)


async def _nearest_thumb(db: AsyncSession, session_id: uuid.UUID, t: int) -> str | None:
    return await db.scalar(
        select(Frame.thumbnail_key)
        .where(Frame.session_id == session_id, Frame.thumbnail_key.is_not(None))
        .order_by(func.abs(Frame.t_ms - t))
        .limit(1)
    )


async def resolve(
    db: AsyncSession, hits: list[SessionHit], window_ms: int, include_unpublished: bool = False
) -> list[Resolved]:
    """Turn each session's moments into a result. Public search only resolves to published clips,
    so unpublished footage never leaks; owners also get drafts and suggested windows."""
    if not hits:
        return []
    session_ids = [h.best.session_id for h in hits]
    sessions = {
        r.Session.id: r
        for r in await db.execute(select(Session, User).join(User, User.id == Session.user_id).where(Session.id.in_(session_ids)))
    }
    out: list[Resolved] = []
    for h in hits:
        row = sessions.get(h.best.session_id)
        if row is None:
            continue
        s, u = row.Session, row.User
        candidates = [h.best, *h.others]
        clip, anchor = None, None
        for m in candidates:
            # Most specific visible clip containing the moment.
            stmt = (
                select(Clip)
                .where(Clip.session_id == s.id, Clip.status == "ready", Clip.start_ms <= m.t_ms, Clip.end_ms >= m.t_ms)
                .order_by((Clip.end_ms - Clip.start_ms).asc(), (Clip.kind == literal("auto")).asc())
                .limit(1)
            )
            if not include_unpublished:
                stmt = stmt.where(Clip.publish_state == "published")
            clip = await db.scalar(stmt)
            if clip is not None:
                anchor = m
                break
        if clip is None:
            if not include_unpublished:
                continue  # every match is in unpublished footage
            anchor = h.best
        ordered = [anchor, *[m for m in candidates if m is not anchor]]
        if clip is not None:
            # Other moments are only shown if they fall inside the same clip.
            ordered = [anchor, *[m for m in ordered[1:] if clip.start_ms <= m.t_ms <= clip.end_ms]]
        t = anchor.t_ms
        moments = []
        for m in ordered:
            moments.append(
                {
                    "t_ms": m.t_ms,
                    "confidence": m.confidence,
                    "signals": [sig for sig in SIGNALS if sig in m.signals],
                    "label": m.label,
                    "snippet": m.snippet,
                    "thumbnail_key": await _nearest_thumb(db, s.id, m.t_ms),
                }
            )
        thumb = moments[0]["thumbnail_key"]
        if clip is not None:
            kind, clip_id, start, end, title = "clip", clip.id, clip.start_ms, clip.end_ms, clip.title
        else:
            kind, clip_id, title = "session", None, s.title
            start, end = max(0, t - window_ms), min(s.duration_ms or t + window_ms, t + window_ms)
        out.append(
            Resolved(
                kind=kind,
                clip_id=clip_id,
                session_id=s.id,
                match_t_ms=t,
                start_ms=start,
                end_ms=end,
                score=round(anchor.score, 6),
                confidence=anchor.confidence,
                signals=moments[0]["signals"],
                thumbnail_key=thumb or (clip.thumbnail_key if clip else None) or s.poster_key,
                transcript_snippet=anchor.snippet,
                game=s.game,
                title=title,
                user={"id": str(u.id), "username": u.username, "avatar_url": u.avatar_url},
                other_moments_ms=[m.t_ms for m in ordered[1:]],
                moments=moments,
            )
        )
    return out


# ---------------------------------------------------------------- entry points


class SearchService:
    _baseline: list[float] | None = None  # generic-gameplay embedding, computed once per process
    _speech_baseline: list[float] | None = None  # generic-talking embedding

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], embedder: Embedder, settings: Settings, redis=None):
        self.sessionmaker = sessionmaker
        self.embedder = embedder
        self.settings = settings
        self.redis = redis

    async def _run(self, fn, *args) -> list[Hit]:
        async with self.sessionmaker() as db:
            return await fn(db, *args)

    def _thresholds(self, image: bool = False) -> Thresholds:
        st = self.settings
        if image:
            # Image-to-image similarity runs much higher than text-to-image.
            return Thresholds(visual=st.image_min_sim, speech=1.0, visual_full=st.image_full_sim, visual_relative=0)
        return Thresholds(
            visual=st.visual_min_score, speech=st.speech_min_score, visual_full=st.visual_full_score,
            speech_full=st.speech_full_score, speech_only=st.speech_only_min_score,
            visual_relative=st.visual_relative_cutoff,
        )

    async def _finish(self, hit_lists: dict[str, list[Hit]], limit: int, th: Thresholds, f: Filters) -> list[Resolved]:
        st = self.settings
        moments = fuse(drop_weak(hit_lists, th), st.rrf_k, st.moment_window_ms)
        for m in moments:
            m.confidence = confidence(m.strength, th)
        moments = rank_moments(drop_lone_weak_speech(moments, th))
        # Over-fetch: public search may skip sessions whose matches are all in unpublished footage.
        grouped = group_by_session(moments)[: limit * 2]
        async with self.sessionmaker() as db:
            return (await resolve(db, grouped, st.clip_window_ms, f.include_unpublished))[:limit]

    async def search_text(self, q: str, f: Filters, limit: int) -> tuple[list[Resolved], bool]:
        """Returns (results, served_from_cache)."""
        st = self.settings
        key = cache_key(q, f, limit)
        if self.redis is not None:
            try:
                if cached := await self.redis.get(key):
                    return [Resolved.from_json(d) for d in json.loads(cached)], True
            except Exception:  # noqa: BLE001 - cache is optional
                log.warning("search cache read failed", exc_info=True)

        t0 = time.monotonic()
        nq = normalize_query(q)
        texts = [nq] + [t.format(nq) for t in VISUAL_TEMPLATES[1:]]
        need_baselines = self._baseline is None or self._speech_baseline is None
        if need_baselines:
            texts += list(VISUAL_BASELINE_PROMPTS) + list(SPEECH_BASELINE_PROMPTS)
        vecs = await asyncio.to_thread(self.embedder.embed_texts, texts)
        vec = vecs[0]  # plain query: best for transcript (text-to-text) matching
        visual_vec = mean_unit(vecs[: len(VISUAL_TEMPLATES)])
        if need_baselines:
            i = len(VISUAL_TEMPLATES)
            SearchService._baseline = mean_unit(vecs[i : i + len(VISUAL_BASELINE_PROMPTS)])
            SearchService._speech_baseline = mean_unit(vecs[i + len(VISUAL_BASELINE_PROMPTS) :])
        n = st.search_signal_limit
        results = await asyncio.gather(
            self._run(visual_hits, visual_vec, f, n, self._baseline),
            self._run(speech_hits, vec, f, n, self._speech_baseline),
            self._run(keyword_hits, q, f, n),
            self._run(event_hits, event_types_for(q), f, n),
        )
        hit_lists = dict(zip(SIGNALS, results, strict=True))
        resolved = await self._finish(hit_lists, limit, self._thresholds(), f)
        log.info(
            "search",
            extra={"q": q, "hits": {k: len(v) for k, v in hit_lists.items()}, "results": len(resolved), "ms": round((time.monotonic() - t0) * 1000)},
        )
        if self.redis is not None:
            try:
                await self.redis.set(key, json.dumps([r.to_json() for r in resolved]), ex=st.search_cache_ttl_s)
            except Exception:  # noqa: BLE001
                log.warning("search cache write failed", exc_info=True)
        return resolved, False

    async def search_image(self, image: bytes, f: Filters, limit: int) -> list[Resolved]:
        vec = (await asyncio.to_thread(self.embedder.embed_images, [image]))[0]
        hits = await self._run(visual_hits, vec, f, self.settings.search_signal_limit)
        return await self._finish({"visual": hits}, limit, self._thresholds(image=True), f)
