/**
 * Types for the deployed MinedIt API.
 *
 * These mirror the service's OpenAPI schema exactly: same field names, same
 * units (milliseconds), same nullability. Nothing is renamed here; the
 * translation into the shapes our components use happens in `lib/api.ts`, so
 * there is one obvious place to look when the upstream contract changes.
 *
 * Source: GET /openapi.json on the deployed service.
 */

export interface UserOut {
  id: string;
  username: string;
  avatar_url: string | null;
}

/** The signed-in account (GET /auth/me). Dev accounts may act as any user. */
export interface MeOut extends UserOut {
  email: string | null;
  is_dev: boolean;
  /** May act as other users: dev accounts, or anyone while the server doesn't require login. */
  can_act_as: boolean;
  birth_date: string | null;
  is_adult: boolean;
}

/** Upstream lifecycle values seen on sessions and clips. */
export type UpstreamStatus = string;

/** Clip visibility. draft/ready are owner-only; published is public. */
export type PublishState = "draft" | "ready" | "published";

/** Transcript moderation verdict. "severe" never reaches a readable session;
 * the pipeline stops and session status becomes "blocked" instead. */
export type ModerationSeverity = "none" | "mild" | "severe";

/** One itemized finding, with where in the video it occurs. */
export interface ModerationViolationOut {
  category: string;
  timestamp_ms: number | null;
  note: string;
}

export interface ClipOut {
  id: string;
  session_id: string;
  user: UserOut;
  game: string | null;
  title: string | null;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  /** Display size (rotation applied); null until processed. */
  width?: number | null;
  height?: number | null;
  /** short = vertical and at most /config limits.short_max_duration_s long. */
  format?: "short" | "long";
  /** For reels: the clip it was made from. */
  reel_of?: string | null;
  thumbnail_url: string | null;
  playlist_url: string;
  status: UpstreamStatus;
  kind: string;
  /** draft (owner only) -> ready (queued to post to YouTube, owner only) -> published (public). */
  publish_state: PublishState;
  published_at: string | null;
  view_count: number;
  like_count: number;
  liked_by_me: boolean | null;
  age_restricted: boolean;
  moderation_severity: ModerationSeverity;
  moderation_reason: string | null;
  moderation_violations: ModerationViolationOut[];
  created_at: string;
  /** Latest successful post of this clip to YouTube. */
  youtube_url?: string | null;
}

export interface EventOut {
  id: string;
  t_ms: number;
  type: string;
  score: number;
  source: string | null;
  metadata: Record<string, unknown>;
}

export interface TranscriptOut {
  id: string;
  start_ms: number;
  end_ms: number;
  speaker: string | null;
  text: string;
}

export interface ClipDetailOut extends ClipOut {
  session_duration_ms: number | null;
  /** Sampled, embedded frames inside the clip's range. */
  frame_count: number;
  events: EventOut[];
  transcript: TranscriptOut[];
}

export interface FeedOut {
  items: ClipOut[];
  next_cursor: string | null;
}

export interface MomentOut {
  t_ms: number;
  offset_ms: number;
  confidence: number;
  signals: string[];
  label: string | null;
  snippet: string | null;
  thumbnail_url: string | null;
}

export interface UpstreamSearchResult {
  kind: string;
  clip_id: string | null;
  session_id: string;
  match_t_ms: number;
  start_ms: number;
  end_ms: number;
  score: number;
  confidence: number;
  signals: string[];
  thumbnail_url: string | null;
  transcript_snippet: string | null;
  playlist_url: string;
  game: string | null;
  title: string | null;
  user: UserOut;
  other_moments_ms: number[];
  moments: MomentOut[];
}

export interface SearchOut {
  query: string;
  results: UpstreamSearchResult[];
  took_ms: number;
  cached: boolean;
}

export interface SessionOut {
  id: string;
  user: UserOut;
  game: string | null;
  title: string | null;
  started_at: string | null;
  duration_ms: number | null;
  width: number | null;
  height: number | null;
  status: UpstreamStatus;
  last_step: string | null;
  failed_step: string | null;
  error: string | null;
  poster_url: string | null;
  playlist_url: string | null;
  created_at: string;
  moderation_severity: ModerationSeverity;
  moderation_reason: string | null;
  age_restricted: boolean;
  moderation_violations: ModerationViolationOut[];
}

export interface SessionStatusEvent {
  session_id: string;
  status: UpstreamStatus;
  progress: number;
  steps: string[];
  last_step: string | null;
  failed_step: string | null;
  error: string | null;
  done: boolean;
  moderation_severity: ModerationSeverity;
  age_restricted: boolean;
}

export interface UploadOut {
  session_id: string;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  expires_in_s: number;
  storage_key: string;
}

export interface CountsOut {
  clip_id: string;
  view_count: number;
  like_count: number;
  liked_by_me: boolean | null;
}

export type JobStatus = "none" | "processing" | "ready" | "failed";

export interface ExportOut {
  clip_id: string;
  status: JobStatus;
  url: string | null;
  error: string | null;
  start_ms: number;
  end_ms: number;
}

export interface CreatorPack {
  title_options: string[];
  description: string;
  summary: string;
  caption: string;
  youtube: {
    title: string;
    description: string;
    tags: string[];
    chapters: { timestamp: string; label: string }[];
  };
  reddit: { title: string; body: string; suggested_subreddits: string[] };
  transcript: { timestamp: string; text: string }[];
  key_moments: { timestamp: string; label: string }[];
  hashtags: string[];
  content_warnings: string[];
}

export interface ClipCreatorPackOut {
  clip_id: string;
  status: JobStatus;
  model: string | null;
  pack: CreatorPack | null;
  error: string | null;
  start_ms: number;
  end_ms: number;
}

export type CreatorPlatform = "general" | "youtube" | "reddit" | "instagram" | "tiktok";

/** A clip's virality from the frame scorer (backend ClipViralityOut). Scores are 0–100. */
export interface ClipViralityOut {
  clip_id: string;
  status: JobStatus;
  score: number | null;
  verdict: "weak" | "mixed" | "promising" | "strong" | null;
  /** The clip's strongest moment, from its start. */
  peak_offset_ms: number | null;
  components: {
    visual: number;
    novelty: number;
    event: number;
    speech: number;
    visibility: number;
    scene: number;
  } | null;
  curve: { offset_ms: number; score: number }[];
  algorithm_version: string | null;
  error: string | null;
  start_ms: number;
  end_ms: number;
}

// ── server config (GET /config) ──────────────────────────────────────────────

export interface ServerConfigOut {
  models: {
    embedder: string;
    transcriber: string;
    highlights: string;
    creator: string | null;
    creator_fallbacks: string[];
    personas: string | null;
  };
  search: Record<string, number>;
  features: { gemini: boolean; youtube: boolean; accounts: boolean; require_login: boolean };
  limits: { max_upload_mb: number; max_video_minutes: number };
}

// ── YouTube posting ──────────────────────────────────────────────────────────

export type YouTubePrivacy = "private" | "unlisted" | "public";

export interface YouTubeStatusOut {
  configured: boolean;
  connected: boolean;
  channel_id: string | null;
  channel_title: string | null;
}

export interface YouTubeUploadOut {
  id: string;
  clip_id: string;
  kind?: "clip" | "montage";
  status: "queued" | "uploading" | "published" | "failed";
  privacy: YouTubePrivacy;
  title: string;
  description: string;
  tags: string[];
  video_id: string | null;
  url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

// ── creator analytics (GET /users/{id}/analytics) ────────────────────────────

export interface AnalyticsTotals {
  views: number;
  likes: number;
  comments: number;
  new_followers: number;
}

export interface AnalyticsDay extends AnalyticsTotals {
  day: string;
}

export interface ViralitySummary {
  status: JobStatus;
  score: number | null;
  verdict: "weak" | "mixed" | "promising" | "strong" | null;
}

export interface ClipAnalytics {
  clip: ClipOut;
  period_views: number;
  period_likes: number;
  period_comments: number;
  virality: ViralitySummary;
}

export interface AnalyticsOut {
  days: number;
  start: string;
  end: string;
  tracking_since: string | null;
  lifetime: AnalyticsTotals;
  period: AnalyticsTotals;
  previous_period: AnalyticsTotals;
  follower_count: number;
  daily: AnalyticsDay[];
  clips: ClipAnalytics[];
}

// ── comments ─────────────────────────────────────────────────────────────────

export interface CommentOut {
  id: string;
  clip_id: string;
  user: UserOut;
  body: string;
  parent_id: string | null;
  created_at: string;
  reply_count: number;
  /** Oldest first; only on top-level comments. */
  replies: CommentOut[];
  /** Author or clip owner; only set when acting as a user. */
  can_delete: boolean | null;
}

export interface CommentsPage {
  /** Top-level comments, newest first, each with its replies. */
  items: CommentOut[];
  next_cursor: string | null;
  /** All comments on the clip, replies included. */
  total: number;
}

// ── AI share renders: single highlight or montage (POST/GET /clips/{id}/highlights) ──

export type HighlightMode = "single" | "montage";
export type HighlightCaptionStyle = "bold" | "minimal" | "gamer";

export interface HighlightOptions {
  platform: CreatorPlatform;
  mode: HighlightMode;
  captions: boolean;
  caption_style: HighlightCaptionStyle;
  hook: boolean;
}

export interface ClipHighlightsOut {
  clip_id: string;
  status: JobStatus;
  stage: "queued" | "exporting" | "analyzing" | "selecting" | "captioning" | "rendering";
  progress: number;
  error: string | null;
  video_url: string | null;
  download_url: string | null;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  moments: { source_start_ms: number; source_end_ms: number; score: number; reason: string }[];
  captions: { start_ms: number; end_ms: number; text: string; kind: "hook" | "speech" | "moment" }[];
  summary: string | null;
  suggested_caption: string | null;
  hashtags: string[];
}
