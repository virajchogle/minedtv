"""Write docs/openapi.json and example responses to docs/api-examples/.

    python -m scripts.export_api_docs

Examples are built from the real response models, so they fail loudly here if they drift
from the API. The data mirrors the MinedTv app's SampleData (same users and games).
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.db.models import PIPELINE_STEPS
from app.main import create_app
from app.ml.audience_simulator import AudiencePanelDraft, build_audience_simulation
from app.schemas import (
    ClipDetailOut,
    CommentOut,
    CommentsPage,
    FollowOut,
    NotificationClip,
    NotificationOut,
    NotificationsPage,
    ProfileOut,
    MomentOut,
    ClipOut,
    CountsOut,
    CreatorPackOut,
    EventOut,
    ExportOut,
    FeedOut,
    HealthOut,
    SearchOut,
    SearchResult,
    SessionOut,
    SessionStatusEvent,
    TranscriptOut,
    UploadOut,
    UserOut,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "api-examples"
API = "https://minedtv-api-xxxxx-ue.a.run.app"
CDN = "https://pub-xxxxxxxx.r2.dev"
NOW = datetime(2026, 10, 24, 18, 30, tzinfo=UTC)


def uid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


USERS = [UserOut(id=uid(100 + i), username=n, avatar_url=f"{CDN}/avatars/{n.lower()}.png")
         for i, n in enumerate(["ShadowSniper", "NovaQueen", "xPixel", "Glitchy", "Kairo"])]

CLIPS = [
    # (title, game, user index, start_ms, end_ms, views, likes, kind)
    ("1v5 clutch on Ascent", "Valorant", 0, 312_000, 342_000, 48_211, 3_904, "auto"),
    ("No scope across the map", "CS2", 1, 95_000, 112_000, 12_877, 1_210, "user"),
    ("Last circle 20-bomb", "Fortnite", 2, 1_402_000, 1_437_000, 201_554, 18_022, "auto"),
    ("Squad wipe with a pistol", "Apex Legends", 3, 640_000, 668_000, 7_310, 615, "user"),
    ("Ace in overtime", "Valorant", 4, 2_210_000, 2_241_000, 33_090, 2_744, "auto"),
]


def clip(i: int, liked: bool | None = None) -> ClipOut:
    title, game, u, start, end, views, likes, kind = CLIPS[i]
    cid, sid = uid(1000 + i), uid(500 + i)
    return ClipOut(
        id=cid, session_id=sid, user=USERS[u], game=game, title=title, start_ms=start, end_ms=end,
        duration_ms=end - start, thumbnail_url=f"{CDN}/sessions/{sid}/frames/{(start + end) // 2 // 1000 * 1000:09d}.jpg",
        playlist_url=f"{API}/clips/{cid}/playlist.m3u8", status="ready", kind=kind, view_count=views,
        like_count=likes, liked_by_me=liked, created_at=NOW - timedelta(hours=3 * i),
    )


def session(status: str = "ready", last_step: str | None = "finalize", **kw) -> SessionOut:
    sid = uid(500)
    ready = status == "ready"
    return SessionOut(
        id=sid, user=USERS[0], game="Valorant", title="Ranked on Ascent", started_at=NOW - timedelta(hours=2),
        duration_ms=2_712_000 if last_step else None, width=1920 if last_step else None,
        height=1080 if last_step else None, status=status, last_step=last_step, failed_step=kw.get("failed_step"),
        error=kw.get("error"), poster_url=f"{CDN}/sessions/{sid}/poster.jpg" if ready else None,
        playlist_url=f"{API}/sessions/{sid}/playlist.m3u8" if ready else None, created_at=NOW - timedelta(hours=1),
    )


def status_event(status: str, last_step: str | None, **kw) -> SessionStatusEvent:
    done = PIPELINE_STEPS.index(last_step) + 1 if last_step else 0
    return SessionStatusEvent(
        session_id=uid(500), status=status, progress=1.0 if status == "ready" else done / len(PIPELINE_STEPS),
        steps=PIPELINE_STEPS, last_step=last_step, failed_step=kw.get("failed_step"), error=kw.get("error"),
        done=status in ("ready", "failed"),
    )


def search_results() -> SearchOut:
    c0, c4 = clip(0), clip(4)
    return SearchOut(
        query="the clutch on ascent",
        took_ms=184,
        cached=False,
        results=[
            SearchResult(
                kind="clip", clip_id=c0.id, session_id=c0.session_id, match_t_ms=331_000, start_ms=c0.start_ms,
                end_ms=c0.end_ms, score=0.04838, confidence=0.97, signals=["visual", "speech", "event"],
                thumbnail_url=f"{CDN}/sessions/{c0.session_id}/frames/000331000.jpg",
                transcript_snippet="NO WAY he just clutched that, one versus five",
                playlist_url=c0.playlist_url, game=c0.game, title=c0.title, user=c0.user,
                other_moments_ms=[338_500],
                moments=[
                    MomentOut(t_ms=331_000, offset_ms=19_000, confidence=0.97, signals=["visual", "speech", "event"],
                              label="clutch", snippet="NO WAY he just clutched that, one versus five",
                              thumbnail_url=f"{CDN}/sessions/{c0.session_id}/frames/000331000.jpg"),
                    MomentOut(t_ms=338_500, offset_ms=26_500, confidence=0.71, signals=["visual"], label=None,
                              snippet=None, thumbnail_url=f"{CDN}/sessions/{c0.session_id}/frames/000338000.jpg"),
                ],
            ),
            SearchResult(
                kind="session", clip_id=None, session_id=uid(507), match_t_ms=754_000, start_ms=739_000,
                end_ms=769_000, score=0.03175, confidence=0.96, signals=["speech", "keyword"],
                thumbnail_url=f"{CDN}/sessions/{uid(507)}/frames/000754000.jpg",
                transcript_snippet="okay okay clutch time, I've got this",
                playlist_url=f"{API}/sessions/{uid(507)}/playlist.m3u8?start_ms=739000&end_ms=769000",
                game="Valorant", title="Late night ranked", user=USERS[1], other_moments_ms=[],
                moments=[MomentOut(t_ms=754_000, offset_ms=15_000, confidence=0.96, signals=["speech", "keyword"], label=None,
                                   snippet="okay okay clutch time, I've got this",
                                   thumbnail_url=f"{CDN}/sessions/{uid(507)}/frames/000754000.jpg")],
            ),
            SearchResult(
                kind="clip", clip_id=c4.id, session_id=c4.session_id, match_t_ms=2_226_000, start_ms=c4.start_ms,
                end_ms=c4.end_ms, score=0.01639, confidence=0.88, signals=["event"],
                thumbnail_url=f"{CDN}/sessions/{c4.session_id}/frames/002226000.jpg", transcript_snippet=None,
                playlist_url=c4.playlist_url, game=c4.game, title=c4.title, user=c4.user, other_moments_ms=[],
                moments=[MomentOut(t_ms=2_226_000, offset_ms=16_000, confidence=0.88, signals=["event"], label="ace",
                                   snippet=None, thumbnail_url=f"{CDN}/sessions/{c4.session_id}/frames/002226000.jpg")],
            ),
        ],
    )


def examples() -> dict[str, object]:
    c0 = clip(0, liked=True)
    sid = uid(500)
    creator = CreatorPackOut(
        title_options=["1v5 Clutch on Ascent", "The Round That Looked Over", "Five Players, One Vandal"],
        description="A Valorant player is left alone on Ascent and eliminates all five opponents to win the round.",
        summary="A Valorant player wins a one-versus-five round on Ascent.",
        caption="The one-versus-five that somehow worked.",
        youtube={
            "title": "1v5 Valorant Clutch on Ascent",
            "description": "A full one-versus-five clutch from a ranked match on Ascent.",
            "tags": ["Valorant", "Ascent", "clutch", "gaming"],
            "chapters": [{"timestamp": "00:00", "label": "The clutch"}],
        },
        reddit={
            "title": "Managed a 1v5 on Ascent",
            "body": "I thought this round was over, but the last duel worked out.",
            "suggested_subreddits": ["VALORANT", "gaming"],
        },
        transcript=[{"timestamp": "00:12", "text": "No way."}],
        key_moments=[{"timestamp": "00:18", "label": "The final elimination wins the round"}],
        hashtags=["Valorant", "gaming", "clutch"],
        content_warnings=[],
    )
    panel = AudiencePanelDraft.model_validate({
        "inferred_niche": "competitive gaming clips",
        "inferred_target_audience": "Valorant players and FPS highlight viewers",
        "personas": [
            {
                "name": "Ranked regular", "layer": "target", "profile": "Plays Valorant most evenings",
                "interests": ["Valorant", "ranked play"], "hook_score": 91, "completion_probability": 0.94,
                "like_probability": 0.86, "comment_probability": 0.61, "save_probability": 0.44,
                "share_probability": 0.72, "skip_probability": 0.04, "primary_action": "share",
                "reaction": "The impossible-looking setup makes the final duel land.",
                "suggested_comment": "How did they isolate every fight?", "what_worked": "The stakes are immediate.",
                "friction": "The first elimination is hard to see.", "recommended_change": "Add a quick 1v5 overlay.",
            },
            {
                "name": "General FPS fan", "layer": "adjacent", "profile": "Watches competitive shooters",
                "interests": ["FPS games", "esports"], "hook_score": 72, "completion_probability": 0.73,
                "like_probability": 0.66, "comment_probability": 0.35, "save_probability": 0.24,
                "share_probability": 0.46, "skip_probability": 0.18, "primary_action": "like",
                "reaction": "The skill is clear even without knowing the map.", "suggested_comment": None,
                "what_worked": "Each elimination increases tension.", "friction": "Game context is assumed.",
                "recommended_change": "Show the score and player count at the start.",
            },
            {
                "name": "Casual viewer", "layer": "outsider", "profile": "Rarely watches gaming clips",
                "interests": ["short comedy", "sports"], "hook_score": 43, "completion_probability": 0.38,
                "like_probability": 0.27, "comment_probability": 0.08, "save_probability": 0.04,
                "share_probability": 0.09, "skip_probability": 0.58, "primary_action": "skip",
                "reaction": "The ending looks impressive, but the stakes arrive too late.", "suggested_comment": None,
                "what_worked": "The team reaction explains the payoff.", "friction": "The HUD is difficult to parse.",
                "recommended_change": "Open with the final reaction, then replay the clutch.",
            },
        ],
        "consensus_strengths": ["The clip has a clear escalating payoff."],
        "consensus_risks": ["Viewers outside the game may not understand the stakes."],
        "recommended_changes": ["Add a one-second 1v5 context card before the action."],
    })
    return {
        "health.json": HealthOut(status="ok", checks={"database": "ok", "redis": "ok", "storage": "ok"}),
        "users.create.json": USERS[0],
        "users.list.json": USERS,
        "uploads.create.json": UploadOut(
            session_id=sid,
            upload_url=f"https://<account>.r2.cloudflarestorage.com/minedtv/sessions/{sid}/source.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=...",
            headers={"Content-Type": "video/mp4"}, expires_in_s=3600, storage_key=f"sessions/{sid}/source.mp4",
        ),
        "uploads.complete.json": session("queued", None),
        "sessions.get.json": session(),
        "sessions.get.failed.json": session("failed", "audio", failed_step="highlights", error="RuntimeError: model exploded"),
        "sessions.reprocess.json": status_event("queued", "audio"),
        "feed.json": FeedOut(items=[clip(i) for i in range(5)], next_cursor="MjAyNi0xMC0yNFQwNjozMDowMCswMDowMHwwMDAw"),
        "users.clips.json": FeedOut(items=[clip(0)], next_cursor=None),
        "clips.get.json": ClipDetailOut(
            **c0.model_dump(), session_duration_ms=2_712_000,
            events=[
                EventOut(id=uid(9001), t_ms=318_400, type="kill", score=0.62, source="HighlightDetector", metadata={"weapon": "vandal"}),
                EventOut(id=uid(9002), t_ms=331_000, type="clutch", score=0.97, source="HighlightDetector", metadata={"enemies": 5}),
            ],
            transcript=[
                TranscriptOut(id=uid(9101), start_ms=312_500, end_ms=319_000, speaker=None, text="okay it's me alone, nobody talk"),
                TranscriptOut(id=uid(9102), start_ms=329_000, end_ms=336_000, speaker="friend", text="NO WAY he just clutched that, one versus five"),
            ],
        ),
        "clips.create.json": clip(1),
        "clips.patch.json": clip(0).model_copy(update={"start_ms": 305_000, "end_ms": 345_000, "duration_ms": 40_000}),
        "clips.like.json": CountsOut(clip_id=c0.id, view_count=48_211, like_count=3_905, liked_by_me=True),
        "clips.unlike.json": CountsOut(clip_id=c0.id, view_count=48_211, like_count=3_904, liked_by_me=False),
        "clips.view.json": CountsOut(clip_id=c0.id, view_count=48_212, like_count=3_904, liked_by_me=None),
        "clips.publish.json": clip(0).model_copy(update={"publish_state": "published", "published_at": NOW}),
        "clips.export.processing.json": ExportOut(clip_id=c0.id, status="processing", url=None, start_ms=c0.start_ms, end_ms=c0.end_ms),
        "clips.export.ready.json": ExportOut(clip_id=c0.id, status="ready", url=f"{CDN}/exports/{c0.id}/{c0.start_ms}-{c0.end_ms}.mp4",
                                             start_ms=c0.start_ms, end_ms=c0.end_ms),
        "comments.list.json": CommentsPage(
            total=3,
            next_cursor=None,
            items=[
                CommentOut(
                    id=uid(7001), clip_id=c0.id, user=USERS[1], body="that flick was disgusting 🔥", parent_id=None,
                    created_at=NOW - timedelta(minutes=40), reply_count=2, can_delete=False,
                    replies=[
                        CommentOut(id=uid(7002), clip_id=c0.id, user=USERS[2], body="aim assist on real life",
                                   parent_id=uid(7001), created_at=NOW - timedelta(minutes=30), can_delete=False),
                        CommentOut(id=uid(7003), clip_id=c0.id, user=USERS[0], body="thanks both!",
                                   parent_id=uid(7001), created_at=NOW - timedelta(minutes=20), can_delete=True),
                    ],
                )
            ],
        ),
        "users.profile.json": ProfileOut(**USERS[0].model_dump(), follower_count=1204, following_count=87,
                                         published_clip_count=42, followed_by_me=True, follows_me=False),
        "users.follow.json": FollowOut(user_id=USERS[0].id, following=True, follower_count=1205),
        "notifications.json": NotificationsPage(
            unread_count=2,
            next_cursor=None,
            items=[
                NotificationOut(id=uid(8001), type="like", message=f"NovaQueen liked your clip “{c0.title}”",
                                actor=USERS[1], clip=NotificationClip(id=c0.id, title=c0.title, thumbnail_url=c0.thumbnail_url),
                                comment_id=None, session_id=None, data={}, read=False, created_at=NOW - timedelta(minutes=2)),
                NotificationOut(id=uid(8002), type="comment",
                                message=f"xPixel commented on your clip “{c0.title}”: how did you hit that??",
                                actor=USERS[2], clip=NotificationClip(id=c0.id, title=c0.title, thumbnail_url=c0.thumbnail_url),
                                comment_id=uid(7004), session_id=None, data={"preview": "how did you hit that??"},
                                read=False, created_at=NOW - timedelta(minutes=32)),
                NotificationOut(id=uid(8003), type="follow", message="Kairo started following you", actor=USERS[4],
                                clip=None, comment_id=None, session_id=None, data={}, read=True,
                                created_at=NOW - timedelta(hours=5)),
                NotificationOut(id=uid(8004), type="upload_ready",
                                message="Your upload “Ranked on Ascent” is ready (3 clips, saved as drafts)", actor=None,
                                clip=NotificationClip(id=c0.id, title=c0.title, thumbnail_url=c0.thumbnail_url),
                                comment_id=None, session_id=c0.session_id,
                                data={"title": "Ranked on Ascent", "clip_ids": [str(c0.id)]}, read=True,
                                created_at=NOW - timedelta(hours=6)),
            ],
        ),
        "search.json": search_results(),
        "search.image.json": search_results().model_copy(update={"query": "image:screenshot.png", "took_ms": 241}),
        "creator.analyze.json": creator,
        "creator.simulate.json": build_audience_simulation(panel, creator, "instagram", "FPS highlight viewers"),
    }


def dump(obj) -> str:
    if isinstance(obj, list):
        return json.dumps([o.model_dump(mode="json") for o in obj], indent=2)
    return obj.model_dump_json(indent=2)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, obj in examples().items():
        (OUT / name).write_text(dump(obj) + "\n")

    sse = [status_event("queued", None), status_event("probing", None), status_event("segmenting", "probe"),
           status_event("frames", "thumbnails"), status_event("audio", "frames"), status_event("ready", "finalize")]
    (OUT / "sessions.status.sse.txt").write_text("".join(f"event: status\ndata: {e.model_dump_json()}\n\n" for e in sse))

    c = clip(0)
    playlist = ["#EXTM3U", "#EXT-X-VERSION:6", "#EXT-X-TARGETDURATION:2", "#EXT-X-MEDIA-SEQUENCE:156",
                "#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-INDEPENDENT-SEGMENTS"]
    for i in range(156, 171):
        playlist += ["#EXTINF:2.000,", f"{CDN}/sessions/{c.session_id}/hls/seg_{i:05d}.ts"]
    (OUT / "clips.playlist.m3u8").write_text("\n".join(playlist + ["#EXT-X-ENDLIST"]) + "\n")

    spec = create_app().openapi()
    (ROOT / "docs" / "openapi.json").write_text(json.dumps(spec, indent=2) + "\n")
    print(f"wrote {len(list(OUT.iterdir()))} examples to {OUT.relative_to(ROOT)} and docs/openapi.json")


if __name__ == "__main__":
    main()
