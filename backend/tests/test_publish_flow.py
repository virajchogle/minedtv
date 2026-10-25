"""Publishing starts the YouTube virality check; virality works on any state you own."""

import uuid

import pytest
from fastapi import HTTPException

from app.api import clips as clips_api
from app.config import get_settings
from app.db.models import Clip, Session, SessionStatus, User
from app.schemas import ClipHighlightsIn, ClipViralityIn
from tests.test_pipeline_e2e import migrated_db, sessionmaker  # noqa: F401  (fixtures)


class _Urls:
    def clip_playlist(self, clip_id):
        return f"http://api.test/clips/{clip_id}/playlist.m3u8"


async def _draft_clip(sm) -> tuple[User, Clip]:
    async with sm() as db:
        owner = User(username=f"owner_{uuid.uuid4().hex[:6]}")
        db.add(owner)
        await db.flush()
        sid = uuid.uuid4()
        db.add(Session(id=sid, user_id=owner.id, storage_prefix=f"sessions/{sid}", source_key="x",
                       status=SessionStatus.READY, duration_ms=10_000))
        await db.flush()
        clip = Clip(session_id=sid, user_id=owner.id, start_ms=0, end_ms=10_000, publish_state="draft", status="ready")
        db.add(clip)
        await db.commit()
        return owner, clip


@pytest.fixture
def started(monkeypatch):
    calls: list[tuple[uuid.UUID, ClipViralityIn]] = []

    async def fake_start(clip, body):
        calls.append((clip.id, body))

    monkeypatch.setattr(clips_api, "_start_virality", fake_start)
    s = get_settings().model_copy(update={"gemini_api_key": "test-key"})
    monkeypatch.setattr(clips_api, "get_settings", lambda: s)
    return calls


async def test_publish_starts_youtube_virality(sessionmaker, started):  # noqa: F811
    owner, clip = await _draft_clip(sessionmaker)
    async with sessionmaker() as db:
        out = await clips_api.publish_clip(clip.id, owner, db, _Urls())
    assert out.publish_state == "published" and out.published_at is not None
    assert [(cid, body.platform) for cid, body in started] == [(clip.id, "youtube")]

    async with sessionmaker() as db:
        out = await clips_api.unpublish_clip(clip.id, owner, db, _Urls())
    assert out.publish_state == "draft" and len(started) == 1  # unpublishing starts nothing


async def test_virality_any_state_but_owner_only(sessionmaker, started):  # noqa: F811
    owner, clip = await _draft_clip(sessionmaker)
    async with sessionmaker() as db:
        await clips_api.publish_clip(clip.id, owner, db, _Urls())
        # Published clips can be checked by hand too (it used to be drafts only).
        await clips_api.start_virality(clip.id, ClipViralityIn(platform="tiktok"), owner, db)
        stranger = User(username=f"x_{uuid.uuid4().hex[:6]}")
        db.add(stranger)
        await db.commit()
        with pytest.raises(HTTPException) as e:
            await clips_api.start_virality(clip.id, ClipViralityIn(platform="tiktok"), stranger, db)
        assert e.value.status_code == 403
    assert [body.platform for _, body in started] == ["youtube", "tiktok"]


def test_default_persona_count_shares_one_result():
    clip = Clip(id=uuid.uuid4(), start_ms=0, end_ms=1000)
    default = get_settings().creator_persona_count
    assert clips_api._virality_args(clip, ClipViralityIn(platform="youtube")) == clips_api._virality_args(
        clip, ClipViralityIn(platform="youtube", persona_count=default)
    )


async def test_creator_tools_are_owner_only(sessionmaker):  # noqa: F811
    owner, clip = await _draft_clip(sessionmaker)
    async with sessionmaker() as db:
        stranger = User(username=f"x_{uuid.uuid4().hex[:6]}")
        db.add(stranger)
        await db.commit()
        for call in (clips_api.get_creator_pack, clips_api.start_creator_pack, clips_api.get_export, clips_api.start_export):
            with pytest.raises(HTTPException) as e:
                await call(clip.id, stranger, db)
            assert e.value.status_code == 403, call.__name__
        assert (await clips_api.get_creator_pack(clip.id, owner, db)).status == "none"
        assert (await clips_api.get_export(clip.id, owner, db)).status == "none"


async def test_stored_highlights_are_owner_only(sessionmaker):  # noqa: F811
    owner, clip = await _draft_clip(sessionmaker)
    async with sessionmaker() as db:
        stranger = User(username=f"x_{uuid.uuid4().hex[:6]}")
        db.add(stranger)
        await db.commit()
        with pytest.raises(HTTPException) as get_error:
            await clips_api.get_clip_highlights(clip.id, stranger, db)
        assert get_error.value.status_code == 403
        with pytest.raises(HTTPException) as post_error:
            await clips_api.start_clip_highlights(clip.id, ClipHighlightsIn(), stranger, db)
        assert post_error.value.status_code == 403
