"""Pydantic models for every API request and response."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthOut(_Out):
    status: Literal["ok", "degraded"]
    checks: dict[str, str]


# --- users ---


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    avatar_url: str | None = None


class UserOut(_Out):
    id: uuid.UUID
    username: str
    avatar_url: str | None = None


class SignupIn(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=254, description="Username or email")
    password: str = Field(min_length=1, max_length=200)


class MeOut(UserOut):
    email: str | None
    is_dev: bool
    can_act_as: bool = Field(default=False, description="May act as other users: dev accounts, or anyone while REQUIRE_LOGIN is off")


class AuthOut(BaseModel):
    token: str = Field(description="Send as Authorization: Bearer <token>")
    expires_at: datetime
    user: MeOut


# --- uploads / sessions ---


class UploadCreate(BaseModel):
    filename: str = Field(examples=["ranked-bind.mp4"])
    content_type: str = Field(default="video/mp4", examples=["video/mp4"])
    game: str | None = Field(default=None, examples=["Valorant"])
    title: str | None = Field(default=None, examples=["Ranked on Bind"])
    started_at: datetime | None = Field(default=None, description="When the recording started, if the client knows")
    size_bytes: int | None = Field(default=None, ge=0)


class UploadOut(_Out):
    session_id: uuid.UUID
    upload_url: str = Field(description="Presigned URL. PUT the raw file bytes here with the given headers.")
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_in_s: int
    storage_key: str


SessionStatusLiteral = Literal[
    "uploading",
    "queued",
    "probing",
    "segmenting",
    "thumbnails",
    "frames",
    "audio",
    "moderating",
    "highlights",
    "finalizing",
    "ready",
    "failed",
    "blocked",
]

ModerationSeverity = Literal["none", "mild", "severe"]


class SessionOut(_Out):
    id: uuid.UUID
    user: UserOut
    game: str | None
    title: str | None
    started_at: datetime | None
    duration_ms: int | None
    width: int | None
    height: int | None
    status: SessionStatusLiteral
    last_step: str | None
    failed_step: str | None
    error: str | None
    poster_url: str | None
    playlist_url: str | None
    created_at: datetime
    moderation_severity: ModerationSeverity = Field(
        description="Transcript moderation verdict. 'severe' never reaches this as a readable session — "
        "the pipeline stops and status becomes 'blocked' instead."
    )
    moderation_reason: str | None = Field(default=None, description="One-line reason, owner-visible only")
    age_restricted: bool = Field(description="True for 'mild' or 'severe' moderation verdicts")


class SessionStatusEvent(_Out):
    """Payload of each `status` event on GET /sessions/{id}/status (server-sent events)."""

    session_id: uuid.UUID
    status: SessionStatusLiteral
    progress: float = Field(ge=0, le=1, description="Fraction of pipeline steps completed")
    steps: list[str] = Field(description="All pipeline steps, in order")
    last_step: str | None
    failed_step: str | None
    error: str | None
    done: bool
    moderation_severity: ModerationSeverity
    age_restricted: bool


# --- clips ---


PublishState = Literal["draft", "ready", "published"]


class ClipOut(_Out):
    id: uuid.UUID
    session_id: uuid.UUID
    user: UserOut
    game: str | None
    title: str | None
    start_ms: int
    end_ms: int
    duration_ms: int
    thumbnail_url: str | None
    playlist_url: str
    status: str
    kind: Literal["auto", "user"]
    publish_state: PublishState = Field(
        default="published",
        description="draft (owner only) -> published (public). 'ready' is a legacy owner-only state the web app treats as draft",
    )
    published_at: datetime | None = None
    view_count: int
    like_count: int
    liked_by_me: bool | None = Field(default=None, description="Only set when X-User-Id is sent")
    comment_count: int = 0
    youtube_url: str | None = Field(default=None, description="Latest successful post of this clip to YouTube")
    age_restricted: bool = Field(default=False, description="Transcript moderation flagged this clip 18+")
    moderation_severity: ModerationSeverity = Field(default="none", description="The owning session's moderation verdict")
    moderation_reason: str | None = Field(default=None, description="One-line reason, owner-visible only")
    created_at: datetime


class FeedOut(_Out):
    items: list[ClipOut]
    next_cursor: str | None = Field(description="Pass as ?cursor= to get the next page; null at the end")


class EventOut(_Out):
    id: uuid.UUID
    t_ms: int
    type: str
    score: float
    source: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptOut(_Out):
    id: uuid.UUID
    start_ms: int
    end_ms: int
    speaker: str | None
    text: str


class ClipDetailOut(ClipOut):
    session_duration_ms: int | None
    frame_count: int = Field(description="Sampled, embedded frames inside the clip's range")
    events: list[EventOut]
    transcript: list[TranscriptOut]


class ClipCreate(BaseModel):
    session_id: uuid.UUID
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    title: str | None = Field(default=None, max_length=200)


class ClipPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)


class ExportOut(_Out):
    clip_id: uuid.UUID
    status: Literal["none", "processing", "ready", "failed"] = Field(
        description="'none' = never requested for this clip range; POST to start"
    )
    url: str | None = Field(description="MP4 download URL when ready")
    error: str | None = None
    start_ms: int
    end_ms: int


class CountsOut(_Out):
    clip_id: uuid.UUID
    view_count: int
    like_count: int
    liked_by_me: bool | None = None


# --- search ---

Signal = Literal["visual", "speech", "keyword", "event"]


class MomentOut(_Out):
    t_ms: int = Field(description="Moment time in session time")
    offset_ms: int = Field(description="Moment time relative to the result's start_ms (where to seek in its playlist)")
    confidence: float = Field(ge=0, le=1)
    signals: list[Signal]
    label: str | None = Field(description="Event type when a highlight event matched, e.g. 'clutch'")
    snippet: str | None = Field(description="Transcript line when speech matched")
    thumbnail_url: str | None


class SearchResult(_Out):
    kind: Literal["clip", "session"] = Field(
        description="'clip' when an existing clip contains the match; otherwise 'session' with a suggested window"
    )
    clip_id: uuid.UUID | None
    session_id: uuid.UUID
    match_t_ms: int = Field(description="The exact moment to seek to, in session time")
    start_ms: int = Field(description="Clip start, or start of the suggested window")
    end_ms: int = Field(description="Clip end, or end of the suggested window")
    score: float = Field(description="Raw fusion score; only meaningful for ordering")
    confidence: float = Field(ge=0, le=1, description="How sure the match is, 0..1, comparable across queries")
    signals: list[Signal]
    thumbnail_url: str | None
    transcript_snippet: str | None
    playlist_url: str
    game: str | None
    title: str | None
    user: UserOut
    other_moments_ms: list[int] = Field(default_factory=list, description="Further good matches in the same session")
    moments: list[MomentOut] = Field(default_factory=list, description="Best moment first, then the others, with details")


class SearchOut(_Out):
    query: str
    results: list[SearchResult]
    took_ms: int
    cached: bool


# --- AI creator metadata ---


class CreatorTranscriptCue(BaseModel):
    timestamp: str = Field(examples=["00:12"])
    text: str


class CreatorKeyMoment(BaseModel):
    timestamp: str = Field(examples=["00:12"])
    label: str


class CreatorChapter(BaseModel):
    timestamp: str = Field(examples=["00:00"])
    label: str


class CreatorYouTubeMetadata(BaseModel):
    title: str = Field(max_length=100)
    description: str
    tags: list[str]
    chapters: list[CreatorChapter]


class CreatorRedditMetadata(BaseModel):
    title: str
    body: str
    suggested_subreddits: list[str]


class CreatorPackOut(_Out):
    title_options: list[str]
    description: str
    summary: str
    caption: str
    youtube: CreatorYouTubeMetadata
    reddit: CreatorRedditMetadata
    transcript: list[CreatorTranscriptCue]
    key_moments: list[CreatorKeyMoment]
    hashtags: list[str]
    content_warnings: list[str]


CreatorPlatform = Literal["general", "youtube", "reddit", "instagram", "tiktok"]
AudienceLayer = Literal["target", "adjacent", "outsider"]
AudienceAction = Literal["like", "comment", "save", "share", "skip"]


class AudienceSimulationIn(BaseModel):
    """Run personas against an already-generated creator content pack."""

    analysis: CreatorPackOut
    platform: CreatorPlatform = "general"
    target_audience: str | None = Field(default=None, max_length=500)
    persona_count: int | None = Field(default=None, ge=3, le=15)


class AudiencePersonaReview(BaseModel):
    name: str
    layer: AudienceLayer
    profile: str
    interests: list[str]
    hook_score: int = Field(ge=0, le=100)
    completion_probability: float = Field(ge=0, le=1)
    like_probability: float = Field(ge=0, le=1)
    comment_probability: float = Field(ge=0, le=1)
    save_probability: float = Field(ge=0, le=1)
    share_probability: float = Field(ge=0, le=1)
    skip_probability: float = Field(ge=0, le=1)
    primary_action: AudienceAction
    reaction: str
    suggested_comment: str | None = None
    what_worked: str
    friction: str
    recommended_change: str


class AudienceMetricsOut(BaseModel):
    simulated_watch_rate: float = Field(ge=0, le=100)
    simulated_completion_rate: float = Field(ge=0, le=100)
    simulated_like_rate: float = Field(ge=0, le=100)
    simulated_comment_rate: float = Field(ge=0, le=100)
    simulated_save_rate: float = Field(ge=0, le=100)
    simulated_share_rate: float = Field(ge=0, le=100)
    action_distribution: dict[AudienceAction, int]


class AudienceLayerOut(BaseModel):
    layer: AudienceLayer
    persona_count: int = Field(ge=1)
    score: float = Field(ge=0, le=100)
    threshold: float = Field(ge=0, le=100)
    exposed_in_cascade: bool
    cleared_threshold: bool


class AudienceSimulationOut(_Out):
    platform: CreatorPlatform
    requested_target_audience: str | None
    inferred_niche: str
    inferred_target_audience: str
    virality_score: float = Field(ge=0, le=100)
    verdict: Literal["weak", "mixed", "promising", "strong"]
    cascade_depth: Literal["target_only", "adjacent", "outsider", "broad_breakout"]
    cascade_summary: str
    metrics: AudienceMetricsOut
    layers: list[AudienceLayerOut]
    persona_reviews: list[AudiencePersonaReview]
    consensus_strengths: list[str]
    consensus_risks: list[str]
    recommended_changes: list[str]
    analysis: CreatorPackOut
    disclaimer: str


class ClipCreatorPackOut(_Out):
    clip_id: uuid.UUID
    status: Literal["none", "processing", "ready", "failed"] = Field(
        description="'none' = never requested for this clip range; POST to start"
    )
    model: str | None = Field(default=None, description="Gemini model that produced the pack")
    pack: CreatorPackOut | None = None
    error: str | None = None
    start_ms: int
    end_ms: int


class ClipViralityIn(BaseModel):
    platform: CreatorPlatform = "general"
    target_audience: str | None = Field(default=None, max_length=500)
    persona_count: int | None = Field(default=None, ge=3, le=15)


class ClipViralityOut(_Out):
    clip_id: uuid.UUID
    status: Literal["none", "processing", "ready", "failed"]
    platform: CreatorPlatform
    result: AudienceSimulationOut | None = None
    error: str | None = None
    start_ms: int
    end_ms: int


# --- social: profiles, follows, comments, notifications ---


class ProfileOut(UserOut):
    follower_count: int
    following_count: int
    published_clip_count: int
    followed_by_me: bool | None = Field(default=None, description="Only set when X-User-Id is sent")
    follows_me: bool | None = Field(default=None, description="Only set when X-User-Id is sent")


class FollowOut(_Out):
    user_id: uuid.UUID
    following: bool
    follower_count: int


class UsersPage(_Out):
    items: list[UserOut]
    next_cursor: str | None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=1000)
    parent_id: uuid.UUID | None = Field(default=None, description="Reply to this comment (one level of threading)")


class CommentOut(_Out):
    id: uuid.UUID
    clip_id: uuid.UUID
    user: UserOut
    body: str
    parent_id: uuid.UUID | None
    created_at: datetime
    reply_count: int = 0
    replies: list["CommentOut"] = Field(default_factory=list, description="Oldest first; only on top-level comments")
    can_delete: bool | None = Field(default=None, description="Author or clip owner; only set when X-User-Id is sent")


class CommentsPage(_Out):
    items: list[CommentOut] = Field(description="Top-level comments, newest first, each with its replies")
    next_cursor: str | None
    total: int = Field(description="All comments on the clip, replies included")


NotificationTypeLiteral = Literal["like", "comment", "reply", "follow", "upload_ready", "virality_ready", "youtube_posted"]


class NotificationClip(_Out):
    id: uuid.UUID
    title: str | None
    thumbnail_url: str | None


class NotificationOut(_Out):
    id: uuid.UUID
    type: NotificationTypeLiteral
    message: str = Field(description="Ready-to-show text, e.g. 'NovaQueen liked your clip'")
    actor: UserOut | None
    clip: NotificationClip | None
    comment_id: uuid.UUID | None
    session_id: uuid.UUID | None
    data: dict[str, Any] = Field(default_factory=dict)
    read: bool
    created_at: datetime


class NotificationsPage(_Out):
    items: list[NotificationOut]
    next_cursor: str | None
    unread_count: int


class UnreadCountOut(_Out):
    unread_count: int


class MarkReadIn(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, description="Notifications to mark read")
    all: bool = Field(default=False, description="Mark every notification read")


# --- YouTube ---

YouTubePrivacy = Literal["private", "unlisted", "public"]


class YouTubeStatusOut(_Out):
    configured: bool = Field(description="Whether the server has YouTube OAuth credentials")
    connected: bool
    channel_id: str | None = None
    channel_title: str | None = None


class YouTubeConnectOut(_Out):
    auth_url: str = Field(description="Open in a browser; Google redirects back to /youtube/callback")


class YouTubePostIn(BaseModel):
    title: str | None = Field(default=None, max_length=100, description="Defaults to the creator pack's YouTube title, then the clip title")
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    privacy: YouTubePrivacy = Field(
        default="private",
        description="Until the Google project passes YouTube's API audit, uploads may be forced to private",
    )


class YouTubeUploadOut(_Out):
    id: uuid.UUID
    clip_id: uuid.UUID
    status: Literal["queued", "uploading", "published", "failed"]
    privacy: YouTubePrivacy
    title: str
    description: str
    tags: list[str]
    video_id: str | None
    url: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
