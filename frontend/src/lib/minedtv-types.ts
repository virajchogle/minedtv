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

/** Upstream lifecycle values seen on sessions and clips. */
export type UpstreamStatus = string;

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
  view_count: number;
  like_count: number;
  liked_by_me: boolean | null;
  created_at: string;
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
}

export interface UploadOut {
  session_id: string;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  expires_in_s: number;
  storage_key: string;
}
