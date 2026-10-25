/**
 * MinedTV client — adapter over the deployed team API.
 *
 * The UI was built against a videos/moments/scope contract; the deployed
 * service speaks sessions, clips, HLS playlists and millisecond offsets. This
 * module is the single translation point between the two, so components keep
 * their existing props and only this file changes when the upstream contract
 * moves. Upstream shapes live in `lib/minedtv-types.ts`.
 *
 * Requests go to `/api/minedtv/...`, a Next route handler that attaches the
 * `X-API-Key` server-side. The key is never present in the browser bundle.
 *
 * Two upstream gaps are surfaced honestly rather than papered over:
 *  - there is no server-side scope filter, so single-video search is a client
 *    filter and says so (`scope_enforced`);
 *  - there is no retrieval-config endpoint, so the settings and eval pages get
 *    the display bands this file applies, not model internals.
 */

import type {
  ClipDetailOut,
  ClipOut,
  FeedOut,
  SearchOut,
  SessionOut,
  UploadOut,
  UpstreamSearchResult,
} from "@/lib/minedtv-types";

/** Same-origin proxy. The upstream host is only ever known to the server. */
export const API_BASE_URL = "/api/minedtv";

export type ProcessingStatus =
  | "pending"
  | "extracting_frames"
  | "analyzing"
  | "indexing"
  | "complete"
  | "visual_only"
  | "failed";

export type MatchBucket = "strong" | "moderate" | "weak" | "no_reliable_match";

export type SearchScope = "gallery" | "video";

export interface Video {
  video_id: string;
  filename: string;
  title: string;
  duration_seconds: number;
  file_size_bytes: number;
  upload_date: string;
  processing_status: ProcessingStatus;
  processing_error: string | null;
  searchable: boolean;
  summary: string | null;
  topics: string[];
  frame_count: number;
  segment_count: number;
  thumbnail_url: string | null;
  /** HLS manifest for playback. Upstream serves clips as m3u8, not MP4. */
  playlist_url: string | null;
  /** Upstream session this clip belongs to; needed for reprocess and scoping. */
  session_id: string | null;
  uploader: string | null;
  game: string | null;
  view_count: number;
  like_count: number;
  publish_state: "draft" | "ready" | "published" | null;
  published_at: string | null;
}

export interface SignalBreakdown {
  name: string;
  raw: number;
  calibrated: number;
  weight: number;
  detail: string;
}

export interface MatchAnalysis {
  bucket: MatchBucket;
  label: string;
  evidence_score: number;
  signals: SignalBreakdown[];
  reasons: string[];
}

export interface SearchResult {
  moment_id: string;
  video_id: string;
  video_title: string;
  rank: number;
  start_seconds: number;
  end_seconds: number;
  seek_seconds: number;
  frame_id: string | null;
  thumbnail_url: string | null;
  transcript: string | null;
  scene_description: string | null;
  matched_terms: string[];
  fusion_score: number;
  match: MatchAnalysis;
  playlist_url: string | null;
  session_id: string;
  /** Additional matching offsets in the same clip, in seconds. */
  other_moments: number[];
}

export interface SearchResponse {
  query: string;
  scope: SearchScope;
  video_id: string | null;
  results: SearchResult[];
  total_results: number;
  bucket_counts: Record<MatchBucket, number>;
  signals_used: string[];
  degraded: string[];
  pipeline: string;
  latency_ms: number;
  searchable_videos: number;
  /**
   * "server" when the upstream applied the scope, "client" when we filtered
   * its results ourselves. The UI shows this so a narrowed result set is never
   * mistaken for a scoped query.
   */
  scope_enforced: "server" | "client";
  cached: boolean;
}

export interface Segment {
  segment_id: string;
  kind: "transcript" | "scene";
  start_seconds: number;
  end_seconds: number;
  transcript: string | null;
  scene_description: string | null;
}

export interface SearchConfig {
  buckets: { strong: number; moderate: number; weak: number };
  weights: Record<string, number>;
  calibration: Record<string, [number, number]>;
  models: Record<string, string>;
  gemini_enabled: boolean;
  /** Upstream health checks, when the service reports them. */
  checks: Record<string, string>;
  backend: string;
}

export interface UploadResponse {
  video_id: string;
  filename: string;
  title: string;
  duration_seconds: number;
  file_size_bytes: number;
  status: string;
  message: string;
}

// ── transport ────────────────────────────────────────────────────────────────

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, cache: "no-store" });
  } catch {
    throw new Error("Could not reach the MinedTV API.");
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* keep the status-line message */
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * Upstream already returns absolute URLs for thumbnails and playlists, so this
 * only guards against a relative path slipping through.
 */
export const absoluteUrl = (path: string | null): string | null => {
  if (!path) return null;
  return /^https?:\/\//.test(path) ? path : `${API_BASE_URL}${path}`;
};

// ── status mapping ───────────────────────────────────────────────────────────

/**
 * Upstream statuses, lowercased, onto the vocabulary the UI renders. Anything
 * unrecognised is treated as in-progress rather than guessed at.
 */
const STATUS_MAP: Record<string, ProcessingStatus> = {
  ready: "complete",
  complete: "complete",
  completed: "complete",
  done: "complete",
  processing: "indexing",
  transcribing: "analyzing",
  analyzing: "analyzing",
  segmenting: "extracting_frames",
  uploading: "pending",
  queued: "pending",
  pending: "pending",
  created: "pending",
  failed: "failed",
  error: "failed",
};

const toStatus = (raw: string | null | undefined): ProcessingStatus =>
  STATUS_MAP[(raw ?? "").toLowerCase()] ?? "indexing";

// ── match strength ───────────────────────────────────────────────────────────

/**
 * Display bands for the confidence the service returns.
 *
 * The number itself is the backend's; these cut-points are a presentation
 * choice made here so the UI can group results, and they are reported as such
 * through `fetchSearchConfig`. They are not model probabilities and nothing
 * here invents a score.
 */
const BAND_STRONG = 0.75;
const BAND_MODERATE = 0.5;
const BAND_WEAK = 0.3;

const BUCKET_LABELS: Record<MatchBucket, string> = {
  strong: "Strong match",
  moderate: "Moderate match",
  weak: "Weak match",
  no_reliable_match: "No reliable match",
};

/** Upstream signal identifiers rendered as something a person can read. */
const SIGNAL_LABELS: Record<string, string> = {
  visual: "Visual similarity",
  speech: "Spoken content",
  text: "Text and metadata",
  event: "Detected event",
  title: "Title match",
  game: "Game match",
};

function bucketFor(confidence: number): MatchBucket {
  if (confidence >= BAND_STRONG) return "strong";
  if (confidence >= BAND_MODERATE) return "moderate";
  if (confidence >= BAND_WEAK) return "weak";
  return "no_reliable_match";
}

function analyzeMatch(hit: UpstreamSearchResult): MatchAnalysis {
  const bucket = bucketFor(hit.confidence);
  const signals: SignalBreakdown[] = hit.signals.map((name) => ({
    name,
    // Upstream reports which signals fired but not their individual
    // contributions, so per-signal numbers are left at the overall values
    // rather than being split up on a guess.
    raw: hit.score,
    calibrated: hit.confidence,
    weight: 1 / Math.max(1, hit.signals.length),
    detail: SIGNAL_LABELS[name] ?? name,
  }));

  const reasons: string[] = [];
  if (hit.signals.length > 0) {
    reasons.push(
      `Matched on ${hit.signals.map((s) => SIGNAL_LABELS[s] ?? s).join(", ").toLowerCase()}.`
    );
  }
  if (hit.moments.length > 1) {
    reasons.push(`${hit.moments.length} matching moments in this clip.`);
  }
  if (bucket === "no_reliable_match") {
    reasons.push("Confidence is below the threshold we treat as a reliable match.");
  }

  return {
    bucket,
    label: BUCKET_LABELS[bucket],
    evidence_score: hit.confidence,
    signals,
    reasons,
  };
}

// ── clips and sessions → Video ───────────────────────────────────────────────

const ms = (value: number | null | undefined) => (value ?? 0) / 1000;

function clipToVideo(clip: ClipOut): Video {
  const status = toStatus(clip.status);
  return {
    video_id: clip.id,
    filename: clip.title ?? clip.id,
    title: clip.title ?? clip.game ?? "Untitled clip",
    duration_seconds: ms(clip.duration_ms),
    // Upstream does not expose byte size for clips.
    file_size_bytes: 0,
    upload_date: clip.created_at,
    processing_status: status,
    processing_error: null,
    searchable: status === "complete",
    summary: null,
    topics: clip.game ? [clip.game] : [],
    frame_count: 0,
    segment_count: 0,
    thumbnail_url: clip.thumbnail_url,
    playlist_url: clip.playlist_url,
    session_id: clip.session_id,
    uploader: clip.user?.username ?? null,
    game: clip.game,
    view_count: clip.view_count,
    like_count: clip.like_count,
    publish_state: clip.publish_state ?? "published",
    published_at: clip.published_at ?? null,
  };
}

function sessionToVideo(session: SessionOut): Video {
  const status = toStatus(session.status);
  return {
    video_id: session.id,
    filename: session.title ?? session.id,
    title: session.title ?? session.game ?? "Untitled session",
    duration_seconds: ms(session.duration_ms),
    file_size_bytes: 0,
    upload_date: session.created_at,
    processing_status: session.failed_step ? "failed" : status,
    processing_error: session.error,
    searchable: status === "complete",
    summary: null,
    topics: session.game ? [session.game] : [],
    frame_count: 0,
    segment_count: 0,
    thumbnail_url: session.poster_url,
    playlist_url: session.playlist_url,
    session_id: session.id,
    uploader: session.user?.username ?? null,
    game: session.game,
    view_count: 0,
    like_count: 0,
    publish_state: null,
    published_at: null,
  };
}

// ── reads ────────────────────────────────────────────────────────────────────

/**
 * The library listing. Upstream has no "list every session" route, so the feed
 * of clips is the browsable collection.
 */
export async function fetchVideos(limit = 40): Promise<Video[]> {
  const feed = await request<FeedOut>(`/feed?limit=${limit}`);
  return Array.isArray(feed?.items) ? feed.items.map(clipToVideo) : [];
}

/**
 * An id may be either a clip or a session: search returns session ids for
 * session-kind hits, while the feed returns clip ids. Clips are tried first
 * because they are what the UI links to most often.
 */
export async function fetchVideo(id: string): Promise<Video> {
  try {
    const clip = await request<ClipDetailOut>(`/clips/${id}`);
    const video = clipToVideo(clip);
    video.segment_count = clip.transcript?.length ?? 0;
    video.frame_count = clip.events?.length ?? 0;
    return video;
  } catch {
    return sessionToVideo(await request<SessionOut>(`/sessions/${id}`));
  }
}

/**
 * Transcript cues and detected events, both presented as segments. Sessions
 * have no segment route upstream, so an id that is not a clip yields none.
 */
export async function fetchSegments(
  id: string
): Promise<{ video_id: string; count: number; segments: Segment[] }> {
  let clip: ClipDetailOut;
  try {
    clip = await request<ClipDetailOut>(`/clips/${id}`);
  } catch {
    return { video_id: id, count: 0, segments: [] };
  }

  const segments: Segment[] = [
    ...(clip.transcript ?? []).map((cue) => ({
      segment_id: cue.id,
      kind: "transcript" as const,
      start_seconds: ms(cue.start_ms),
      end_seconds: ms(cue.end_ms),
      transcript: cue.speaker ? `${cue.speaker}: ${cue.text}` : cue.text,
      scene_description: null,
    })),
    ...(clip.events ?? []).map((event) => ({
      segment_id: event.id,
      kind: "scene" as const,
      start_seconds: ms(event.t_ms),
      end_seconds: ms(event.t_ms),
      transcript: null,
      scene_description: event.type,
    })),
  ].sort((a, b) => a.start_seconds - b.start_seconds);

  return { video_id: id, count: segments.length, segments };
}

/**
 * Upstream has no retrieval-config endpoint. What is returned describes the
 * display bands applied in this file plus the service's own health checks —
 * it deliberately does not claim to report model internals.
 */
export async function fetchSearchConfig(): Promise<SearchConfig> {
  let checks: Record<string, string> = {};
  try {
    const health = await request<{ status: string; checks?: Record<string, string> }>(
      "/health"
    );
    checks = health.checks ?? {};
  } catch {
    /* health is informational here */
  }

  return {
    buckets: { strong: BAND_STRONG, moderate: BAND_MODERATE, weak: BAND_WEAK },
    weights: {},
    calibration: {},
    models: {},
    gemini_enabled: false,
    checks,
    backend: "deployed MinedTV API",
  };
}

/**
 * HLS manifest for a clip, served through the proxy so the API key is applied.
 * The player needs hls.js outside Safari.
 */
export const videoStreamUrl = (clipId: string): string =>
  `${API_BASE_URL}/clips/${clipId}/playlist.m3u8`;

// ── search ───────────────────────────────────────────────────────────────────

function toResult(hit: UpstreamSearchResult, index: number): SearchResult {
  return {
    moment_id: `${hit.session_id}:${hit.match_t_ms}`,
    video_id: hit.clip_id ?? hit.session_id,
    video_title: hit.title ?? hit.game ?? "Untitled clip",
    rank: index + 1,
    start_seconds: ms(hit.start_ms),
    end_seconds: ms(hit.end_ms),
    seek_seconds: ms(hit.match_t_ms),
    frame_id: null,
    thumbnail_url: hit.thumbnail_url,
    transcript: hit.transcript_snippet,
    scene_description: hit.moments.find((m) => m.label)?.label ?? null,
    matched_terms: [],
    fusion_score: hit.score,
    match: analyzeMatch(hit),
    playlist_url: hit.playlist_url,
    session_id: hit.session_id,
    other_moments: (hit.other_moments_ms ?? []).map(ms),
  };
}

/**
 * One entry point for both modes.
 *
 * Gallery search maps straight onto `GET /search`. Single-video search has no
 * upstream equivalent — the service filters by game and user, not by clip or
 * session — so it over-fetches and filters here, and reports
 * `scope_enforced: "client"` so the UI can say so plainly.
 */
export async function searchVideos(options: {
  query: string;
  scope: SearchScope;
  videoId?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<SearchResponse> {
  const { query, scope, videoId, limit = 12, signal } = options;
  const scoped = scope === "video" && Boolean(videoId);

  const params = new URLSearchParams({
    q: query,
    // Over-fetch when narrowing locally, or the filter has little to work with.
    limit: String(scoped ? Math.max(limit * 5, 50) : limit),
  });

  const started = performance.now();
  const raw = await request<SearchOut>(`/search?${params}`, { signal });
  const elapsed = Math.round(performance.now() - started);

  let hits = Array.isArray(raw?.results) ? raw.results : [];
  if (scoped) {
    hits = hits
      .filter((hit) => hit.clip_id === videoId || hit.session_id === videoId)
      .slice(0, limit);
  }

  const results = hits.map(toResult);
  const bucket_counts: Record<MatchBucket, number> = {
    strong: 0,
    moderate: 0,
    weak: 0,
    no_reliable_match: 0,
  };
  for (const result of results) bucket_counts[result.match.bucket] += 1;

  const signals_used = [...new Set(hits.flatMap((hit) => hit.signals))];

  return {
    query: raw?.query ?? query,
    scope,
    video_id: videoId ?? null,
    results,
    total_results: results.length,
    bucket_counts,
    signals_used,
    degraded: [],
    pipeline: raw?.cached ? "deployed hybrid search (cached)" : "deployed hybrid search",
    latency_ms: raw?.took_ms ?? elapsed,
    searchable_videos: new Set(hits.map((hit) => hit.session_id)).size,
    scope_enforced: scoped ? "client" : "server",
    cached: Boolean(raw?.cached),
  };
}

// ── writes ───────────────────────────────────────────────────────────────────

export const deleteVideo = (clipId: string) =>
  request<void>(`/clips/${clipId}`, { method: "DELETE" });

/** Upstream reprocesses whole sessions, not clips. */
export const reindexVideo = (sessionId: string) =>
  request<Record<string, unknown>>(`/sessions/${sessionId}/reprocess`, {
    method: "POST",
  });

export const recordView = (clipId: string) =>
  request<unknown>(`/clips/${clipId}/view`, { method: "POST" }).catch(() => {
    /* view counting must never interrupt playback */
  });

/**
 * Three-step upload: ask the API for a signed URL, PUT the bytes straight to
 * storage, then tell the API the object has landed. The bytes never pass
 * through our server, and the signed URL needs no API key.
 */
export async function uploadVideo(
  file: File,
  onProgress: (percent: number) => void
): Promise<UploadResponse> {
  const ticket = await request<UploadOut>("/uploads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "video/mp4",
      title: file.name.replace(/\.[^.]+$/, ""),
      size_bytes: file.size,
    }),
  });

  await putWithProgress(ticket, file, onProgress);

  await request<unknown>(`/uploads/${ticket.session_id}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });

  return {
    video_id: ticket.session_id,
    filename: file.name,
    title: file.name.replace(/\.[^.]+$/, ""),
    duration_seconds: 0,
    file_size_bytes: file.size,
    status: "pending",
    message: "Upload complete. The API is processing this session.",
  };
}

function putWithProgress(
  ticket: UploadOut,
  file: File,
  onProgress: (percent: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(ticket.method || "PUT", ticket.upload_url);
    for (const [name, value] of Object.entries(ticket.headers ?? {})) {
      xhr.setRequestHeader(name, value);
    }

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`Upload to storage failed (HTTP ${xhr.status}).`));
    });
    xhr.addEventListener("error", () =>
      reject(new Error("Network error while uploading to storage."))
    );
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelled.")));
    xhr.send(file);
  });
}

// ── formatting ───────────────────────────────────────────────────────────────

export function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

export function formatDuration(seconds: number): string {
  return formatTimestamp(seconds);
}

export function formatUploadDate(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) {
    const weeks = Math.floor(days / 7);
    return `${weeks} week${weeks > 1 ? "s" : ""} ago`;
  }
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export const STATUS_COPY: Record<
  ProcessingStatus,
  { label: string; tone: "ok" | "partial" | "working" | "error" }
> = {
  pending: { label: "Queued", tone: "working" },
  extracting_frames: { label: "Segmenting", tone: "working" },
  analyzing: { label: "Transcribing", tone: "working" },
  indexing: { label: "Processing", tone: "working" },
  complete: { label: "Ready", tone: "ok" },
  visual_only: { label: "Visual only", tone: "partial" },
  failed: { label: "Failed", tone: "error" },
};
