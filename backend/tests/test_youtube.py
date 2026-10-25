"""YouTube posting with Google mocked at the HTTP layer (httpx.MockTransport)."""

import json
import uuid

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.models import Clip, Notification, SessionStatus, YouTubeAccount, YouTubeUpload
from app.services import youtube
from app.services.storage import LocalStorage
from app.worker.pipeline import run_pipeline
from tests.test_pipeline_e2e import FakeDetector, _deps, _new_session, migrated_db, sessionmaker, video  # noqa: F401

KEY = Fernet.generate_key().decode()


def yt_settings(**kw) -> Settings:
    return get_settings().model_copy(
        update={"youtube_client_id": "cid", "youtube_client_secret": "secret", "youtube_token_key": KEY, **kw}
    )


def test_state_round_trip_and_tampering():
    s = yt_settings()
    uid = uuid.uuid4()
    state = youtube.sign_state(s, uid, now=1_000_000)
    assert youtube.verify_state(s, state, now=1_000_100) == uid
    with pytest.raises(youtube.YouTubeError, match="too long"):
        youtube.verify_state(s, state, now=1_000_000 + youtube.STATE_TTL_S + 1)
    forged = youtube.sign_state(yt_settings(youtube_token_key=Fernet.generate_key().decode()), uid, now=1_000_000)
    with pytest.raises(youtube.YouTubeError, match="Invalid"):
        youtube.verify_state(s, forged, now=1_000_100)
    with pytest.raises(youtube.YouTubeError):
        youtube.verify_state(s, "garbage", now=1_000_100)


def test_token_encryption_and_not_configured():
    s = yt_settings()
    enc = youtube.encrypt_token(s, "1//refresh")
    assert "refresh" not in enc and youtube.decrypt_token(s, enc) == "1//refresh"
    with pytest.raises(youtube.YouTubeNotConfigured):
        youtube.encrypt_token(Settings(), "x")
    assert not youtube.is_configured(Settings())


def test_auth_url_asks_for_offline_upload_access():
    url = youtube.auth_url(yt_settings(), "https://api.example/youtube/callback", "st")
    assert "access_type=offline" in url and "youtube.upload" in url and "prompt=consent" in url and "state=st" in url


def test_clean_metadata_fits_youtube_limits():
    title, desc, tags = youtube.clean_metadata("  <b>Clutch</b>   " + "x" * 200, "a" * 6000, ["#valorant", "valorant", " ", "t" * 300, "u" * 300])
    assert title.startswith("bClutch/b") and len(title) == 100 and "<" not in title
    assert len(desc) == 5000
    assert tags == ["valorant", "t" * 300]  # dedupe, strip '#', stop before 500 chars


def fake_google(calls: list, upload_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.url.host == "oauth2.googleapis.com":
            assert b"refresh_token=1%2F%2Frefresh" in request.content
            return httpx.Response(200, json={"access_token": "ya29.token"})
        if request.method == "POST" and "uploadType=resumable" in str(request.url):
            meta = json.loads(request.content)
            assert request.headers["authorization"] == "Bearer ya29.token"
            assert meta["status"]["privacyStatus"] == "unlisted" and meta["snippet"]["categoryId"] == "20"
            return httpx.Response(200, headers={"location": "https://upload.example/session/1"})
        if request.method == "PUT" and request.url.host == "upload.example":
            assert int(request.headers["content-length"]) > 1000  # the rendered MP4
            if upload_status != 200:
                return httpx.Response(upload_status, json={"error": {"message": "quota", "errors": [{"reason": "quotaExceeded"}]}})
            return httpx.Response(200, json={"id": "dQw4w9WgXcQ"})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _ready_clip_with_account(sm, storage, vid, settings):
    sid = await _new_session(sm, storage, vid)
    deps = _deps(sm, storage, FakeDetector())
    deps.settings = settings
    assert await run_pipeline(sid, deps=deps) == SessionStatus.READY
    async with sm() as db:
        clip = (await db.scalars(select(Clip).where(Clip.session_id == sid))).first()
        clip.publish_state = "ready"
        db.add(YouTubeAccount(user_id=clip.user_id, channel_id="UC123", channel_title="Shadow",
                              refresh_token_enc=youtube.encrypt_token(settings, "1//refresh")))
        up = YouTubeUpload(clip_id=clip.id, user_id=clip.user_id, privacy="unlisted", title="Insane clutch",
                           description="gg", tags=["valorant"])
        db.add(up)
        await db.commit()
        return clip, up, deps


async def test_post_to_youtube_end_to_end(sessionmaker, video, tmp_path):  # noqa: F811
    from app.worker.youtube_post import post_to_youtube

    settings = yt_settings()
    storage = LocalStorage(tmp_path / "storage")
    clip, up, deps = await _ready_clip_with_account(sessionmaker, storage, video, settings)

    calls: list = []
    async with fake_google(calls) as http:
        video_id = await post_to_youtube(up.id, deps, http=http)
    assert video_id == "dQw4w9WgXcQ"
    assert [m for m, _ in calls] == ["POST", "POST", "PUT"]  # token refresh, start upload, send bytes

    async with sessionmaker() as db:
        row = await db.get(YouTubeUpload, up.id)
        assert (row.status, row.video_id, row.error) == ("published", "dQw4w9WgXcQ", None)
        note = await db.scalar(select(Notification).where(Notification.clip_id == clip.id, Notification.type == "youtube_posted"))
        assert note.data["url"] == "https://youtu.be/dQw4w9WgXcQ" and note.data["privacy"] == "unlisted"

    # Running it again doesn't upload twice.
    async with fake_google(calls) as http:
        assert await post_to_youtube(up.id, deps, http=http) == "dQw4w9WgXcQ"
    assert len(calls) == 3


async def test_post_to_youtube_failure_is_recorded(sessionmaker, video, tmp_path):  # noqa: F811
    from app.worker.youtube_post import post_to_youtube

    settings = yt_settings()
    storage = LocalStorage(tmp_path / "storage")
    clip, up, deps = await _ready_clip_with_account(sessionmaker, storage, video, settings)
    async with fake_google([], upload_status=403) as http:
        with pytest.raises(youtube.YouTubeError, match="quotaExceeded"):
            await post_to_youtube(up.id, deps, http=http)
    async with sessionmaker() as db:
        row = await db.get(YouTubeUpload, up.id)
        assert row.status == "failed" and "quotaExceeded" in row.error
        note = await db.scalar(select(Notification).where(Notification.clip_id == clip.id, Notification.type == "youtube_posted"))
        assert note.data["status"] == "failed"


async def test_post_montage_uploads_the_rendered_file(sessionmaker, video, tmp_path):  # noqa: F811
    from app.worker.export import export_key
    from app.worker.youtube_post import post_to_youtube

    settings = yt_settings()
    storage = LocalStorage(tmp_path / "storage")
    clip, up, deps = await _ready_clip_with_account(sessionmaker, storage, video, settings)
    montage_key = f"highlights/{clip.id}/montage.mp4"
    storage.put_bytes(montage_key, b"\0" * 4321, "video/mp4")
    async with sessionmaker() as db:
        row = await db.get(YouTubeUpload, up.id)
        row.kind, row.source_key = "montage", montage_key
        await db.commit()

    sizes: list[int] = []
    calls: list = []
    client = fake_google(calls)
    original = client._transport.handler

    def recording(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            sizes.append(int(request.headers["content-length"]))
        return original(request)

    client._transport.handler = recording
    async with client as http:
        assert await post_to_youtube(up.id, deps, http=http) == "dQw4w9WgXcQ"
    assert sizes == [4321]  # the montage file, not the clip
    assert not storage.exists(export_key(clip.id, clip.start_ms, clip.end_ms))  # no plain export was made
