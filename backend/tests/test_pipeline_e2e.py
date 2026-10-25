"""Full pipeline against real Postgres + pgvector and ffmpeg, with stub/fake models.

Needs the compose Postgres (`docker-compose up -d postgres`) and ffmpeg on PATH; skips otherwise.
Uses a separate database (minedtv_test) and local-disk storage.
"""

import asyncio
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import (
    Clip,
    Event,
    Frame,
    FrameHighlightRun,
    FrameViralityScore,
    Segment,
    Session,
    SessionStatus,
    Transcript,
    User,
)
from app.ml.interfaces import DetectedEvent, TranscriptChunk
from app.ml.stubs import StubEmbedder
from app.services.playlist import build_playlist
from app.services.search import Filters, SearchService
from app.services.storage import LocalStorage
from app.worker.pipeline import Deps, run_pipeline

BASE_URL = os.environ.get("TEST_DATABASE_ADMIN_URL", "postgresql+asyncpg://minedtv:minedtv@localhost:5432/minedtv")
TEST_DB = "minedtv_test"
TEST_URL = BASE_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
ROOT = Path(__file__).resolve().parents[1]
VIDEO_S = 20

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


async def _create_db() -> None:
    import asyncpg

    conn = await asyncpg.connect(BASE_URL.replace("+asyncpg", ""), timeout=3)
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB):
            await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def migrated_db():
    try:
        asyncio.run(_create_db())
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable ({e}); run docker-compose up -d postgres")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "app/db/migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_URL)
    command.upgrade(cfg, "head")
    return TEST_URL


@pytest.fixture
async def sessionmaker(migrated_db):
    engine = create_async_engine(migrated_db)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture(scope="session")
def video(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("media") / "game.mp4"
    subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={VIDEO_S}",
            "-f", "lavfi", "-i", f"sine=frequency=300:duration={VIDEO_S}",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(out),
        ],
        check=True,
    )
    return out


class FakeTranscriber:
    def transcribe(self, audio_path: str) -> list[TranscriptChunk]:
        assert Path(audio_path).stat().st_size > 0
        return [
            TranscriptChunk(1000, 3000, "okay rotate to B"),
            TranscriptChunk(3000, 6000, "he's one shot, he's one shot"),
            TranscriptChunk(14_000, 17_000, "NO WAY that clutch was insane", "friend"),
        ]


class FakeDetector:
    def detect(self, video_path: str, session_id: str) -> list[DetectedEvent]:
        return [DetectedEvent(4000, "kill", 0.6, {"weapon": "vandal"}), DetectedEvent(15_000, "clutch", 0.95)]


class BrokenDetector:
    def detect(self, video_path: str, session_id: str):
        raise RuntimeError("model exploded")


def _deps(sm, storage, detector, auto_frame_highlights: bool = False) -> Deps:
    # Most tests check the pipeline's own steps, so the frame scorer's automatic run is off
    # unless a test asks for it.
    settings = get_settings().model_copy(
        update={"clip_window_ms": 3000, "auto_frame_highlights": auto_frame_highlights}
    )
    return Deps(storage, StubEmbedder(), FakeTranscriber(), detector, sm, settings)


async def _new_session(sm, storage, video) -> uuid.UUID:
    async with sm() as db:
        user = User(username=f"tester_{uuid.uuid4().hex[:6]}")
        db.add(user)
        await db.flush()
        sid = uuid.uuid4()
        prefix = f"sessions/{sid}"
        db.add(Session(id=sid, user_id=user.id, game="Valorant", title="Bind ranked", storage_prefix=prefix,
                       source_key=f"{prefix}/source.mp4", status=SessionStatus.QUEUED))
        await db.commit()
    storage.put_file(f"{prefix}/source.mp4", video)
    return sid


async def test_pipeline_end_to_end(sessionmaker, video, tmp_path):
    storage = LocalStorage(tmp_path / "storage")
    sid = await _new_session(sessionmaker, storage, video)

    assert await run_pipeline(sid, deps=_deps(sessionmaker, storage, FakeDetector())) == SessionStatus.READY

    async with sessionmaker() as db:
        s = await db.get(Session, sid)
        assert (s.status, s.last_step, s.error) == ("ready", "finalize", None)
        assert s.duration_ms == VIDEO_S * 1000
        assert (s.width, s.height, s.has_audio) == (1280, 720, True)
        assert storage.exists(s.poster_key)

        segs = (await db.scalars(select(Segment).where(Segment.session_id == sid).order_by(Segment.idx))).all()
        assert len(segs) == VIDEO_S // 2
        assert all(a.start_ms + a.duration_ms == b.start_ms for a, b in zip(segs, segs[1:]))
        assert all(storage.exists(sg.storage_key) and len(sg.content_hash) == 64 for sg in segs)

        n_frames = await db.scalar(select(func.count()).select_from(Frame).where(Frame.session_id == sid))
        assert n_frames == VIDEO_S

        lines = (await db.scalars(select(Transcript).where(Transcript.session_id == sid).order_by(Transcript.start_ms))).all()
        assert [t.text for t in lines] == ["okay rotate to B he's one shot, he's one shot", "NO WAY that clutch was insane"]
        assert lines[1].speaker == "friend"

        events = (await db.scalars(select(Event).where(Event.session_id == sid))).all()
        assert {(e.type, e.source) for e in events} == {("kill", "FakeDetector"), ("clutch", "FakeDetector")}

        clips = (await db.scalars(select(Clip).where(Clip.session_id == sid).order_by(Clip.start_ms))).all()
        assert [(c.start_ms, c.end_ms, c.kind) for c in clips] == [(1000, 7000, "auto"), (12_000, 18_000, "auto")]
        assert all(c.thumbnail_key and "/frames/" in c.thumbnail_key for c in clips)

    body = build_playlist(segs, clips[1].start_ms, clips[1].end_ms, storage.url_for)
    assert body.count("#EXTINF") == 3 and "#EXT-X-MEDIA-SEQUENCE:6" in body

    # Stub vectors are random, so any visual "match" is noise; this checks speech/keyword/event fusion.
    search = SearchService(sessionmaker, StubEmbedder(), get_settings().model_copy(update={"visual_min_score": 1.0, "speech_min_score": 1.0}), redis=None)
    # New auto clips are drafts: invisible to public search, visible when the owner searches their own clips.
    assert all(c.publish_state == "draft" for c in clips)
    hidden, _ = await search.search_text("the clutch", Filters(game="valorant"), 10)
    assert hidden == []
    own, _ = await search.search_text("the clutch", Filters(game="valorant", include_unpublished=True), 10)
    assert len(own) == 1 and own[0].clip_id == clips[1].id

    async with sessionmaker() as db:
        await db.execute(update(Clip).where(Clip.id == clips[1].id).values(publish_state="published"))
        await db.commit()
    results, cached = await search.search_text("the clutch", Filters(game="valorant"), 10)
    assert not cached and len(results) == 1
    r = results[0]
    assert r.kind == "clip" and r.clip_id == clips[1].id
    assert {"keyword", "event"} <= set(r.signals)
    assert r.match_t_ms in range(14_000, 15_001)
    assert r.transcript_snippet == "NO WAY that clutch was insane"

    none, _ = await search.search_text("the clutch", Filters(game="Fortnite"), 10)
    assert none == []

    # Rerunning is idempotent: same row counts, user clips untouched.
    async with sessionmaker() as db:
        s = await db.get(Session, sid)
        db.add(Clip(session_id=sid, user_id=s.user_id, start_ms=0, end_ms=5000, kind="user", status="ready"))
        await db.commit()
    assert await run_pipeline(sid, deps=_deps(sessionmaker, storage, FakeDetector())) == SessionStatus.READY
    async with sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(Segment).where(Segment.session_id == sid)) == VIDEO_S // 2
        assert await db.scalar(select(func.count()).select_from(Frame).where(Frame.session_id == sid)) == VIDEO_S
        kinds = (await db.scalars(select(Clip.kind).where(Clip.session_id == sid))).all()
        assert sorted(kinds) == ["auto", "auto", "user"]
        # The uploader heard once that it's ready, even though it was processed twice.
        from app.db.models import Notification

        notes = (await db.scalars(select(Notification).where(Notification.session_id == sid))).all()
        assert [n.type for n in notes] == ["upload_ready"]
        assert len(notes[0].data["clip_ids"]) == 2 and notes[0].user_id == s.user_id


async def test_failed_step_resumes(sessionmaker, video, tmp_path):
    storage = LocalStorage(tmp_path / "storage")
    sid = await _new_session(sessionmaker, storage, video)

    assert await run_pipeline(sid, deps=_deps(sessionmaker, storage, BrokenDetector())) == SessionStatus.FAILED
    async with sessionmaker() as db:
        s = await db.get(Session, sid)
        assert (s.status, s.failed_step, s.last_step) == ("failed", "highlights", "moderate")
        assert "model exploded" in s.error
        seg_ids = set((await db.scalars(select(Segment.id).where(Segment.session_id == sid))).all())

    assert await run_pipeline(sid, resume=True, deps=_deps(sessionmaker, storage, FakeDetector())) == SessionStatus.READY
    async with sessionmaker() as db:
        s = await db.get(Session, sid)
        assert (s.status, s.failed_step, s.error) == ("ready", None, None)
        # Earlier steps were not redone.
        assert set((await db.scalars(select(Segment.id).where(Segment.session_id == sid))).all()) == seg_ids
        assert await db.scalar(select(func.count()).select_from(Event).where(Event.session_id == sid)) == 2


async def test_export_renders_exact_clip_mp4(sessionmaker, video, tmp_path):
    from app.worker.export import export_clip, export_key

    storage = LocalStorage(tmp_path / "storage")
    sid = await _new_session(sessionmaker, storage, video)
    assert await run_pipeline(sid, deps=_deps(sessionmaker, storage, FakeDetector())) == SessionStatus.READY
    async with sessionmaker() as db:
        s = await db.get(Session, sid)
        # Deliberately not on a segment boundary.
        clip = Clip(session_id=sid, user_id=s.user_id, start_ms=3_500, end_ms=9_250, kind="user", status="ready")
        db.add(clip)
        await db.commit()

    key = await export_clip(clip.id, _deps(sessionmaker, storage, FakeDetector()))
    assert key == export_key(clip.id, 3_500, 9_250) and storage.exists(key)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name", "-of", "json", str(storage._path(key))],
        capture_output=True, text=True, check=True,
    ).stdout
    import json

    info = json.loads(probe)
    assert abs(float(info["format"]["duration"]) - 5.75) < 0.15
    assert {s["codec_name"] for s in info["streams"]} == {"h264", "aac"}
    # Second call reuses the finished file.
    assert await export_clip(clip.id, _deps(sessionmaker, storage, FakeDetector())) == key


async def test_creator_pack_for_existing_clip(sessionmaker, video, tmp_path):
    import json as _json

    from app.worker.creator_pack import build_creator_pack, pack_key
    from tests.test_creator_pack import engine_factory

    storage = LocalStorage(tmp_path / "storage")
    sid = await _new_session(sessionmaker, storage, video)
    assert await run_pipeline(sid, deps=_deps(sessionmaker, storage, FakeDetector())) == SessionStatus.READY
    async with sessionmaker() as db:
        clip = (await db.scalars(select(Clip).where(Clip.session_id == sid).order_by(Clip.start_ms))).first()

    calls: list[str] = []
    deps = _deps(sessionmaker, storage, FakeDetector())
    deps.settings = deps.settings.model_copy(update={"gemini_model": "busy-model", "gemini_fallback_models": ["ok-model"]})
    key = await build_creator_pack(clip.id, deps, engine_factory=engine_factory({"busy-model": Exception("503 high demand")}, calls))
    assert key == pack_key(clip.id, clip.start_ms, clip.end_ms)
    body = _json.loads(storage.get_bytes(key))
    assert body["model"] == "ok-model" and body["pack"]["youtube"]["title"] == "t"
    assert calls == ["busy-model", "ok-model"]
    # The MP4 export was produced on the way and is reused; a second call reuses the pack.
    assert await build_creator_pack(clip.id, deps, engine_factory=engine_factory({}, calls)) == key
    assert calls == ["busy-model", "ok-model"]


async def test_frame_virality_reuses_pipeline_frames_and_creates_clips(sessionmaker, video, tmp_path):
    from app.services.frame_virality import ALGORITHM_VERSION
    from app.worker.frame_highlights import run_frame_highlights

    storage = LocalStorage(tmp_path / "storage")
    sid = await _new_session(sessionmaker, storage, video)
    deps = _deps(sessionmaker, storage, FakeDetector())
    deps.settings = deps.settings.model_copy(
        update={"frame_highlight_count": 2, "frame_highlight_duration_ms": 4000}
    )
    assert await run_pipeline(sid, deps=deps) == SessionStatus.READY

    assert await run_frame_highlights(sid, deps) == str(sid)
    async with sessionmaker() as db:
        run = await db.get(FrameHighlightRun, sid)
        assert (run.status, run.algorithm_version) == ("ready", ALGORITHM_VERSION)
        scores = (
            await db.scalars(
                select(FrameViralityScore)
                .where(FrameViralityScore.session_id == sid)
                .order_by(FrameViralityScore.t_ms)
            )
        ).all()
        assert len(scores) == VIDEO_S
        assert 1 <= sum(score.selected for score in scores) <= 2
        clips = (
            await db.scalars(
                select(Clip).where(Clip.session_id == sid, Clip.generation_source == "frame_virality")
            )
        ).all()
        assert len(clips) == sum(score.selected for score in scores)
        assert await db.scalar(
            select(func.count()).select_from(Clip).where(
                Clip.session_id == sid, Clip.generation_source == "pipeline"
            )
        ) == 2
        assert all(clip.end_ms - clip.start_ms == 4000 for clip in clips)
        assert all(clip.publish_state == "draft" for clip in clips)
        assert await db.scalar(
            select(func.count()).select_from(Event).where(
                Event.session_id == sid, Event.source == "FrameViralityScorer"
            )
        ) == len(clips)

    # Re-running replaces the generated rows rather than duplicating them.
    assert await run_frame_highlights(sid, deps) == str(sid)
    async with sessionmaker() as db:
        assert await db.scalar(
            select(func.count()).select_from(FrameViralityScore).where(
                FrameViralityScore.session_id == sid
            )
        ) == VIDEO_S
        assert await db.scalar(
            select(func.count()).select_from(Clip).where(Clip.session_id == sid, Clip.kind == "auto")
        ) >= 1
        assert await db.scalar(
            select(func.count()).select_from(Clip).where(
                Clip.session_id == sid, Clip.generation_source == "frame_virality"
            )
        ) <= 2


async def test_uploads_get_frame_highlight_clips_automatically(sessionmaker, video, tmp_path):
    from app.db.models import Notification

    storage = LocalStorage(tmp_path / "storage")
    sid = await _new_session(sessionmaker, storage, video)
    deps = _deps(sessionmaker, storage, FakeDetector(), auto_frame_highlights=True)
    deps.settings = deps.settings.model_copy(update={"frame_highlight_count": 2, "frame_highlight_duration_ms": 4000})
    assert await run_pipeline(sid, deps=deps) == SessionStatus.READY

    async with sessionmaker() as db:
        sources = (await db.scalars(select(Clip.generation_source).where(Clip.session_id == sid))).all()
        # The frame scorer's clips replaced the event-based ones.
        assert sources and set(sources) == {"frame_virality"}
        clip_ids = set((await db.scalars(select(Clip.id).where(Clip.session_id == sid))).all())
        note = await db.scalar(select(Notification).where(Notification.session_id == sid, Notification.type == "upload_ready"))
        assert note is not None and note.clip_id in clip_ids  # survived the swap, points at a new clip
        assert await db.scalar(select(func.count()).select_from(FrameViralityScore).where(FrameViralityScore.session_id == sid)) == VIDEO_S
