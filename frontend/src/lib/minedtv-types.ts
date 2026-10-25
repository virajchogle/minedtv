/**
 * Types for the deployed MinedTV API.
 *
 * These mirror the service's OpenAPI schema exactly — same field names, same
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
}

/** Upstream lifecycle values seen on sessions and clips. */
export type UpstreamStatus = string;

/** Clip visibility. draft/ready are owner-only; published is public. */
export type PublishState = "draft" | "ready" | "published";

/** Transcript moderation verdict. "severe" never reaches a readable session —
 * the pipeline stops and session status becomes "blocked" instead. */
export type ModerationSeverity = "none" | "mild" | "severe";

export interface ClipOut {
  id: string;
  session_id: string;
  user: UserOut;
  game: string | null;
  title: string | null;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
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

export interface AudiencePersonaReview {
  name: string;
  layer: string;
  profile: string;
  interests: string[];
  hook_score: number;
  completion_probability: number;
  like_probability: number;
  share_probability: number;
  skip_probability: number;
  primary_action: string;
  [key: string]: unknown;
}

/** The persona simulator's output (backend AudienceSimulationOut). */
export interface AudienceSimulation {
  platform: CreatorPlatform;
  requested_target_audience: string | null;
  inferred_niche: string;
  inferred_target_audience: string;
  virality_score: number;
  verdict: "weak" | "mixed" | "promising" | "strong";
  cascade_depth: "target_only" | "adjacent" | "outsider" | "broad_breakout";
  cascade_summary: string;
  metrics: {
    simulated_watch_rate: number;
    simulated_completion_rate: number;
    simulated_like_rate: number;
    simulated_comment_rate: number;
    simulated_save_rate: number;
    simulated_share_rate: number;
  };
  layers: { layer: string; persona_count: number; score: number; threshold: number; cleared_threshold: boolean }[];
  persona_reviews: AudiencePersonaReview[];
  consensus_strengths: string[];
  consensus_risks: string[];
  recommended_changes: string[];
  disclaimer: string;
}

export interface ClipViralityOut {
  clip_id: string;
  status: JobStatus;
  platform: CreatorPlatform;
  result: AudienceSimulation | null;
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
