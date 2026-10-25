# MinedTV Dashboard Backend API Integration

This document is the complete frontend contract for the MinedTV backend. It covers users, uploads, processing status, sessions, clips, feeds, search, playback, export, video analysis, publishing metadata, synthetic audience personas, virality/cascade scoring, and the asynchronous creator-pack flow for clips already stored in MinedTV.

## Quick start

Local API base URL:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

Recommended dashboard flow:

```text
video file
   |
   | multipart POST /creator/analyze (one video/Gemini call)
   v
CreatorPack
   |\
   | \-- render titles, summary, transcript, captions, warnings,
   |     YouTube metadata, and Reddit metadata immediately
   |
   \---- JSON POST /creator/simulate-analysis (one text-only Gemini call)
          |
          \-- render personas, engagement estimates, cascade, risks,
              strengths, and recommended changes
```

Do not upload the video again for personas after `/creator/analyze` succeeds. Keep the returned `CreatorPack` in frontend state and pass it unchanged to `/creator/simulate-analysis`.

## Feature and endpoint summary

| Method | Endpoint | Input | Purpose |
|---|---|---|---|
| `POST` | `/creator/analyze` | Multipart video | Analyze a video and generate the publishing content pack. |
| `POST` | `/creator/simulate-analysis` | JSON containing an existing content pack | Run personas without reading or analyzing the video again. Recommended second step. |
| `POST` | `/creator/simulate` | Multipart video plus persona options | Standalone convenience route that performs analysis and personas in one blocking request. Do not use after `/creator/analyze`. |
| `POST` | `/clips/{clip_id}/creator-pack` | Path parameter | Start asynchronous content-pack generation for a clip already stored in MinedTV. |
| `GET` | `/clips/{clip_id}/creator-pack` | Path parameter | Poll asynchronous content-pack status. |
| `GET` | `/health` | None | API/infrastructure health information. |

## Authentication and CORS

When the deployment has `API_KEYS` configured, send the API key with every creator request:

```http
X-API-Key: your-api-key
```

An invalid or missing key returns:

```json
{
  "detail": "Missing or invalid API key (send X-API-Key)"
}
```

`/health`, `/docs`, `/redoc`, and `/openapi.json` remain public. CORS origins are deployment-configurable. The local development configuration normally permits the local dashboard origin.

Do not embed a production API key in publicly served JavaScript. A production web app should obtain authorization through its own server/session layer or use a backend-for-frontend proxy.

## 1. Analyze an uploaded video

### Request

```http
POST /creator/analyze
Content-Type: multipart/form-data
```

Multipart field:

| Field | Type | Required | Notes |
|---|---|---:|---|
| `video` | File | Yes | Accepted extensions: `.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v`, `.avi`, `.mpeg`, `.mpg`. MIME type must begin with `video/`. |

The default maximum upload size is 500 MB, configurable by the backend. The route is synchronous: it returns only when analysis is complete. There is currently no progress or job-status endpoint for direct uploads.

### Browser example

```ts
async function analyzeVideo(file: File, apiBase: string, apiKey?: string) {
  const form = new FormData();
  form.append("video", file);

  const response = await fetch(`${apiBase}/creator/analyze`, {
    method: "POST",
    headers: apiKey ? { "X-API-Key": apiKey } : undefined,
    body: form,
  });

  const body = await response.json();
  if (!response.ok) {
    throw new Error(readApiError(body, response));
  }
  return body as CreatorPack;
}
```

Do not set the multipart `Content-Type` header manually. The browser must add the boundary.

### Response: `CreatorPack`

```ts
export interface CreatorPack {
  title_options: string[];
  description: string;
  summary: string;
  caption: string;
  youtube: YouTubeMetadata;
  reddit: RedditMetadata;
  transcript: TranscriptCue[];
  key_moments: KeyMoment[];
  hashtags: string[];
  content_warnings: string[];
}

export interface YouTubeMetadata {
  title: string; // Backend enforces a maximum of 100 characters.
  description: string;
  tags: string[];
  chapters: Chapter[];
}

export interface RedditMetadata {
  title: string;
  body: string;
  suggested_subreddits: string[]; // Names do not include "r/".
}

export interface TranscriptCue {
  timestamp: string; // Display value such as "00:12".
  text: string;
}

export interface KeyMoment {
  timestamp: string;
  label: string;
}

export interface Chapter {
  timestamp: string;
  label: string;
}
```

### Meaning of each field

| Field | Display recommendation |
|---|---|
| `title_options` | Alternative titles the creator can copy or select. |
| `description` | Detailed, literal description of what happens in the video. |
| `summary` | Short, direct summary. This is intentionally shorter than `description`. |
| `caption` | General social-media caption. |
| `youtube` | Ready-to-use YouTube title, description, tags, and chapters. |
| `reddit` | Ready-to-use Reddit title/body plus suggested communities. |
| `transcript` | Timestamped detected speech or meaningful audio. It may be empty when no useful audio exists. |
| `key_moments` | Timestamped visual or narrative moments. It may be empty. |
| `hashtags` | Values do not include `#`; add it only for presentation/copying. |
| `content_warnings` | Empty means no warning was identified. These are model-generated suggestions, not a moderation guarantee. |

The uploaded temporary file is deleted after the request. Small files are sent inline to Gemini. Larger files use Gemini's Files API and the remote temporary file is also deleted after analysis.

## 2. Run personas using an existing analysis

This is the recommended persona endpoint.

### Request

```http
POST /creator/simulate-analysis
Content-Type: application/json
```

```ts
export type CreatorPlatform =
  | "general"
  | "youtube"
  | "reddit"
  | "instagram"
  | "tiktok";

export interface AudienceSimulationRequest {
  analysis: CreatorPack;
  platform?: CreatorPlatform;       // Default: "general"
  target_audience?: string | null;  // Maximum 500 characters; null means infer it.
  persona_count?: number | null;    // Integer from 3 through 15; default: 9.
}
```

Example:

```ts
async function simulateAudience(
  analysis: CreatorPack,
  apiBase: string,
  options: {
    platform?: CreatorPlatform;
    targetAudience?: string;
    personaCount?: number;
    apiKey?: string;
  } = {},
) {
  const response = await fetch(`${apiBase}/creator/simulate-analysis`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(options.apiKey ? { "X-API-Key": options.apiKey } : {}),
    },
    body: JSON.stringify({
      analysis,
      platform: options.platform ?? "general",
      target_audience: options.targetAudience?.trim() || null,
      persona_count: options.personaCount ?? 9,
    } satisfies AudienceSimulationRequest),
  });

  const body = await response.json();
  if (!response.ok) {
    throw new Error(readApiError(body, response));
  }
  return body as AudienceSimulation;
}
```

### Response: `AudienceSimulation`

```ts
export type AudienceLayer = "target" | "adjacent" | "outsider";
export type AudienceAction = "like" | "comment" | "save" | "share" | "skip";
export type ViralityVerdict = "weak" | "mixed" | "promising" | "strong";
export type CascadeDepth =
  | "target_only"
  | "adjacent"
  | "outsider"
  | "broad_breakout";

export interface AudienceSimulation {
  platform: CreatorPlatform;
  requested_target_audience: string | null;
  inferred_niche: string;
  inferred_target_audience: string;
  virality_score: number; // 0-100
  verdict: ViralityVerdict;
  cascade_depth: CascadeDepth;
  cascade_summary: string;
  metrics: AudienceMetrics;
  layers: AudienceLayerResult[];
  persona_reviews: PersonaReview[];
  consensus_strengths: string[];
  consensus_risks: string[];
  recommended_changes: string[];
  analysis: CreatorPack;
  disclaimer: string;
}

export interface AudienceMetrics {
  simulated_watch_rate: number;       // Percentage, 0-100.
  simulated_completion_rate: number;  // Percentage, 0-100.
  simulated_like_rate: number;        // Percentage, 0-100.
  simulated_comment_rate: number;     // Percentage, 0-100.
  simulated_save_rate: number;        // Percentage, 0-100.
  simulated_share_rate: number;       // Percentage, 0-100.
  action_distribution: Record<AudienceAction, number>; // Persona counts.
}

export interface AudienceLayerResult {
  layer: AudienceLayer;
  persona_count: number;
  score: number;              // 0-100
  threshold: number;          // 0-100
  exposed_in_cascade: boolean;
  cleared_threshold: boolean;
}

export interface PersonaReview {
  name: string;
  layer: AudienceLayer;
  profile: string;
  interests: string[];
  hook_score: number; // 0-100
  completion_probability: number; // 0-1
  like_probability: number;       // 0-1
  comment_probability: number;    // 0-1
  save_probability: number;       // 0-1
  share_probability: number;      // 0-1
  skip_probability: number;       // 0-1
  primary_action: AudienceAction;
  reaction: string;
  suggested_comment: string | null;
  what_worked: string;
  friction: string;
  recommended_change: string;
}
```

### Persona and cascade interpretation

The panel is divided into three audience layers:

1. `target`: people most likely to care about the inferred or requested topic.
2. `adjacent`: people with related interests who are not the core audience.
3. `outsider`: people with little prior interest in the niche.

The backend calculates the layer scores and cascade locally after Gemini produces the individual reviews. The default propagation thresholds are:

| Layer | Threshold |
|---|---:|
| Target | 55 |
| Adjacent | 50 |
| Outsider | 45 |

`exposed_in_cascade` means the previous layer cleared its threshold, allowing this simulated layer to receive the video. `cleared_threshold` means this layer scored strongly enough to advance the cascade.

Recommended visualization:

- Show `virality_score` and `verdict` together, not the score alone.
- Render `cascade_summary` as the plain-language explanation.
- Render the three `layers` in target -> adjacent -> outsider order.
- Dim a layer when `exposed_in_cascade` is false.
- Label an exposed layer as advanced/stopped using `cleared_threshold`.
- Convert persona probabilities to percentages only in the UI (`value * 100`).
- Display `disclaimer` near the results. These are synthetic reactions, not real analytics or a guaranteed performance forecast.

The top-level engagement metrics are already percentages. Do not multiply those by 100 again.

### Example condensed response

```json
{
  "platform": "general",
  "requested_target_audience": null,
  "inferred_niche": "competitive gaming clips",
  "inferred_target_audience": "Valorant players and FPS viewers",
  "virality_score": 56.5,
  "verdict": "promising",
  "cascade_depth": "outsider",
  "cascade_summary": "The video reached outsiders but did not show broad-breakout strength.",
  "metrics": {
    "simulated_watch_rate": 73.3,
    "simulated_completion_rate": 68.3,
    "simulated_like_rate": 59.7,
    "simulated_comment_rate": 34.7,
    "simulated_save_rate": 24.0,
    "simulated_share_rate": 42.3,
    "action_distribution": {
      "like": 3,
      "comment": 1,
      "save": 0,
      "share": 2,
      "skip": 3
    }
  },
  "layers": [],
  "persona_reviews": [],
  "consensus_strengths": [],
  "consensus_risks": [],
  "recommended_changes": [],
  "analysis": {},
  "disclaimer": "Synthetic persona feedback is a creative testing aid..."
}
```

The repository contains a complete response example at `backend/docs/api-examples/creator.simulate.json`.

## 3. Standalone combined endpoint

`POST /creator/simulate` accepts a video and returns the same `AudienceSimulation` shape. It is useful only when a client wants the final persona result and has not already requested a content pack.

Multipart fields:

| Field | Type | Required | Default |
|---|---|---:|---|
| `video` | File | Yes | - |
| `platform` | CreatorPlatform | No | `general` |
| `target_audience` | String or omitted | No | Inferred |
| `persona_count` | Integer 3-15 | No | 9 |

This endpoint performs video analysis and persona generation sequentially in one blocking request. If the dashboard needs to show the analysis before personas, use the two-step recommended flow instead.

## 4. Existing MinedTV clip flow

If the dashboard is working with a saved `clip_id`, it can create a content pack without asking the user to upload the video again.

Start or reuse the creator-pack job:

```http
POST /clips/{clip_id}/creator-pack
```

The route returns HTTP `202` while processing. It is idempotent: repeated calls reuse an existing ready/in-progress result.

Poll:

```http
GET /clips/{clip_id}/creator-pack
```

Response:

```ts
export interface ClipCreatorPackResult {
  clip_id: string;
  status: "none" | "processing" | "ready" | "failed";
  model: string | null;
  pack: CreatorPack | null;
  error: string | null;
  start_ms: number;
  end_ms: number;
}
```

Suggested polling behavior:

```ts
async function waitForCreatorPack(clipId: string, apiBase: string) {
  await fetch(`${apiBase}/clips/${clipId}/creator-pack`, { method: "POST" });

  for (;;) {
    const response = await fetch(`${apiBase}/clips/${clipId}/creator-pack`);
    const state = (await response.json()) as ClipCreatorPackResult;

    if (state.status === "ready" && state.pack) return state.pack;
    if (state.status === "failed") throw new Error(state.error || "Creator pack failed");
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
}
```

This asynchronous flow requires the full MinedTV stack: database, Redis/worker, and object storage. Once `pack` is ready, it can be passed directly as `analysis` to `/creator/simulate-analysis`.

## Error handling

Common status codes:

| Status | Meaning | Suggested UI behavior |
|---:|---|---|
| `401` | API key missing or invalid | Ask the user to sign in/reconfigure the environment. |
| `413` | Video exceeds the configured upload limit | Show the configured limit from the error message. |
| `422` | Bad extension, MIME type, empty file, invalid platform/count, or malformed JSON | Display the validation detail beside the relevant control. |
| `502` | Gemini returned unusable data or an upstream analysis/simulation failed | Offer Retry without discarding the selected video or existing analysis. |
| `503` | Gemini API key/configuration missing | Show a backend-configuration message rather than retrying automatically. |
| `504` | Gemini processing timeout | Offer Retry and retain the current form/analysis. |

FastAPI errors normally use:

```ts
type ApiErrorBody = {
  detail?: string | Array<{
    loc: Array<string | number>;
    msg: string;
    type: string;
  }>;
};

function readApiError(body: ApiErrorBody, response: Response): string {
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    return body.detail.map(item => `${item.loc.join(".")}: ${item.msg}`).join("; ");
  }
  return `${response.status} ${response.statusText}`;
}
```

## Loading and state-management recommendations

Maintain independent states for the two stages:

```ts
type CreatorDashboardState = {
  selectedVideo: File | null;
  analysisStatus: "idle" | "loading" | "ready" | "error";
  analysis: CreatorPack | null;
  analysisError: string | null;
  simulationStatus: "idle" | "loading" | "ready" | "error";
  simulation: AudienceSimulation | null;
  simulationError: string | null;
};
```

Important behavior:

- Disable Analyze while `/creator/analyze` is in flight.
- Do not start personas automatically unless the product explicitly wants that cost/latency.
- Enable Run Personas only after a valid `CreatorPack` exists.
- Keep the `CreatorPack` when persona generation fails so Retry does not re-upload/reanalyze the video.
- Reset both stages when the user chooses a different video.
- If only platform, target audience, or panel size changes, reuse the same analysis.
- The current backend does not stream partial results.
- An `AbortController` can stop the browser from waiting, but it may not cancel work already executing upstream.

## Observed local performance

Performance varies by video, network, Gemini capacity, deployment region, and model configuration. In local validation with a 322 KB sample video:

| Operation | Observed time |
|---|---:|
| Analyze video | 3.9-8.4 seconds across four runs |
| 3-persona panel | 13.4 seconds |
| 9-persona panel | 8.1 seconds |
| 15-persona panel | 18.7 seconds |

These are development observations, not frontend timeout guarantees. Use a request timeout comfortably above the backend's configured analysis timeout and show a persistent loading state.

## Frontend acceptance checklist

- [ ] General is the default platform.
- [ ] The video is sent only once in the recommended flow.
- [ ] The exact analysis JSON is reused for personas.
- [ ] Analysis remains visible if persona generation fails.
- [ ] Persona probabilities are rendered as `value * 100` percent.
- [ ] Top-level simulated metrics are rendered directly as percentages.
- [ ] Non-exposed cascade layers are visually distinct.
- [ ] Empty transcript, key moments, warnings, and suggested comments are handled gracefully.
- [ ] The synthetic-feedback disclaimer is visible.
- [ ] API error `detail` is shown instead of only "Bad Gateway".
- [ ] API keys are not shipped in public frontend bundles.
- [ ] Mobile layouts handle long descriptions, transcript rows, and persona cards.

## Source-of-truth files

- `backend/app/api/creator.py` - direct creator and persona endpoints.
- `backend/app/schemas.py` - request/response contracts.
- `backend/app/ml/gemini_creator.py` - video analysis engine.
- `backend/app/ml/audience_simulator.py` - persona generation and deterministic cascade scoring.
- `backend/app/api/clips.py` - asynchronous creator-pack endpoints for saved clips.
- `backend/docs/openapi.json` - generated OpenAPI document.
- `backend/docs/api-examples/creator.simulate.json` - complete simulation response example.

---

## Complete backend API reference

The earlier sections explain the AI creator workflow in depth. This section covers every remaining HTTP API and defines every request and response field used by the dashboard.

### Global conventions

#### Headers

| Header | Required when | Meaning |
|---|---|---|
| `X-API-Key` | When the deployment configures `API_KEYS` | Grants access to protected API routes. Do not ship a production key in a public bundle. |
| `X-User-Id` | Routes marked **acting user required** | UUID of the demo user performing the action. This is the current identity mechanism, not secure end-user authentication. |
| `Content-Type: application/json` | JSON request bodies | Standard JSON request. |
| `Content-Type: multipart/form-data` | File search and direct creator uploads | Let the browser set the multipart boundary. |

`X-User-Id` is optional on feed/detail/view routes. When omitted, `liked_by_me` is `null`. When supplied, it must match an existing user or the API returns `401`.

#### Value formats

| Value | Format |
|---|---|
| IDs | UUID strings such as `"123e4567-e89b-12d3-a456-426614174000"`. |
| Datetimes | ISO 8601 strings with timezone when known. |
| Video positions and durations | Integer milliseconds unless the field is a creator timestamp string. |
| Creator timestamps | Display strings such as `"00:12"`; do not use them for precise player seeking. |
| Probabilities | Decimal `0..1`. |
| Creator aggregate rates | Percentages `0..100`. |
| Optional values | Returned as JSON `null`, not omitted, unless noted otherwise. |

#### HTTP response families

- `200`: successful read/update/action.
- `201`: resource created.
- `202`: asynchronous work accepted or already processing.
- `204`: successful deletion with no response body.
- `4xx`: request, identity, ownership, state, or validation problem.
- `5xx`: backend configuration, dependency, or upstream-model problem.

### Shared non-creator response types

These interfaces are the canonical field-level formats used by the endpoint reference below.

#### Users

```ts
export interface UserCreate {
  username: string;         // 2-64 chars; letters, numbers, underscore, dot, or hyphen.
  avatar_url?: string | null;
}

export interface User {
  id: string;               // UUID.
  username: string;
  avatar_url: string | null;
}
```

#### Uploads and sessions

```ts
export interface UploadCreate {
  filename: string;         // Original filename, including extension.
  content_type?: string;    // Default "video/mp4".
  game?: string | null;
  title?: string | null;    // Defaults to filename stem on the backend.
  started_at?: string | null; // ISO 8601 recording start time.
  size_bytes?: number | null; // Non-negative informational value.
}

export interface UploadReservation {
  session_id: string;       // UUID of the newly created session.
  upload_url: string;       // Presigned object-storage URL.
  method: "PUT";
  headers: Record<string, string>; // Required headers for the storage PUT.
  expires_in_s: number;     // Seconds until upload_url expires.
  storage_key: string;      // Internal object key; normally informational to UI.
}

export type SessionStatus =
  | "uploading"
  | "queued"
  | "probing"
  | "segmenting"
  | "thumbnails"
  | "frames"
  | "audio"
  | "highlights"
  | "finalizing"
  | "ready"
  | "failed";

export interface Session {
  id: string;
  user: User;
  game: string | null;
  title: string | null;
  started_at: string | null;
  duration_ms: number | null; // Known after media probing.
  width: number | null;       // Source width in pixels.
  height: number | null;      // Source height in pixels.
  status: SessionStatus;
  last_step: string | null;   // Last completed pipeline step.
  failed_step: string | null; // Step that failed, if status is failed.
  error: string | null;       // Human-readable processing error.
  poster_url: string | null;  // Displayable poster/thumbnail URL when available.
  playlist_url: string | null;// HLS URL when playback is available.
  created_at: string;         // ISO 8601 datetime.
}

export interface SessionStatusEvent {
  session_id: string;
  status: SessionStatus;
  progress: number;           // Fraction 0..1, not percentage.
  steps: string[];            // Ordered pipeline steps.
  last_step: string | null;
  failed_step: string | null;
  error: string | null;
  done: boolean;              // True for ready or failed.
}
```

The current ordered processing steps are:

```ts
["probe", "segment", "thumbnails", "frames", "audio", "highlights", "finalize"]
```

#### Clips, events, transcripts, and engagement

```ts
export type ClipKind = "auto" | "user";

export interface Clip {
  id: string;
  session_id: string;
  user: User;
  game: string | null;
  title: string | null;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  thumbnail_url: string | null;
  playlist_url: string;       // HLS playlist URL.
  status: string;
  kind: ClipKind;
  view_count: number;
  like_count: number;
  liked_by_me: boolean | null;// Null when X-User-Id was not supplied.
  created_at: string;
}

export interface HighlightEvent {
  id: string;
  t_ms: number;               // Position in the source session.
  type: string;               // For example clutch, win, kill, or funny.
  score: number;
  source: string | null;
  metadata: Record<string, unknown>;
}

export interface TranscriptLine {
  id: string;
  start_ms: number;
  end_ms: number;
  speaker: string | null;
  text: string;
}

export interface ClipDetail extends Clip {
  session_duration_ms: number | null;
  events: HighlightEvent[];
  transcript: TranscriptLine[];
}

export interface ClipCreate {
  session_id: string;
  start_ms: number;           // >= 0.
  end_ms: number;             // > start_ms and within the session.
  title?: string | null;      // Maximum 200 characters.
}

export interface ClipPatch {
  title?: string | null;      // Maximum 200 characters.
  start_ms?: number | null;
  end_ms?: number | null;
}

export interface EngagementCounts {
  clip_id: string;
  view_count: number;
  like_count: number;
  liked_by_me: boolean | null;
}

export interface FeedPage {
  items: Clip[];
  next_cursor: string | null; // Supply unchanged to the next request.
}
```

User clips must be at least 1,000 ms long. The range must remain within a processed session.

#### MP4 export

```ts
export interface ExportResult {
  clip_id: string;
  status: "none" | "processing" | "ready" | "failed";
  url: string | null;         // Download URL only when ready.
  error: string | null;       // Failure detail only when failed.
  start_ms: number;
  end_ms: number;
}
```

An export is keyed to the current clip range. If the clip range changes, the new range has its own export state.

#### Search

```ts
export type SearchSignal = "visual" | "speech" | "keyword" | "event";

export interface SearchMoment {
  t_ms: number;               // Absolute moment within the source session.
  offset_ms: number;          // Seek position relative to this result's playlist.
  confidence: number;         // 0..1 and comparable across queries.
  signals: SearchSignal[];
  label: string | null;       // Matching highlight type when available.
  snippet: string | null;     // Matching transcript text when available.
  thumbnail_url: string | null;
}

export interface SearchResult {
  kind: "clip" | "session";
  clip_id: string | null;     // Null for a suggested session window.
  session_id: string;
  match_t_ms: number;         // Exact best match in session time.
  start_ms: number;           // Existing clip or suggested window start.
  end_ms: number;             // Existing clip or suggested window end.
  score: number;              // Raw fusion rank; use only for ordering/debugging.
  confidence: number;         // 0..1 normalized confidence.
  signals: SearchSignal[];
  thumbnail_url: string | null;
  transcript_snippet: string | null;
  playlist_url: string;
  game: string | null;
  title: string | null;
  user: User;
  other_moments_ms: number[];
  moments: SearchMoment[];    // Best moment first.
}

export interface SearchResponse {
  query: string;              // Text query or image:<filename>.
  results: SearchResult[];
  took_ms: number;
  cached: boolean;
}
```

When `kind` is `session`, the backend did not find an existing clip containing the moment. The returned `start_ms..end_ms` is a suggested clip range and `playlist_url` plays that window.

#### Health and warmup

```ts
export interface HealthResponse {
  status: "ok" | "degraded";
  checks: Record<string, string>; // database, redis, and storage details.
}

export interface WarmupResponse {
  status: "warm" | "failed";
  ms: number;
}
```

### Users API

#### `POST /users`

Creates a demo user.

- Content type: `application/json`
- Request: `UserCreate`
- Success: `201 User`
- Acting user: not required

```json
{
  "username": "viraj.dev",
  "avatar_url": "https://example.com/avatar.png"
}
```

Errors include `409` when the username is already taken and `422` for username format/length violations.

#### `GET /users`

Returns `200 User[]`, ordered by username.

Query parameters:

| Parameter | Type | Default | Constraints |
|---|---|---:|---|
| `limit` | Integer | 50 | 1-200 |

#### `GET /users/{user_id}`

Returns `200 User`. Returns `404` when the user does not exist.

#### `GET /users/{user_id}/clips`

Returns `200 FeedPage` containing that user's ready clips, newest first.

| Parameter | Location | Type | Default | Constraints |
|---|---|---|---:|---|
| `user_id` | Path | UUID | - | Required |
| `cursor` | Query | String or null | null | Opaque cursor from the prior response |
| `limit` | Query | Integer | 20 | 1-100 |
| `X-User-Id` | Header | UUID | omitted | Optional; populates `liked_by_me` |

### Upload API

MinedTV's main ingestion flow uploads directly to object storage. The raw video does not pass through the API server.

#### `POST /uploads`

- Content type: `application/json`
- Acting user required: `X-User-Id`
- Request: `UploadCreate`
- Success: `201 UploadReservation`

Accepted extensions: `.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v`, `.avi`, `.flv`, `.ts`.

Complete browser sequence:

```ts
async function uploadSession(file: File, metadata: {
  game?: string;
  title?: string;
  startedAt?: string;
}, apiBase: string, userId: string, apiKey?: string) {
  const commonHeaders = {
    "X-User-Id": userId,
    ...(apiKey ? { "X-API-Key": apiKey } : {}),
  };

  const reserveResponse = await fetch(`${apiBase}/uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...commonHeaders },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "video/mp4",
      game: metadata.game || null,
      title: metadata.title || null,
      started_at: metadata.startedAt || null,
      size_bytes: file.size,
    } satisfies UploadCreate),
  });
  const reservation = (await reserveResponse.json()) as UploadReservation;

  const storageResponse = await fetch(reservation.upload_url, {
    method: reservation.method,
    headers: reservation.headers,
    body: file,
  });
  if (!storageResponse.ok) throw new Error("Storage upload failed");

  const completeResponse = await fetch(
    `${apiBase}/uploads/${reservation.session_id}/complete`,
    { method: "POST", headers: commonHeaders },
  );
  return (await completeResponse.json()) as Session;
}
```

#### `POST /uploads/{session_id}/complete`

Verifies the storage upload and queues media processing.

- Request body: none
- Acting user required
- Success: `202 Session`, normally with `status: "queued"`
- `400`: object was not uploaded to storage
- `403`: session belongs to another user
- `404`: session not found
- `409`: session is no longer in `uploading` state

### Sessions API

#### `GET /sessions/{session_id}`

Returns `200 Session`. Use it for a point-in-time status/detail fetch. Returns `404` for an unknown session.

#### `GET /sessions/{session_id}/status`

Returns a Server-Sent Events stream with media type `text/event-stream`. Each changed status is sent as:

```text
event: status
data: {"session_id":"...","status":"frames","progress":0.57,"steps":[...],"last_step":"thumbnails","failed_step":null,"error":null,"done":false}

```

The payload after `data:` is `SessionStatusEvent`. The stream closes when `done` becomes true. A comment keep-alive is emitted after approximately 15 idle seconds.

```ts
function watchSession(
  sessionId: string,
  apiBase: string,
  onStatus: (status: SessionStatusEvent) => void,
  apiKey?: string,
) {
  // EventSource cannot set X-API-Key; the middleware permits ?api_key= for this case.
  const url = new URL(`${apiBase}/sessions/${sessionId}/status`);
  if (apiKey) url.searchParams.set("api_key", apiKey);
  const source = new EventSource(url);
  source.addEventListener("status", event => {
    const status = JSON.parse((event as MessageEvent).data) as SessionStatusEvent;
    onStatus(status);
    if (status.done) source.close();
  });
  return () => source.close();
}
```

#### `POST /sessions/{session_id}/reprocess`

Retries a failed session from its last completed step, or completely reprocesses a ready session.

- Request body: none
- Acting user required
- Success: `202 SessionStatusEvent`
- `403`: not the session owner
- `404`: session not found
- `409`: session is neither failed nor ready

#### `GET /sessions/{session_id}/playlist.m3u8`

Returns HLS playlist text with content type `application/vnd.apple.mpegurl`.

| Parameter | Type | Default | Meaning |
|---|---|---:|---|
| `start_ms` | Integer >= 0 or omitted | 0 | Requested playback-window start. |
| `end_ms` | Integer > 0 or omitted | Session duration | Requested playback-window end. |

The response is not JSON. Give the URL to hls.js, AVPlayer, ExoPlayer/Media3, or another HLS-capable player. It returns `409` until the session is ready and `422` for an invalid range.

### Clips API

#### `POST /clips`

Creates a clip as a time-range view over a ready session; it does not copy the video.

- Content type: `application/json`
- Acting user required
- Request: `ClipCreate`
- Success: `201 Clip`

```json
{
  "session_id": "123e4567-e89b-12d3-a456-426614174000",
  "start_ms": 12000,
  "end_ms": 42000,
  "title": "Final clutch"
}
```

Returns `404` for an unknown session, `409` when the session is not ready, and `422` for an invalid range.

#### `GET /clips/{clip_id}`

Returns `200 ClipDetail`, including events and overlapping transcript lines. `X-User-Id` is optional and controls `liked_by_me`.

#### `PATCH /clips/{clip_id}`

Renames, trims, or extends a clip.

- Content type: `application/json`
- Acting user required and must own the clip
- Request: `ClipPatch`; send only changed fields
- Success: `200 Clip`

Changing the range also refreshes the clip thumbnail when a suitable frame exists.

#### `DELETE /clips/{clip_id}`

- Acting user required and must own the clip
- Success: `204 No Content`
- Response body: none

Do not call `response.json()` for a `204` response.

#### `GET /clips/{clip_id}/playlist.m3u8`

Returns the clip's HLS playlist as `application/vnd.apple.mpegurl`, not JSON. Returns `409` if session segments do not exist yet.

#### `POST /clips/{clip_id}/like`

- Acting user required
- Request body: none
- Success: `200 EngagementCounts`
- Idempotent: liking an already-liked clip does not increment again

#### `DELETE /clips/{clip_id}/like`

- Acting user required
- Request body: none
- Success: `200 EngagementCounts`
- Idempotent: removing a nonexistent like does not decrement again

#### `POST /clips/{clip_id}/view`

- Acting user optional
- Request body: none
- Success: `200 EngagementCounts`

The backend buffers engagement increments, so always replace displayed counts with the response rather than incrementing optimistically without reconciliation.

#### `POST /clips/{clip_id}/export`

Starts or reuses asynchronous MP4 export.

- Request body: none
- Success: `202 ExportResult`
- Idempotent when already processing or ready

#### `GET /clips/{clip_id}/export`

Returns `200 ExportResult`. Poll until `status` is `ready` or `failed`. When ready, download or share `url`.

Suggested polling:

```ts
async function waitForExport(clipId: string, apiBase: string): Promise<ExportResult> {
  await fetch(`${apiBase}/clips/${clipId}/export`, { method: "POST" });
  for (;;) {
    const response = await fetch(`${apiBase}/clips/${clipId}/export`);
    const state = (await response.json()) as ExportResult;
    if (state.status === "ready") return state;
    if (state.status === "failed") throw new Error(state.error || "Export failed");
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
}
```

#### `POST /clips/{clip_id}/creator-pack`

Starts or reuses asynchronous creator-pack generation for the clip's current range.

- Request body: none
- Success: `202 ClipCreatorPackResult`
- Requires Gemini configuration
- Idempotent when already processing or ready

#### `GET /clips/{clip_id}/creator-pack`

Returns `200 ClipCreatorPackResult`. The complete `ClipCreatorPackResult` and `CreatorPack` field formats are defined earlier in this document. When `status` becomes `ready`, pass `pack` directly to `/creator/simulate-analysis` if persona results are needed.

### Feed API

#### `GET /feed`

Returns `200 FeedPage` of ready clips, newest first.

| Parameter | Location | Type | Default | Constraints/meaning |
|---|---|---|---:|---|
| `cursor` | Query | String or null | null | Opaque cursor from `next_cursor`. |
| `limit` | Query | Integer | 20 | 1-100. |
| `game` | Query | String or null | null | Case-insensitive exact game filter. |
| `X-User-Id` | Header | UUID or omitted | omitted | Enables `liked_by_me`. |

Never construct or modify the cursor. Pass it back exactly as returned. A null `next_cursor` means the end of the feed.

### Search API

#### `GET /search`

Hybrid search across visual frames, transcript meaning/keywords, and highlight events.

Returns `200 SearchResponse`.

| Parameter | Type | Default | Constraints/meaning |
|---|---|---:|---|
| `q` | String | - | Required, 1-300 characters. |
| `game` | String or null | null | Optional game filter. |
| `user_id` | UUID or null | null | Optional owner filter. |
| `from` | ISO datetime or null | null | Optional recording-time lower bound. |
| `to` | ISO datetime or null | null | Optional recording-time upper bound. |
| `limit` | Integer | 20 | 1-50. |
| `nocache` | Boolean | false | Skip the five-minute search cache; intended for testing. |

Example:

```text
GET /search?q=the%20clutch%20on%20Bind&game=Valorant&limit=20
```

Use `confidence` for user-facing match strength. `score` is an internal rank-fusion value and is not comparable between different queries.

#### `POST /search/image`

Finds moments visually similar to a screenshot.

- Content type: `multipart/form-data`
- Success: `200 SearchResponse`
- The response `query` is `image:<filename>` and `cached` is always false

Multipart fields:

| Field | Type | Required | Default/constraint |
|---|---|---:|---|
| `image` | JPEG/PNG file | Yes | Maximum 8 MB; must not be empty. |
| `game` | String | No | No game filter. |
| `user_id` | UUID | No | No owner filter. |
| `limit` | Integer | No | 20; range 1-50. |

### Creator API complete format map

The creator endpoint bodies and all nested response fields are defined in the first half of this document. This map makes their HTTP contracts explicit:

| Endpoint | Request format | Success response |
|---|---|---|
| `POST /creator/analyze` | `multipart/form-data` with required `video` | `200 CreatorPack` |
| `POST /creator/simulate-analysis` | `application/json` `AudienceSimulationRequest` | `200 AudienceSimulation` |
| `POST /creator/simulate` | `multipart/form-data`: `video`, optional `platform`, `target_audience`, `persona_count` | `200 AudienceSimulation` |

`AudienceSimulation.analysis` is the complete `CreatorPack`, not an ID or summary. The frontend may therefore restore both stages from the simulation response alone.

### Operational API

#### `POST /warmup`

Warms the configured embedding model so the first search avoids a cold start.

- Request body: none
- Success: `200 WarmupResponse`
- May take up to approximately 120 seconds on a cold deployment
- `status: "failed"` is still returned with HTTP 200 because warmup is best-effort

Call this on app launch without blocking primary navigation when search latency matters.

#### `GET /health`

Returns `200 HealthResponse`.

Example:

```json
{
  "status": "degraded",
  "checks": {
    "database": "ok",
    "redis": "error: TimeoutError",
    "storage": "ok"
  }
}
```

`degraded` means one or more infrastructure checks failed. The HTTP status remains 200 so monitoring and dashboards must inspect the JSON `status` field.

### Complete endpoint inventory

This checklist is useful when confirming dashboard coverage:

- [ ] `POST /users`
- [ ] `GET /users`
- [ ] `GET /users/{user_id}`
- [ ] `GET /users/{user_id}/clips`
- [ ] `POST /uploads`
- [ ] `POST /uploads/{session_id}/complete`
- [ ] `GET /sessions/{session_id}`
- [ ] `GET /sessions/{session_id}/status`
- [ ] `POST /sessions/{session_id}/reprocess`
- [ ] `GET /sessions/{session_id}/playlist.m3u8`
- [ ] `POST /clips`
- [ ] `GET /clips/{clip_id}`
- [ ] `PATCH /clips/{clip_id}`
- [ ] `DELETE /clips/{clip_id}`
- [ ] `GET /clips/{clip_id}/playlist.m3u8`
- [ ] `POST /clips/{clip_id}/like`
- [ ] `DELETE /clips/{clip_id}/like`
- [ ] `POST /clips/{clip_id}/view`
- [ ] `POST /clips/{clip_id}/export`
- [ ] `GET /clips/{clip_id}/export`
- [ ] `POST /clips/{clip_id}/creator-pack`
- [ ] `GET /clips/{clip_id}/creator-pack`
- [ ] `GET /feed`
- [ ] `GET /search`
- [ ] `POST /search/image`
- [ ] `POST /creator/analyze`
- [ ] `POST /creator/simulate-analysis`
- [ ] `POST /creator/simulate`
- [ ] `POST /warmup`
- [ ] `GET /health`

### Backend-wide frontend implementation notes

- Use the URLs returned by the API instead of constructing storage object URLs.
- Playlist endpoints return text, not JSON.
- Session status is SSE, not a normal JSON polling response.
- Direct upload has three steps: reserve, PUT to storage, complete.
- Creator direct upload is separate and sends multipart data directly to the API.
- Feed pagination is keyset/cursor based, not page-number based.
- Export and saved-clip creator packs are asynchronous polling APIs.
- Direct creator analysis and persona simulation are synchronous APIs.
- Keep millisecond session/clip positions separate from creator display timestamps.
- Treat `content_warnings`, persona results, and virality scores as generated guidance rather than moderation or analytics guarantees.
