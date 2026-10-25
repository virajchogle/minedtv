"""Publishing, frame-score virality on clips, and owner-only creator tools."""

import uuid

import pytest
from fastapi import HTTPException

from app.api import clips as clips_api
from app.db.models import Clip, Frame, FrameViralityScore, Session, SessionStatus, User
from app.schemas import ClipHighlightsIn
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


async def _score_frames(sm, clip: Clip, scores: list[tuple[int, float]]) -> None:
    """Frame scores like the frame scorer writes: (t_ms, combined score)."""
    async with sm() as db:
        for t, score in scores:
            frame = Frame(session_id=clip.session_id, t_ms=t)
            db.add(frame)
            await db.flush()
            db.add(FrameViralityScore(
                session_id=clip.session_id, frame_id=frame.id, t_ms=t, score=score, visual_score=score,
                novelty_score=0.5, event_score=0.0, speech_score=0.2, visibility_score=0.9, scene_score=score,
            ))
        await db.commit()


async def test_publish_no_longer_runs_a_job(sessionmaker, monkeypatch):  # noqa: F811
    queued = []
    monkeypatch.setattr(clips_api, "enqueue_frame_highlights", lambda *a: queued.append(a))
    owner, clip = await _draft_clip(sessionmaker)
    async with sessionmaker() as db:
        out = await clips_api.publish_clip(clip.id, owner, db, _Urls())
    assert out.publish_state == "published" and out.published_at is not None and queued == []


async def test_clip_virality_from_frame_scores(sessionmaker, monkeypatch):  # noqa: F811
    queued = []
    monkeypatch.setattr(clips_api, "enqueue_frame_highlights", lambda *a: queued.append(a))
    owner, clip = await _draft_clip(sessionmaker)  # clip covers 0–10 s
    async with sessionmaker() as db:
        # Not scored yet: POST queues a score-only run (make_clips=False) and leaves clips alone.
        assert (await clips_api.get_virality(clip.id, owner, db)).status == "none"
        assert (await clips_api.score_virality(clip.id, owner, db)).status == "processing"
    assert queued and queued[0][0] == clip.session_id and queued[0][-1] is False

    await _score_frames(sessionmaker, clip, [(1000, 0.2), (4000, 0.9), (6000, 0.8), (8000, 0.7), (12_000, 1.0)])
    async with sessionmaker() as db:
        v = await clips_api.get_virality(clip.id, owner, db)
        assert v.status == "ready" and v.score == 80.0 and v.verdict == "strong"  # mean of the top 3 inside 0–10 s
        assert v.peak_offset_ms == 4000 and [p.offset_ms for p in v.curve] == [1000, 4000, 6000, 8000]
        assert v.components.visibility == 90.0
        stranger = User(username=f"x_{uuid.uuid4().hex[:6]}")
        db.add(stranger)
        await db.commit()
        for call in (clips_api.get_virality, clips_api.score_virality):
            with pytest.raises(HTTPException) as e:
                await call(clip.id, stranger, db)
            assert e.value.status_code == 403


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
