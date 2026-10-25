"""Shorts / Reels: clip shape on responses, format-filtered and ranked feeds, reel uploads, and
vertical (incl. phone-rotated) video staying vertical through processing."""

import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import feed as feed_api
from app.api import uploads as uploads_api
from app.api import users as users_api
from app.db.models import Clip, Frame, FrameViralityScore, Segment, Session, SessionStatus, User
from app.schemas import UploadCreate
from app.services.formats import clip_format
from app.services.search import Filters, SearchService
from app.services.storage import LocalStorage
from app.worker import media
from app.worker.pipeline import run_pipeline
from app.config import get_settings
from app.ml.stubs import StubEmbedder
from tests.test_pipeline_e2e import (  # noqa: F401  (fixtures)
    FakeDetector,
    _deps,
    migrated_db,
    sessionmaker,
)


def _feed(db, *, cursor=None, limit=20, format=None, sort="new"):
    # Calling the route directly: pass every parameter, or FastAPI's Query() defaults leak in.
    return feed_api.feed(db, _Urls(), None, cursor=cursor, limit=limit, game=None, format=format, sort=sort)


class _Urls:
    def clip_playlist(self, clip_id):
        return f"http://api.test/clips/{clip_id}/playlist.m3u8"


def test_format_rule():
    assert clip_format(720, 1280, 22_000) == "short"
    assert clip_format(720, 1280, 60_000) == "short"
    assert clip_format(720, 1280, 61_000) == "long"  # vertical but too long
    assert clip_format(1280, 720, 10_000) == "long"
    assert clip_format(720, 720, 10_000) == "long"  # square isn't vertical
    assert clip_format(None, None, 10_000) == "long"  # not probed yet


async def _clip(db, owner: User, size: tuple[int, int], duration_ms: int, **kw) -> Clip:
    sid = uuid.uuid4()
    db.add(Session(id=sid, user_id=owner.id, storage_prefix=f"sessions/{sid}", source_key="x",
                   status=SessionStatus.READY, duration_ms=duration_ms, width=size[0], height=size[1]))
    await db.flush()
    clip = Clip(session_id=sid, user_id=owner.id, start_ms=0, end_ms=duration_ms, status="ready",
                publish_state=kw.pop("publish_state", "published"), **kw)
    db.add(clip)
    await db.flush()
    return clip


async def test_feeds_filter_by_format_before_paging(sessionmaker):  # noqa: F811
    async with sessionmaker() as db:
        owner = User(username=f"o_{uuid.uuid4().hex[:6]}")
        db.add(owner)
        await db.flush()
        shorts = [await _clip(db, owner, (720, 1280), 20_000) for _ in range(3)]
        longs = [await _clip(db, owner, (1920, 1080), 20_000) for _ in range(3)]
        tall_but_long = await _clip(db, owner, (1080, 1920), 120_000)
        await db.commit()

        page1 = await _feed(db, limit=2, format="short")
        assert len(page1.items) == 2 and page1.next_cursor  # full page, not thinned by a post-filter
        page2 = await _feed(db, cursor=page1.next_cursor, limit=2, format="short")
        assert {c.id for c in page1.items + page2.items} == {c.id for c in shorts} and page2.next_cursor is None
        assert all(c.format == "short" and (c.width, c.height) == (720, 1280) for c in page1.items)

        long_ids = {c.id for c in (await _feed(db, format="long")).items}
        assert long_ids == {c.id for c in longs} | {tall_but_long.id}
        assert len((await _feed(db)).items) == 7  # no format = everything, as before

        mine = await users_api.user_clips(
            owner.id, db, _Urls(), owner, cursor=None, limit=20, state="all", format="short", sort="new"
        )
        assert {c.id for c in mine.items} == {c.id for c in shorts}


async def test_top_sort_ranks_by_engagement_and_virality(sessionmaker):  # noqa: F811
    async with sessionmaker() as db:
        owner = User(username=f"o_{uuid.uuid4().hex[:6]}")
        db.add(owner)
        await db.flush()
        quiet = await _clip(db, owner, (720, 1280), 20_000)
        liked = await _clip(db, owner, (720, 1280), 20_000, like_count=40)
        viral = await _clip(db, owner, (720, 1280), 20_000)
        frame = Frame(session_id=viral.session_id, t_ms=5000)
        db.add(frame)
        await db.flush()
        db.add(FrameViralityScore(session_id=viral.session_id, frame_id=frame.id, t_ms=5000, score=0.95,
                                  visual_score=0.9, novelty_score=0.5, event_score=0, speech_score=0,
                                  visibility_score=1, scene_score=0.9))
        await db.commit()

        first = await _feed(db, limit=2, format="short", sort="top")
        assert [c.id for c in first.items] == [liked.id, viral.id] and first.next_cursor
        rest = await _feed(db, limit=2, cursor=first.next_cursor, format="short", sort="top")
        assert [c.id for c in rest.items] == [quiet.id] and rest.next_cursor is None

        with pytest.raises(HTTPException):  # a newest-first cursor isn't a ranked one
            await _feed(db, cursor="bm90LWEtY3Vyc29y", sort="top")


async def test_reel_upload_credits_its_source(sessionmaker, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(uploads_api, "get_storage", lambda: LocalStorage(tmp_path / "s"))
    async with sessionmaker() as db:
        me, other = User(username=f"me_{uuid.uuid4().hex[:6]}"), User(username=f"x_{uuid.uuid4().hex[:6]}")
        db.add_all([me, other])
        await db.flush()
        source = await _clip(db, me, (1920, 1080), 90_000)
        private = await _clip(db, other, (1920, 1080), 90_000, publish_state="draft")
        await db.commit()

        out = await uploads_api.create_upload(UploadCreate(filename="reel.mp4", reel_of=source.id), me, db)
        s = await db.get(Session, out.session_id)
        assert s.is_reel and s.reel_of_clip_id == source.id

        with pytest.raises(HTTPException) as e:  # someone else's private clip stays hidden
            await uploads_api.create_upload(UploadCreate(filename="r.mp4", reel_of=private.id), me, db)
        assert e.value.status_code == 404


@pytest.fixture(scope="module")
def phone_video(tmp_path_factory) -> Path:
    """A 6 s portrait phone recording: stored landscape (1280x720) with a 90° rotation flag."""
    d = tmp_path_factory.mktemp("phone")
    flat = d / "flat.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", "-shortest", str(flat)],
        check=True,
    )
    out = d / "phone.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-display_rotation", "90", "-i", str(flat), "-c", "copy", str(out)],
                   check=True)
    return out


async def test_rotated_phone_reel_stays_vertical_and_whole(sessionmaker, phone_video, tmp_path):  # noqa: F811
    storage = LocalStorage(tmp_path / "storage")
    async with sessionmaker() as db:
        user = User(username=f"r_{uuid.uuid4().hex[:6]}")
        db.add(user)
        await db.flush()
        sid = uuid.uuid4()
        prefix = f"sessions/{sid}"
        db.add(Session(id=sid, user_id=user.id, title="My reel", storage_prefix=prefix, source_key=f"{prefix}/source.mp4",
                       status=SessionStatus.QUEUED, is_reel=True))
        await db.commit()
    storage.put_file(f"{prefix}/source.mp4", phone_video)

    assert await run_pipeline(sid, deps=_deps(sessionmaker, storage, FakeDetector())) == SessionStatus.READY

    async with sessionmaker() as db:
        s = await db.get(Session, sid)
        assert (s.width, s.height) == (720, 1280)  # display size, not the stored 1280x720
        clips = (await db.scalars(select(Clip).where(Clip.session_id == sid))).all()
        # Not cut into highlights despite the detector's events: one clip, the whole reel.
        assert [(c.start_ms, c.end_ms) for c in clips] == [(0, s.duration_ms)]
        assert clip_format(s.width, s.height, clips[0].end_ms - clips[0].start_ms) == "short"
        seg = await db.scalar(select(Segment).where(Segment.session_id == sid).limit(1))
        p = media.probe(storage.root / seg.storage_key)
        assert (p.width, p.height) == (720, 1280)  # the HLS rendition is vertical at full 720p width

        await db.execute(Clip.__table__.update().where(Clip.session_id == sid).values(publish_state="published"))
        await db.commit()

    # Stub vectors are noise, so only the keyword signal matches (the transcript line at 1–6 s).
    st = get_settings().model_copy(update={"visual_min_score": 1.0, "speech_min_score": 1.0})
    search = SearchService(sessionmaker, StubEmbedder(), st, redis=None)
    shorts, _ = await search.search_text("rotate to B", Filters(fmt="short"), 10)
    longs, _ = await search.search_text("rotate to B", Filters(fmt="long"), 10)
    assert [r.session_id for r in shorts] == [sid] and shorts[0].format == "short" and shorts[0].height == 1280
    assert longs == []
