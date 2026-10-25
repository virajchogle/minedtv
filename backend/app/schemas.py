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
    "uploading", "queued", "probing", "segmenting", "thumbnails", "frames", "audio", "highlights", "finalizing", "ready", "failed"
]


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


# --- clips ---


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
    view_count: int
    like_count: int
    liked_by_me: bool | None = Field(default=None, description="Only set when X-User-Id is sent")
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
