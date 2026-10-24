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

from sqlalchemy import Select, func, literal, select
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


@dataclass
class Filters:
    game: str | None = None
    user_id: uuid.UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


@dataclass
class Hit:
    session_id: uuid.UUID
    t_ms: int
    signal: str
    raw_score: float
    snippet: str | None = None


@dataclass
class Moment:
    session_id: uuid.UUID
    t_ms: int
    score: float
    signals: set[str] = field(default_factory=set)
    snippet: str | None = None


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
            if h.snippet and m.snippet is None:
                m.snippet = h.snippet

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
        [normalize_query(q), (f.game or "").lower(), str(f.user_id or ""), str(f.date_from or ""), str(f.date_to or ""), limit]
    )
    return "search:v1:" + hashlib.sha1(payload.encode()).hexdigest()


# ---------------------------------------------------------------- signal queries


def _filtered(stmt: Select, f: Filters) -> Select:
    stmt = stmt.where(Session.status == SessionStatus.READY)
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


async def visual_hits(db: AsyncSession, vec: list[float], f: Filters, limit: int) -> list[Hit]:
    dist = Frame.embedding.cosine_distance(vec)
    stmt = _filtered(
        select(Frame.session_id, Frame.t_ms, (1 - dist).label("sim")).join(Session, Session.id == Frame.session_id), f
    ).order_by(dist).limit(limit)
    return [Hit(r.session_id, r.t_ms, "visual", float(r.sim)) for r in await db.execute(stmt)]


async def speech_hits(db: AsyncSession, vec: list[float], f: Filters, limit: int) -> list[Hit]:
    dist = Transcript.embedding.cosine_distance(vec)
    stmt = _filtered(
        select(Transcript.session_id, Transcript.start_ms, Transcript.text, (1 - dist).label("sim")).join(
            Session, Session.id == Transcript.session_id
        ),
        f,
    ).order_by(dist).limit(limit)
    return [Hit(r.session_id, r.start_ms, "speech", float(r.sim), r.text) for r in await db.execute(stmt)]


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
        _filtered(select(Event.session_id, Event.t_ms, Event.score).join(Session, Session.id == Event.session_id), f)
        .where(Event.type.in_(types))
        .order_by(Event.score.desc())
        .limit(limit)
    )
    return [Hit(r.session_id, r.t_ms, "event", float(r.score)) for r in await db.execute(stmt)]


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
    signals: list[str]
    thumbnail_key: str | None
    transcript_snippet: str | None
    game: str | None
    title: str | None
    user: dict
    other_moments_ms: list[int]

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


async def resolve(db: AsyncSession, hits: list[SessionHit], window_ms: int) -> list[Resolved]:
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
        t = h.best.t_ms
        # Most specific clip containing the moment.
        clip = await db.scalar(
            select(Clip)
            .where(Clip.session_id == s.id, Clip.status == "ready", Clip.start_ms <= t, Clip.end_ms >= t)
            .order_by((Clip.end_ms - Clip.start_ms).asc(), (Clip.kind == literal("auto")).asc())
            .limit(1)
        )
        thumb = await db.scalar(
            select(Frame.thumbnail_key)
            .where(Frame.session_id == s.id, Frame.thumbnail_key.is_not(None))
            .order_by(func.abs(Frame.t_ms - t))
            .limit(1)
        )
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
                score=round(h.best.score, 6),
                signals=[sig for sig in SIGNALS if sig in h.best.signals],
                thumbnail_key=thumb or (clip.thumbnail_key if clip else None) or s.poster_key,
                transcript_snippet=h.best.snippet,
                game=s.game,
                title=title,
                user={"id": str(u.id), "username": u.username, "avatar_url": u.avatar_url},
                other_moments_ms=[m.t_ms for m in h.others],
            )
        )
    return out


# ---------------------------------------------------------------- entry points


class SearchService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], embedder: Embedder, settings: Settings, redis=None):
        self.sessionmaker = sessionmaker
        self.embedder = embedder
        self.settings = settings
        self.redis = redis

    async def _run(self, fn, *args) -> list[Hit]:
        async with self.sessionmaker() as db:
            return await fn(db, *args)

    async def _finish(self, hit_lists: dict[str, list[Hit]], limit: int) -> list[Resolved]:
        st = self.settings
        moments = fuse(hit_lists, st.rrf_k, st.moment_window_ms)
        grouped = group_by_session(moments)[:limit]
        async with self.sessionmaker() as db:
            return await resolve(db, grouped, st.clip_window_ms)

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
        vec = (await asyncio.to_thread(self.embedder.embed_texts, [normalize_query(q)]))[0]
        n = st.search_signal_limit
        results = await asyncio.gather(
            self._run(visual_hits, vec, f, n),
            self._run(speech_hits, vec, f, n),
            self._run(keyword_hits, q, f, n),
            self._run(event_hits, event_types_for(q), f, n),
        )
        hit_lists = dict(zip(SIGNALS, results, strict=True))
        resolved = await self._finish(hit_lists, limit)
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
        return await self._finish({"visual": hits}, limit)
