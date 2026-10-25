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
 * There is no server-side single-clip search filter, so single-video search is
 * a client filter and says so (`scope_enforced`).
 */

import type {
  ClipCreatorPackOut,
  ClipDetailOut,
  ClipOut,
  ClipViralityOut,
  CountsOut,
  CreatorPlatform,
  ExportOut,
  FeedOut,
  MeOut,
  ModerationSeverity,
  PublishState,
  SearchOut,
  ServerConfigOut,
  SessionOut,
  UploadOut,
  UpstreamSearchResult,
  UserOut,
  YouTubePrivacy,
  YouTubeStatusOut,
  YouTubeUploadOut,
} from "@/lib/minedtv-types";

export type { ModerationSeverity, PublishState } from "@/lib/minedtv-types";

/** Same-origin proxy. The upstream host is only ever known to the server. */
export const API_BASE_URL = "/api/minedtv";

export type ProcessingStatus =
  | "pending"
  | "extracting_frames"
  | "analyzing"
  | "indexing"
  | "complete"
  | "visual_only"
  | "failed"
  /** Transcript moderation found severe content; the pipeline stopped before
   * creating a clip. Terminal, distinct from a technical "failed". */
  | "blocked";

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
  /** "clip" for real clips; "session" when only the raw recording is known (e.g. mid-processing). */
  kind: "clip" | "session";
  /** null for sessions, which have no publish state of their own. */
  publish_state: PublishState | null;
  published_at: string | null;
  owner_id: string | null;
  liked_by_me: boolean;
  start_ms: number;
  end_ms: number;
  /** Transcript moderation flagged this 18+ ("mild" or "severe" verdict). */
  age_restricted: boolean;
  moderation_severity: ModerationSeverity;
  /** Owner-visible one-line reason; never the policy itself. */
  moderation_reason: string | null;
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
  /** Backend confidence, 0..1, comparable across queries. */
  confidence: number;
  /** Every matching moment in this clip, best first, with its own evidence. */
  moments: MomentView[];
  game: string | null;
  uploader: string | null;
}

export interface MomentView {
  /** Seconds into the clip's playlist (what the player seeks to). */
  offset_seconds: number;
  confidence: number;
  signals: string[];
  label: string | null;
  snippet: string | null;
  thumbnail_url: string | null;
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
  // The backend identifies the acting user by X-User-Id (demo identity, no passwords yet).
  const headers = new Headers(init?.headers);
  const me = getCurrentUser();
  if (me && !headers.has("X-User-Id")) headers.set("X-User-Id", me.id);
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers, cache: "no-store" });
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
  probing: "extracting_frames",
  thumbnails: "extracting_frames",
  frames: "indexing",
  audio: "analyzing",
  moderating: "analyzing",
  highlights: "analyzing",
  finalizing: "indexing",
  uploading: "pending",
  queued: "pending",
  pending: "pending",
  created: "pending",
  failed: "failed",
  error: "failed",
  blocked: "blocked",
};

const toStatus = (raw: string | null | undefined): ProcessingStatus =>
  STATUS_MAP[(raw ?? "").toLowerCase()] ?? "indexing";

// ── match strength ───────────────────────────────────────────────────────────

/**
 * Display bands for the confidence the service returns.
 *
 * The number itself is the backend's; these cut-points are a presentation
 * choice made here so the UI can group results, and they are reported as such
 * on the Settings page. They are not model probabilities and nothing
 * here invents a score.
 */
export const BAND_STRONG = 0.75;
export const BAND_MODERATE = 0.5;
export const BAND_WEAK = 0.3;

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
  keyword: "Exact words in voice chat",
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
    kind: "clip",
    publish_state: clip.publish_state ?? "published",
    published_at: clip.published_at ?? null,
    owner_id: clip.user?.id ?? null,
    liked_by_me: Boolean(clip.liked_by_me),
    start_ms: clip.start_ms,
    end_ms: clip.end_ms,
    age_restricted: Boolean(clip.age_restricted),
    moderation_severity: clip.moderation_severity ?? "none",
    moderation_reason: clip.moderation_reason ?? null,
  };
}

function sessionToVideo(session: SessionOut): Video {
  // `session.status` is already authoritative ("failed" vs "blocked" vs anything
  // else) — don't override it from failed_step, which is set for both.
  const status = toStatus(session.status);
  return {
    video_id: session.id,
    filename: session.title ?? session.id,
    title: session.title ?? session.game ?? "Untitled session",
    duration_seconds: ms(session.duration_ms),
    file_size_bytes: 0,
    upload_date: session.created_at,
    processing_status: status,
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
    kind: "session",
    publish_state: null,
    published_at: null,
    owner_id: session.user?.id ?? null,
    liked_by_me: false,
    start_ms: 0,
    end_ms: session.duration_ms ?? 0,
    age_restricted: Boolean(session.age_restricted),
    moderation_severity: session.moderation_severity ?? "none",
    moderation_reason: session.moderation_reason ?? null,
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

function clipSegments(clip: ClipDetailOut): Segment[] {
  return [
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
}

/**
 * A clip with its transcript lines and detected events, from one request.
 * An id may also be a session (search returns those for moments no clip
 * covers); sessions have no segment route, so they come back with none.
 */
export async function fetchVideoWithSegments(
  id: string
): Promise<{ video: Video; segments: Segment[] }> {
  let clip: ClipDetailOut;
  try {
    clip = await request<ClipDetailOut>(`/clips/${id}`);
  } catch (clipError) {
    try {
      return { video: sessionToVideo(await request<SessionOut>(`/sessions/${id}`)), segments: [] };
    } catch {
      throw clipError; // "not found" for the clip is the more useful message
    }
  }
  const video = clipToVideo(clip);
  video.frame_count = clip.frame_count ?? 0;
  video.segment_count = clip.transcript?.length ?? 0;
  return { video, segments: clipSegments(clip) };
}

export async function fetchVideo(id: string): Promise<Video> {
  return (await fetchVideoWithSegments(id)).video;
}

/** Models, search thresholds, feature flags and limits the server runs with. */
export const fetchServerConfig = () => request<ServerConfigOut>("/config");

/**
 * HLS manifest for a clip, served through the proxy so the API key is applied.
 * The player needs hls.js outside Safari.
 */
export const videoStreamUrl = (clipId: string): string =>
  `${API_BASE_URL}/clips/${clipId}/playlist.m3u8`;

/** Whole-session HLS (for session-kind ids that have no clip yet). */
export const sessionStreamUrl = (sessionId: string): string =>
  `${API_BASE_URL}/sessions/${sessionId}/playlist.m3u8`;

/** The right playlist for whatever the Video wraps. */
export const streamUrlFor = (video: Video): string =>
  video.kind === "session" ? sessionStreamUrl(video.video_id) : videoStreamUrl(video.video_id);

// ── search ───────────────────────────────────────────────────────────────────

function toResult(hit: UpstreamSearchResult, index: number): SearchResult {
  return {
    moment_id: `${hit.session_id}:${hit.match_t_ms}`,
    video_id: hit.clip_id ?? hit.session_id,
    video_title: hit.title ?? hit.game ?? "Untitled clip",
    rank: index + 1,
    start_seconds: ms(hit.start_ms),
    end_seconds: ms(hit.end_ms),
    // Playlists start at start_ms, so the player seeks to the offset within the clip.
    // Clip playlists start at the clip's start, so seek to the offset inside the clip. Session
    // hits (no clip contains the moment; owner-only) open the whole session, so seek absolutely.
    seek_seconds: hit.clip_id
      ? ms(hit.moments?.[0]?.offset_ms ?? hit.match_t_ms - hit.start_ms)
      : ms(hit.match_t_ms),
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
    confidence: hit.confidence,
    moments: (hit.moments ?? []).map((m) => ({
      offset_seconds: ms(m.offset_ms),
      confidence: m.confidence,
      signals: m.signals,
      label: m.label,
      snippet: m.snippet,
      thumbnail_url: m.thumbnail_url,
    })),
    game: hit.game,
    uploader: hit.user?.username ?? null,
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
  /** Only the current user's clips, including their drafts and "ready" clips. */
  mine?: boolean;
  game?: string | null;
}): Promise<SearchResponse> {
  const { query, scope, videoId, limit = 12, signal, mine = false, game } = options;
  const scoped = scope === "video" && Boolean(videoId);

  const params = new URLSearchParams({
    q: query,
    // Over-fetch when narrowing locally, or the filter has little to work with.
    limit: String(scoped ? Math.max(limit * 5, 50) : Math.min(limit, 50)),
  });
  const me = getCurrentUser();
  // Single-video search on your own draft needs the owner scope, or the draft is invisible.
  if ((mine || scoped) && me) params.set("user_id", me.id);
  if (game) params.set("game", game);

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
  onProgress: (percent: number) => void,
  meta: { title?: string; game?: string } = {}
): Promise<UploadResponse> {
  const ticket = await request<UploadOut>("/uploads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "video/mp4",
      title: meta.title?.trim() || file.name.replace(/\.[^.]+$/, ""),
      game: meta.game?.trim() || null,
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

// ── identity ─────────────────────────────────────────────────────────────────

/**
 * Two things are tracked here:
 *  - the signed-in account (`getAccount`), whose login token lives in an
 *    httpOnly cookie the proxy forwards — browser code never sees it;
 *  - the user requests act as (`getCurrentUser`), sent as X-User-Id. For a
 *    normal account that's always itself; dev accounts can switch to anyone.
 * Both are cached in localStorage so components can read them synchronously;
 * `refreshAccount()` re-checks the cookie with the server on load.
 */
const USER_KEY = "minedtv-user";
const ACCOUNT_KEY = "minedtv-account";
export const USER_CHANGED_EVENT = "minedtv-user-changed";

function readStored<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeStored(key: string, value: unknown): void {
  try {
    if (value) window.localStorage.setItem(key, JSON.stringify(value));
    else window.localStorage.removeItem(key);
  } catch {
    /* storage may be unavailable (private mode); the session just won't persist */
  }
}

/** Who requests act as. */
export function getCurrentUser(): UserOut | null {
  return readStored<UserOut>(USER_KEY);
}

/** The signed-in account, or null when signed out. */
export function getAccount(): MeOut | null {
  return readStored<MeOut>(ACCOUNT_KEY);
}

/** Act as another user. Only dev accounts may pick someone other than themselves. */
export function setCurrentUser(user: UserOut | null): void {
  writeStored(USER_KEY, user);
  window.dispatchEvent(new Event(USER_CHANGED_EVENT));
}

function setAccount(account: MeOut | null): void {
  writeStored(ACCOUNT_KEY, account);
  const acting = getCurrentUser();
  // Signed out, or a normal account: requests act as the account itself.
  if (!account || !account.is_dev || !acting) writeStored(USER_KEY, account);
  window.dispatchEvent(new Event(USER_CHANGED_EVENT));
}

async function authRequest<T>(action: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/auth/${action}`, {
      method: body === undefined && action === "me" ? "GET" : "POST",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new Error("Could not reach the MinedTV API.");
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = humanizeValidation(data.detail);
    } catch {
      /* keep the status-line message */
    }
    throw new Error(message);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** FastAPI's 422 detail list, as one readable line. */
function humanizeValidation(detail: unknown[]): string {
  const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined;
  const field = first?.loc?.[first.loc.length - 1];
  if (field === "email") return "Enter a valid email address.";
  if (field === "username") return "Usernames are 2–64 letters, numbers, dots, dashes or underscores.";
  if (field === "password") return "Passwords need at least 8 characters.";
  return first?.msg ?? "Check the form and try again.";
}

export async function signIn(login: string, password: string): Promise<MeOut> {
  const account = await authRequest<MeOut>("login", { login, password });
  setAccount(account);
  return account;
}

export async function signUp(username: string, email: string, password: string): Promise<MeOut> {
  const account = await authRequest<MeOut>("signup", { username, email, password });
  setAccount(account);
  return account;
}

export async function signOut(): Promise<void> {
  await authRequest<void>("logout", {}).catch(() => {
    /* the cookie is cleared server-side; local state is cleared regardless */
  });
  setAccount(null);
}

/** Re-checks the login cookie with the server (call once on load). */
export async function refreshAccount(): Promise<MeOut | null> {
  try {
    const account = await authRequest<MeOut>("me");
    setAccount(account);
    return account;
  } catch (e) {
    // Only a definite "not signed in" clears state; a network blip keeps it.
    if (e instanceof Error && /not signed in|expired|invalid|malformed|no longer exists/i.test(e.message)) {
      setAccount(null);
    }
    return null;
  }
}

export const fetchUsers = () => request<UserOut[]>("/users?limit=200");

/** A password-less demo user (dev accounts act as these). */
export const createUser = (username: string) =>
  request<UserOut>("/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });

// ── my clips and publishing ──────────────────────────────────────────────────

export type ClipBucket = "all" | "draft" | "ready" | "published" | "unpublished";

/** The current user's clips. Owners see every bucket; nobody else sees unpublished ones. */
export async function fetchMyVideos(bucket: ClipBucket = "all", limit = 60): Promise<Video[]> {
  const me = getCurrentUser();
  if (!me) return [];
  const feed = await request<FeedOut>(`/users/${me.id}/clips?state=${bucket}&limit=${limit}`);
  return Array.isArray(feed?.items) ? feed.items.map(clipToVideo) : [];
}

/** Clips the pipeline made for a session, found via the owner's clip list. */
export async function fetchClipsForSession(sessionId: string): Promise<Video[]> {
  return (await fetchMyVideos("all", 100)).filter((v) => v.session_id === sessionId);
}

export const publishClip = (clipId: string) =>
  request<ClipOut>(`/clips/${clipId}/publish`, { method: "POST" }).then(clipToVideo);
export const unpublishClip = (clipId: string) =>
  request<ClipOut>(`/clips/${clipId}/unpublish`, { method: "POST" }).then(clipToVideo);
export const markClipReady = (clipId: string) =>
  request<ClipOut>(`/clips/${clipId}/mark-ready`, { method: "POST" }).then(clipToVideo);

export const setLiked = (clipId: string, liked: boolean) =>
  request<CountsOut>(`/clips/${clipId}/like`, { method: liked ? "POST" : "DELETE" });

// ── background jobs: MP4 export, AI creator pack, virality ───────────────────

export const startExport = (clipId: string) =>
  request<ExportOut>(`/clips/${clipId}/export`, { method: "POST" });
export const getExport = (clipId: string) => request<ExportOut>(`/clips/${clipId}/export`);

export const startCreatorPack = (clipId: string) =>
  request<ClipCreatorPackOut>(`/clips/${clipId}/creator-pack`, { method: "POST" });
export const getCreatorPack = (clipId: string) =>
  request<ClipCreatorPackOut>(`/clips/${clipId}/creator-pack`);

export interface ViralityOptions {
  platform: CreatorPlatform;
  target_audience?: string | null;
  persona_count?: number | null;
}

function viralityQuery(o: ViralityOptions): string {
  const params = new URLSearchParams({ platform: o.platform });
  if (o.target_audience) params.set("target_audience", o.target_audience);
  if (o.persona_count) params.set("persona_count", String(o.persona_count));
  return params.toString();
}

/** Synthetic audience panel. The backend only runs it on unpublished (draft/ready) clips. */
export const startVirality = (clipId: string, o: ViralityOptions) =>
  request<ClipViralityOut>(`/clips/${clipId}/virality`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      platform: o.platform,
      target_audience: o.target_audience || null,
      persona_count: o.persona_count || null,
    }),
  });
export const getVirality = (clipId: string, o: ViralityOptions) =>
  request<ClipViralityOut>(`/clips/${clipId}/virality?${viralityQuery(o)}`);

// ── YouTube posting ──────────────────────────────────────────────────────────

export const getYouTubeStatus = () => request<YouTubeStatusOut>("/youtube/status");

/** Google's consent page for the acting user; it redirects back to /library. */
export const getYouTubeConnectUrl = () =>
  request<{ auth_url: string }>("/youtube/connect").then((r) => r.auth_url);

export const disconnectYouTube = () => request<void>("/youtube/connection", { method: "DELETE" });

/** Past and in-flight uploads of a clip, newest first. */
export const getYouTubeUploads = (clipId: string) =>
  request<YouTubeUploadOut[]>(`/clips/${clipId}/youtube`);

/** Title, description and tags default to the clip's AI creator pack. */
export const postToYouTube = (
  clipId: string,
  body: { privacy: YouTubePrivacy; title?: string | null; description?: string | null; tags?: string[] | null }
) =>
  request<YouTubeUploadOut>(`/clips/${clipId}/youtube`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

/** Wakes the GPU embedder so the first search isn't a cold start. Fire and forget. */
export function warmup(): void {
  void request<unknown>("/warmup", { method: "POST" }).catch(() => {
    /* best effort */
  });
}

// ── screenshot search ────────────────────────────────────────────────────────

export async function searchByImage(
  image: File,
  options: { mine?: boolean; game?: string | null; limit?: number } = {}
): Promise<SearchResponse> {
  const form = new FormData();
  form.set("image", image);
  form.set("limit", String(options.limit ?? 12));
  const me = getCurrentUser();
  if (options.mine && me) form.set("user_id", me.id);
  if (options.game) form.set("game", options.game);
  const started = performance.now();
  const raw = await request<SearchOut>("/search/image", { method: "POST", body: form });
  const hits = Array.isArray(raw?.results) ? raw.results : [];
  const results = hits.map(toResult);
  const bucket_counts: Record<MatchBucket, number> = { strong: 0, moderate: 0, weak: 0, no_reliable_match: 0 };
  for (const result of results) bucket_counts[result.match.bucket] += 1;
  return {
    query: raw?.query ?? `image:${image.name}`,
    scope: "gallery",
    video_id: null,
    results,
    total_results: results.length,
    bucket_counts,
    signals_used: [...new Set(hits.flatMap((hit) => hit.signals))],
    degraded: [],
    pipeline: "deployed screenshot search",
    latency_ms: raw?.took_ms ?? Math.round(performance.now() - started),
    searchable_videos: new Set(hits.map((hit) => hit.session_id)).size,
    scope_enforced: "server",
    cached: false,
  };
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
  blocked: { label: "Blocked", tone: "error" },
};
