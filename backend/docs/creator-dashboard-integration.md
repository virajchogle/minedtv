# MinedTV Dashboard Backend API Integration

This document is the complete frontend contract for the MinedTV backend. It covers accounts, users, uploads, processing and moderation, sessions, clips, feeds, search, playback, exports, comments, follows, notifications, analytics, YouTube publishing, video analysis, publishing metadata, synthetic audience personas, frame virality, and the captioned highlight-montage flow.

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
| `POST` | `/creator/virality` | Multipart video plus persona options | Sample the video's frame curve once and blend it with one audience-persona panel. |
| `POST` | `/creator/highlights` | Multipart video | Score the full video once and return one captioned mobile montage containing its main moments. |
| `POST` | `/clips/{clip_id}/highlights` | JSON options | Start/reuse an asynchronous portrait AI-share render for a stored clip. Owner only. |
| `GET` | `/clips/{clip_id}/highlights` | Matching query options | Poll highlight status, stage, progress, and the ready review payload. |
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

`/health`, `/docs`, `/redoc`, `/openapi.json`, `/youtube/callback`, and HLS playlist URLs remain exempt from API-key checks. CORS origins are deployment-configurable. The local development configuration normally permits the local dashboard origin.

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
  persona_score: number | null; // Score before frame blending; null only on older stored results.
  scoring_version: string;
  video_evidence: VideoViralityEvidence | null;
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
  score_samples: number[]; // Multi-panel clip virality runs; empty for direct one-panel simulation.
}

export interface VideoViralityEvidence {
  algorithm_version: string;
  duration_ms: number;
  frames_analyzed: number;
  frame_score: number;      // Aggregate frame-curve score, 0-100.
  peak_score: number;       // Strongest sampled frame, 0-100.
  hook_score: number;       // Strongest opening signal, 0-100.
  sustained_score: number;  // 75th-percentile frame strength, 0-100.
  coverage: number;         // Fraction 0-1 of frames supporting a strong moment.
  moments: VideoViralityMoment[];
}

export interface VideoViralityMoment {
  t_ms: number;
  context_start_ms: number;
  context_end_ms: number;
  score: number;
  visual_score: number;
  novelty_score: number;
  speech_score: number;
  visibility_score: number;
  scene_score: number;
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

### Frame-aware direct video virality

`POST /creator/virality` accepts the same multipart fields as `/creator/simulate`, but adds deterministic evidence from the video's full frame curve. Use this endpoint for a standalone “upload a video and get its virality” feature.

The backend saves the upload once, then runs one Gemini video-content analysis and one local frame-sampling/embedding pass in parallel. The local pass reuses the highlight features' visibility, novelty, sustained scene, transcript reaction, adaptive context, and meaningful-peak filtering. Sampling adapts downward for long videos and is capped by `CREATOR_VIRALITY_MAX_FRAMES` (240 by default). After both finish, the backend gives the compact `VideoViralityEvidence` to one persona-panel request. It never makes one Gemini call per frame or persona.

The final `virality_score` blends `persona_score` with `video_evidence.frame_score`. The default is 75% persona cascade and 25% frame evidence, configurable with `CREATOR_VIRALITY_FRAME_WEIGHT`. The response is `200 AudienceSimulation`; see `backend/docs/api-examples/creator.virality.json` for a complete example.

This direct route requires FFmpeg/FFprobe, the configured embedder, and Gemini, but does not require Postgres, Redis, object storage, or an account.

## 4. Generate a direct-upload highlight montage

`POST /creator/highlights` is a synchronous, database-free upload endpoint. It samples and embeds the source frames once, scores visual relevance, novelty, visibility, and sustained scene strength, and returns one 720x1280 MP4. `mode=single` creates one adaptive 10-25 second continuous moment; `mode=montage` keeps 4-10 seconds around each significant peak and joins those ranges chronologically. Sampling adapts downward and is capped by `STANDALONE_HIGHLIGHT_MAX_FRAMES`, so long uploads do not create an unbounded number of decoded images. The assembled audio is transcribed once, so selecting more moments does not create one caption-model request per moment.

### Request

```http
POST /creator/highlights
Content-Type: multipart/form-data
```

| Field | Type | Required | Notes |
|---|---|---:|---|
| `video` | Video file | Yes | Same extensions, MIME validation, and configured upload limit as `/creator/analyze`. |
| `mode` | `single \| montage` | No | Defaults to `montage` for backward compatibility. |
| `captions` | Boolean | No | Defaults to `true`; set false to skip caption generation and burn-in. |
| `caption_style` | `bold \| minimal \| gamer` | No | Defaults to `bold`. |

### Response: `DirectHighlights`

```ts
export interface DirectHighlights {
  run_id: string;                    // UUID; assets expire after the configured TTL.
  filename: string;
  duration_ms: number;               // Original source duration.
  width: number;                     // Original source width.
  height: number;                    // Original source height.
  frames_analyzed: number;
  algorithm_version: string;
  scores: DirectHighlightFrame[];    // Timeline/debug data for every sampled frame.
  clips: DirectHighlightClip[];      // Currently one finished montage.
}

export interface DirectHighlightFrame {
  frame_id: string;
  t_ms: number;                      // Position in the original source.
  score: number;                     // Combined 0..1 score.
  visual_score: number;              // Relative semantic/shareability signal.
  novelty_score: number;             // Change from neighboring sampled frames.
  visibility_score: number;          // Absolute readability/luminance signal.
  scene_score: number;               // Sustained strength around this frame.
  selected: boolean;                 // True when this peak contributes to the montage.
  thumbnail_url: string | null;      // Present only for selected peaks.
}

export interface DirectHighlightMoment {
  index: number;                     // 1-based chronological order in the montage.
  source_start_ms: number;
  source_end_ms: number;
  duration_ms: number;
  score: number;                     // Selected peak's 0..1 score.
  thumbnail_url: string;
}

export interface DirectHighlightClip {
  index: number;                     // Currently 1.
  title: string;                     // "The highlight montage".
  start_ms: number;                  // 0 on the assembled montage timeline.
  end_ms: number;                    // Equal to duration_ms.
  duration_ms: number;               // Sum of included moment durations.
  score: number;                     // Best included peak score.
  video_url: string;                 // Inline/playback MP4 URL.
  download_url: string;              // Same asset with Content-Disposition download.
  thumbnail_url: string;             // Thumbnail for the strongest included moment.
  width: number;                     // Normally 720.
  height: number;                    // Normally 1280.
  captions_burned: boolean;
  caption_count: number;
  caption_source: "none" | "transcriber" | "gemini";
  moments: DirectHighlightMoment[];  // Every source range in chronological order.
}
```

Asset routes returned by this response:

- `GET /creator/highlights/{run_id}/clips/{index}.mp4` returns the MP4. Add `?download=true` to request a download filename.
- `GET /creator/highlights/{run_id}/frames/{frame_id}.jpg` returns a selected peak thumbnail.
- Missing or expired assets return `404`. Direct outputs expire after `STANDALONE_HIGHLIGHT_TTL_S` (24 hours by default).
- This flow requires FFmpeg/FFprobe and the configured embedder, but does not require Postgres, Redis, object storage, a user, or the persona simulator.

Complete sample: `backend/docs/api-examples/creator.highlights.json`.

## 5. Generate an AI-share highlight for a stored clip

Use this flow for Android Share â†’ Enhance with AI. It does not upload the source again and does not keep a mobile request open while FFmpeg and Gemini run. The job reuses the clip export and creator pack, plus the frame embeddings, transcript, and highlight events already produced by the upload pipeline.

Start or reuse an option-specific render:

```http
POST /clips/{clip_id}/highlights
Content-Type: application/json
X-User-Id: {owner_id}

{
  "platform": "tiktok",
  "mode": "single",
  "captions": true,
  "caption_style": "bold",
  "hook": true
}
```

The route returns `202`. Poll with the same options as query parameters:

```http
GET /clips/{clip_id}/highlights?platform=tiktok&mode=single&captions=true&caption_style=bold&hook=true
```

`status` is `none`, `processing`, `ready`, or `failed`. During processing, `stage` is `queued`, `exporting`, `analyzing`, `selecting`, `captioning`, or `rendering`; `progress` is always 0..1. Failed jobs include a JSON `error`. Repeating POST with the same clip range and options reuses the current job or ready object-storage result.

```ts
export interface ClipHighlightsResult {
  clip_id: string;
  status: "none" | "processing" | "ready" | "failed";
  stage: "queued" | "exporting" | "analyzing" | "selecting" | "captioning" | "rendering";
  progress: number;
  error: string | null;
  start_ms: number;
  end_ms: number;
  platform: "general" | "youtube" | "reddit" | "instagram" | "tiktok";
  mode: "single" | "montage";
  captions_enabled: boolean;
  caption_style: "bold" | "minimal" | "gamer";
  hook_enabled: boolean;
  algorithm_version: string | null;
  video_url: string | null;
  download_url: string | null;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  frames_analyzed: number;
  captions_burned: boolean;
  moments: Array<{
    source_start_ms: number;         // Relative to the stored clip.
    source_end_ms: number;
    score: number;
    reason: string;
  }>;
  captions: Array<{
    start_ms: number;                // Relative to the rendered output.
    end_ms: number;
    text: string;
    kind: "hook" | "speech" | "moment";
  }>;
  summary: string | null;
  suggested_caption: string | null;
  hashtags: string[];
}
```

When speech is absent, captions fall back to the creator pack's first title as a 2.5-second hook and its key-moment labels. The app can use `captions.length` for its before/after screen, `moments[].reason` for â€œwhy these editsâ€, and `suggested_caption`/`hashtags` for editable post copy. Outputs are H.264/AAC, yuv420p, 720x1280, and use absolute object-storage URLs.

Configured limits are returned from `GET /config` as `highlight_max_minutes`, `highlight_max_source_mb`, and `highlight_max_sampled_frames`. The defaults accept clips up to ten minutes and cap scoring at 240 sampled frames.

## 6. Existing MinedTV clip flow

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
| `401` | API key missing/invalid, or a route requires an acting account | Distinguish server access from account login using the returned `detail`. |
| `403` | The acting account does not own the requested private resource | Keep the user signed in, but hide/disable the owner-only action. |
| `404` | Resource is missing, expired, or intentionally hidden from this viewer | Return to the relevant list and refresh it. |
| `409` | Resource exists but is in the wrong state for the action | Show the backend detail, such as “session not ready” or “connect YouTube first.” |
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
    input?: unknown;
    ctx?: Record<string, unknown>;
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

- `backend/app/main.py` - application setup plus health, configuration, and warmup endpoints.
- `backend/app/api/accounts.py` - signup, login, current-account, and logout endpoints.
- `backend/app/api/creator.py` - direct creator, persona, and standalone montage endpoints.
- `backend/app/api/uploads.py`, `sessions.py`, and `clips.py` - persisted video workflow.
- `backend/app/api/users.py`, `social.py`, `notifications.py`, and `analytics.py` - profiles and social/dashboard APIs.
- `backend/app/api/feed.py` and `search.py` - discovery APIs.
- `backend/app/api/youtube.py` - YouTube OAuth connection and clip posting.
- `backend/app/schemas.py` - request/response contracts.
- `backend/app/ml/gemini_creator.py` - video analysis engine.
- `backend/app/ml/audience_simulator.py` - persona generation and deterministic cascade scoring.
- `backend/app/services/standalone_highlights.py` - direct-upload montage selection and rendering.
- `backend/app/services/video_persona_virality.py` - one-pass frame evidence for direct persona virality.
- `backend/app/worker/frame_virality.py` - persisted-session frame scoring and generated clips.
- `backend/docs/openapi.json` - generated OpenAPI document.
- `backend/docs/api-examples/` - generated success-response examples for JSON endpoints.

---

## Complete backend API reference

The earlier sections explain the AI creator workflow in depth. This section covers every remaining HTTP API and defines every request and response field used by the dashboard.

### Global conventions

#### Headers

| Header | Required when | Meaning |
|---|---|---|
| `X-API-Key` | When the deployment configures `API_KEYS` | Grants access to protected API routes. Do not ship a production key in a public bundle. |
| `Authorization: Bearer <token>` | Signed-in routes when `REQUIRE_LOGIN=true` | Token returned by `/auth/signup` or `/auth/login`. It identifies the account behind the request. |
| `X-User-Id` | Optional acting-user override | UUID of the user the request acts as. A normal signed-in user may use only their own ID; dev accounts can impersonate. When login is disabled, this remains available for demos. |
| `X-Viewer-Id` | Optional on `POST /clips/{id}/view` | Stable anonymous viewer identifier. A viewer counts at most once per clip per 30 minutes. |
| `Content-Type: application/json` | JSON request bodies | Standard JSON request. |
| `Content-Type: multipart/form-data` | File search and direct creator uploads | Let the browser set the multipart boundary. |

Acting-user resolution is: allowed `X-User-Id`, otherwise the Bearer-token account, otherwise anonymous. Routes using an acting user return `401` when no identity can be resolved. Owner-only actions return `403` for another user. `X-User-Id` is optional on feed/detail/view routes; when no user is resolved, `liked_by_me`, `followed_by_me`, and similar viewer-specific values are `null`.

The API-key middleware is separate from account authentication. Production may require both `X-API-Key` and a Bearer token. `/health`, `/docs`, `/redoc`, `/openapi.json`, the OAuth callback, and HLS playlists bypass API-key checks. `/config` contains no secrets but still requires `X-API-Key` when API keys are configured.

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

export interface Profile extends User {
  follower_count: number;
  following_count: number;
  published_clip_count: number;
  followed_by_me: boolean | null;
  follows_me: boolean | null;
}

export interface SignupRequest {
  username: string;         // Same 2-64 character rules as UserCreate.
  email: string;
  password: string;         // 8-200 characters.
  birth_date: string;       // YYYY-MM-DD; required for 18+ content gating.
}

export interface LoginRequest {
  login: string;            // Username or email.
  password: string;
}

export interface Me extends User {
  email: string | null;
  is_dev: boolean;
  can_act_as: boolean;
  birth_date: string | null;
  is_adult: boolean;
}

export interface AuthResponse {
  token: string;
  expires_at: string;
  user: Me;
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
  | "moderating"
  | "highlights"
  | "finalizing"
  | "ready"
  | "failed"
  | "blocked";

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
  moderation_severity: "none" | "mild" | "severe";
  moderation_reason: string | null; // Owner-visible one-line explanation.
  age_restricted: boolean;
  moderation_violations: ModerationViolation[];
}

export interface ModerationViolation {
  category: string;
  timestamp_ms: number | null; // Source position; null for non-localized findings.
  note: string;
}

export interface SessionStatusEvent {
  session_id: string;
  status: SessionStatus;
  progress: number;           // Fraction 0..1, not percentage.
  steps: string[];            // Ordered pipeline steps.
  last_step: string | null;
  failed_step: string | null;
  error: string | null;
  done: boolean;              // True for ready, failed, or blocked.
  moderation_severity: "none" | "mild" | "severe";
  age_restricted: boolean;
  moderation_violations: ModerationViolation[];
}
```

The current ordered processing steps are:

```ts
["probe", "segment", "thumbnails", "frames", "audio", "moderate", "highlights", "finalize"]
```

`mild` content can finish processing but is age-restricted. A `severe` verdict stops the pipeline with `status: "blocked"`; the owner can see the reason and timestamped violations. Do not treat `blocked` as a retriable infrastructure failure.

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
  generation_source: "pipeline" | "frame_virality" | null;
  publish_state: "draft" | "ready" | "published";
  published_at: string | null;
  view_count: number;
  like_count: number;
  liked_by_me: boolean | null;// Null when X-User-Id was not supplied.
  comment_count: number;
  youtube_url: string | null;
  age_restricted: boolean;
  moderation_severity: "none" | "mild" | "severe";
  moderation_reason: string | null; // Owner-visible only.
  moderation_violations: ModerationViolation[];
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
  frame_count: number;
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

`publish_state` controls visibility: `draft` and `ready` are owner-only, while `published` appears in feeds/search/profile pages. The legacy `ready` state means queued/eligible for YouTube posting; it is still private on MinedTV. `generation_source` is `pipeline` for normal automatic clips, `frame_virality` for on-demand frame-ranked clips, and `null` for manually created clips.

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

#### Frame-ranked session highlights

```ts
export interface FrameHighlightsRequest {
  count?: number | null;             // 1-10; backend default when omitted.
  clip_duration_ms?: number | null;  // 3,000-120,000; backend default when omitted.
}

export interface FrameViralityPoint {
  frame_id: string;
  t_ms: number;
  score: number;
  visual_score: number;
  novelty_score: number;
  event_score: number;
  speech_score: number;
  visibility_score: number;
  scene_score: number;
  selected: boolean;
  thumbnail_url: string | null;
}

export interface FrameHighlightsResult {
  session_id: string;
  status: "none" | "processing" | "ready" | "failed";
  requested_count: number;
  clip_duration_ms: number;
  algorithm_version: string;
  error: string | null;
  scores: FrameViralityPoint[];
  clips: Clip[];                     // Draft clips generated from selected peaks.
  updated_at: string | null;
}
```

#### Comments, follows, and notifications

```ts
export interface CommentCreate {
  body: string;                      // 1-2,000 characters.
  parent_id?: string | null;         // One level of replies.
}

export interface Comment {
  id: string;
  clip_id: string;
  user: User;
  body: string;
  parent_id: string | null;
  created_at: string;
  reply_count: number;
  replies: Comment[];                // Oldest first; populated on top-level items.
  can_delete: boolean | null;        // Viewer-specific.
}

export interface CommentsPage {
  items: Comment[];                  // Top-level comments newest first.
  next_cursor: string | null;
  total: number;                     // Top-level comments plus replies.
}

export interface FollowResult {
  user_id: string;
  following: boolean;
  follower_count: number;
}

export interface UsersPage {
  items: User[];
  next_cursor: string | null;
}

export interface NotificationClip {
  id: string;
  title: string | null;
  thumbnail_url: string | null;
}

export interface Notification {
  id: string;
  type: "like" | "comment" | "reply" | "follow" | "upload_ready" | "virality_ready" | "youtube_posted";
  message: string;                   // Ready-to-display backend text.
  actor: User | null;
  clip: NotificationClip | null;
  comment_id: string | null;
  session_id: string | null;
  data: Record<string, unknown>;
  read: boolean;
  created_at: string;
}

export interface NotificationsPage {
  items: Notification[];
  next_cursor: string | null;
  unread_count: number;
}

export interface UnreadCount { unread_count: number }
```

#### Creator analytics

```ts
export interface AnalyticsTotals {
  views: number;
  likes: number;
  comments: number;
  new_followers: number;
}

export interface AnalyticsDay extends AnalyticsTotals { day: string }

export interface ViralitySummary {
  status: "none" | "processing" | "ready" | "failed";
  score: number | null;
  verdict: string | null;
  score_samples: number[];
}

export interface ClipAnalytics {
  clip: Clip;
  period_views: number;
  period_likes: number;
  period_comments: number;
  virality: ViralitySummary;
}

export interface Analytics {
  days: number;
  start: string;                     // UTC date, YYYY-MM-DD.
  end: string;
  tracking_since: string | null;
  lifetime: AnalyticsTotals;
  period: AnalyticsTotals;
  previous_period: AnalyticsTotals;
  follower_count: number;
  daily: AnalyticsDay[];             // Zero-filled, oldest first.
  clips: ClipAnalytics[];            // All owned clips, newest first.
}
```

#### YouTube publishing

```ts
export interface YouTubeStatus {
  configured: boolean;
  connected: boolean;
  channel_id: string | null;
  channel_title: string | null;
}

export interface YouTubePostRequest {
  title?: string | null;
  description?: string | null;
  tags?: string[] | null;
  privacy?: "private" | "unlisted" | "public"; // Default private.
}

export interface YouTubeUpload {
  id: string;
  clip_id: string;
  status: "queued" | "uploading" | "published" | "failed";
  privacy: "private" | "unlisted" | "public";
  title: string;
  description: string;
  tags: string[];
  video_id: string | null;
  url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}
```

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

### Authentication API

#### `POST /auth/signup`

Creates an account and immediately returns a login token.

- Request: `SignupRequest`
- Success: `201 AuthResponse`
- `409`: username or email already exists
- `422`: invalid username/email, password shorter than 8 characters, or future birth date

```json
{
  "username": "nova",
  "email": "nova@example.com",
  "password": "correct-horse-battery-staple",
  "birth_date": "2001-04-17"
}
```

#### `POST /auth/login`

- Request: `LoginRequest`; `login` accepts username or email
- Success: `200 AuthResponse`
- `401`: wrong username/email or password

Store `token` in the client session and send it as `Authorization: Bearer <token>`. `expires_at` is the exact expiry time.

#### `GET /auth/me`

Returns `200 Me` for the Bearer-token account. It intentionally returns the signed-in account rather than an impersonated `X-User-Id` user. Returns `401` without a valid token.

#### `POST /auth/logout`

Returns `204`. Tokens are stateless; the client must delete its local token. Calling logout does not revoke already issued tokens server-side.

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

Returns `200 Profile`. When an acting user is available, `followed_by_me` and `follows_me` are populated; otherwise they are `null`. Returns `404` when the user does not exist.

#### `GET /users/{user_id}/clips`

Returns `200 FeedPage` containing that user's ready clips, newest first.

| Parameter | Location | Type | Default | Constraints |
|---|---|---|---:|---|
| `user_id` | Path | UUID | - | Required |
| `cursor` | Query | String or null | null | Opaque cursor from the prior response |
| `limit` | Query | Integer | 20 | 1-100 |
| `state` | Query | `all`, `draft`, `ready`, `published`, `unpublished` | `all` | Honored only for the owner; everyone else sees published clips only. |
| `X-User-Id` | Header | UUID | omitted | Optional; populates `liked_by_me` |

#### `POST /users/{user_id}/follow`

Follows a user and returns `200 FollowResult`. Acting user required. The operation is idempotent, creates a notification only the first time, and returns `422` when attempting to follow yourself.

#### `DELETE /users/{user_id}/follow`

Unfollows a user and returns `200 FollowResult`. Acting user required and idempotent.

#### `GET /users/{user_id}/followers`

Returns `200 UsersPage`, newest follow first. Query parameters: opaque `cursor` and `limit` (default 30, range 1-100).

#### `GET /users/{user_id}/following`

Returns `200 UsersPage` for accounts this user follows, using the same cursor and limit rules.

#### `GET /users/{user_id}/analytics`

Owner-only creator analytics. Returns `200 Analytics`; another user or anonymous request receives `403`.

| Parameter | Type | Default | Constraints |
|---|---|---:|---|
| `days` | Integer | 30 | 7-180 |

`period` covers the requested UTC date range and `previous_period` covers the immediately preceding range of equal length. `tracking_since` explains when daily view history starts; lifetime totals can include older aggregate counts. Each `clips[].virality` summarizes the YouTube persona run for that clip.

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

#### `POST /sessions/{session_id}/frame-highlights`

Starts or reuses frame-ranked highlight generation for a ready session owned by the acting user.

- Request: optional JSON `FrameHighlightsRequest` (`{}` uses backend defaults)
- Success: `202 FrameHighlightsResult`
- Reuses sampled frame embeddings, event detections, transcript cues, and persisted visibility values from the normal pipeline; it does not decode/upload the source again
- Existing pipeline/manual clips are preserved; generated clips use `generation_source: "frame_virality"`
- `403`: not the owner; `404`: session missing; `409`: session not ready

#### `GET /sessions/{session_id}/frame-highlights`

Returns `200 FrameHighlightsResult`. Poll until `status` is `ready` or `failed`. When ready, `scores` contains every frame/component score and `clips` contains the generated draft clips. Repeating POST with unchanged options reuses the stored run.

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

#### `POST /clips/{clip_id}/publish`

Owner-only. Returns `200 Clip` with `publish_state: "published"`, exposes it in public feeds/search/profile, and starts the default YouTube persona/virality check when Gemini is configured. A follow-up job failure does not make publishing fail.

#### `POST /clips/{clip_id}/unpublish`

Owner-only. Returns `200 Clip` with `publish_state: "draft"`; the clip becomes private again.

#### `POST /clips/{clip_id}/mark-ready`

Owner-only. Returns `200 Clip` with `publish_state: "ready"`. This is a private legacy/YouTube queue state and does not publish the clip on MinedTV.

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

The owner viewing their own clip does not increase the count. Other signed-in users are deduplicated by user ID; anonymous viewers should send a stable `X-Viewer-Id`. The same viewer counts at most once per clip per 30-minute window. The backend buffers engagement increments, so always replace displayed counts with the response rather than incrementing optimistically without reconciliation.

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

#### `POST /clips/{clip_id}/virality`

Runs the persona panel asynchronously for any clip owned by the acting user. Request body:

```ts
interface ClipViralityRequest {
  platform?: "general" | "youtube" | "reddit" | "instagram" | "tiktok"; // Default general.
  target_audience?: string | null;
  persona_count?: number | null; // 3-15; backend default when omitted.
}
```

Returns `202 ClipViralityResult`:

```ts
interface ClipViralityResult {
  clip_id: string;
  status: "none" | "processing" | "ready" | "failed";
  platform: string;
  result: AudienceSimulation | null;
  error: string | null;
  start_ms: number;
  end_ms: number;
}
```

The job builds/reuses the creator pack first. Poll GET with exactly the same platform, target audience, and persona count.

#### `GET /clips/{clip_id}/virality`

Owner-only polling endpoint. Query parameters mirror the POST body; defaults are `platform=general`, no explicit target audience, and the configured persona count. Returns `200 ClipViralityResult`.

#### `GET /clips/{clip_id}/comments`

Returns `200 CommentsPage`. It accepts `cursor` and `limit` (default 20, range 1-100). The top-level list is newest first; each item's `replies` are oldest first. Private clips are visible only to their owner.

#### `POST /clips/{clip_id}/comments`

Acting user required. Request: `CommentCreate`; success: `201 Comment`. `parent_id` must refer to a top-level comment on the same clip. It notifies the clip owner and, for replies, the parent author.

#### `DELETE /comments/{comment_id}`

Returns `204`. Allowed for the comment author or clip owner. Deleting a top-level comment also deletes its replies.

#### `POST /clips/{clip_id}/youtube`

Owner-only asynchronous YouTube upload. Requires a connected YouTube account and `publish_state` of `ready` or `published`.

- Request: `YouTubePostRequest`; omitted title/description/tags fall back to the saved AI creator pack and then clip metadata
- Success: `202 YouTubeUpload`
- Reuses an existing queued/uploading job rather than creating duplicates
- Poll `GET /clips/{clip_id}/youtube`
- `409`: channel not connected or clip not ready/published; `503`: server OAuth configuration missing

#### `GET /clips/{clip_id}/youtube`

Returns `200 YouTubeUpload[]` for the acting user's posts of this clip, newest first. A successful row has `status: "published"`, a `video_id`, and a public/watch `url`; a failed row has `error`.

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

Published clips marked `age_restricted` are excluded for anonymous viewers and signed-in accounts under 18. They are included only for a signed-in adult account.

#### `GET /feed/following`

Returns `200 FeedPage` containing published clips from accounts the acting user follows, newest first. Authentication is required. It accepts the same opaque `cursor` and `limit` parameters as `/feed` but has no `game` filter. The same age gate applies.

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
| `POST /creator/virality` | Same multipart fields; frame analysis runs locally in parallel | `200 AudienceSimulation` with `video_evidence` |
| `POST /creator/highlights` | `multipart/form-data` with required `video` | `200 DirectHighlights` |
| `GET /creator/highlights/{run_id}/clips/{index}.mp4` | Optional `download` Boolean query | MP4 bytes (`video/mp4`) |
| `GET /creator/highlights/{run_id}/frames/{frame_id}.jpg` | No body | JPEG bytes (`image/jpeg`) |

`AudienceSimulation.analysis` is the complete `CreatorPack`, not an ID or summary. The frontend may therefore restore both stages from the simulation response alone.

The direct-highlight response and every nested frame, moment, and clip field are defined in section 4. Its asset routes are temporary: a `404` means the run expired or the identifier is invalid. The clip `download_url` is the same MP4 route with `download=true`, which adds a download filename.

### Notifications API

All notification routes require the acting account.

#### `GET /notifications`

Returns `200 NotificationsPage`, newest first.

| Parameter | Type | Default | Meaning |
|---|---|---:|---|
| `cursor` | String or null | null | Opaque `next_cursor` from the previous response. |
| `limit` | Integer | 30 | Range 1-100. |
| `unread_only` | Boolean | false | When true, return only unread notifications. |

Each item contains a backend-generated `message` ready to render, optional actor/clip/comment/session links, machine-readable `data`, and `read`. `unread_count` is the account's total unread count, not merely the unread items on the current page.

#### `GET /notifications/unread-count`

Returns `200 UnreadCount`. This small response is suitable for polling an inbox badge.

#### `POST /notifications/read`

Request and response:

```ts
interface MarkNotificationsRead {
  ids?: string[] | null; // Notification UUIDs belonging to the acting user.
  all?: boolean;         // Default false. When true, ids is ignored.
}

interface UnreadCount {
  unread_count: number;
}
```

Returns `200 UnreadCount` after updating. Sending neither IDs nor `all: true` is a safe no-op.

### YouTube connection API

These endpoints connect the acting account's channel. Actual clip-posting endpoints are documented under Clips API.

#### `GET /youtube/status`

Returns `200 YouTubeStatus`. `configured` reports whether this backend deployment has OAuth credentials; `connected` reports whether the acting user completed the flow. Channel fields are null while disconnected.

#### `GET /youtube/connect`

Returns `200 YouTubeConnect`:

```ts
interface YouTubeConnect {
  auth_url: string;
}
```

Open `auth_url` in a browser or popup. The signed OAuth state binds the callback to this user. The route returns `503` when YouTube OAuth is not configured.

#### `GET /youtube/callback`

This is Google's public browser callback and is intentionally omitted from OpenAPI. Query parameters are `code`, `state`, and optional `error`. It returns either a `303` redirect to the configured frontend library page or a small HTML success/error page; it never returns a dashboard JSON model. The frontend normally does not call it directly.

#### `DELETE /youtube/connection`

Returns `200 YouTubeStatus` with `connected: false`. It attempts to revoke the Google token and always forgets the local connection, so calling it while already disconnected is safe.

### Operational API

#### `GET /config`

Returns a read-only description of non-secret backend capabilities and limits:

```ts
interface RuntimeConfig {
  models: {
    embedder: string;
    transcriber: string;
    highlights: string;
    creator: string | null;
    creator_fallbacks: string[];
    personas: string | null;
  };
  search: {
    rrf_k: number;
    visual_min_score: number;
    visual_full_score: number;
    visual_relative_cutoff: number;
    speech_min_score: number;
    speech_full_score: number;
    speech_only_min_score: number;
    image_min_sim: number;
    image_full_sim: number;
  };
  features: {
    gemini: boolean;
    youtube: boolean;
    accounts: boolean;
    require_login: boolean;
  };
  limits: {
    max_upload_mb: number;
    max_video_minutes: number;
  };
}
```

Use `features` to hide unavailable integrations and `limits` for upload validation. Model/search values are useful for diagnostics and should not be treated as secrets.

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

This is the compact implementation index. The named models point to the complete field definitions in this document; `binary` and `SSE` responses must not be parsed as JSON.

#### Accounts and users

| Method and path | Request | Success response | Purpose |
|---|---|---|---|
| `POST /auth/signup` | `SignupRequest` | `201 AuthResponse` | Create an account/token with birth date for age gating. |
| `POST /auth/login` | `LoginRequest` | `200 AuthResponse` | Log in by username or email. |
| `GET /auth/me` | Bearer token | `200 Me` | Restore the signed-in account. |
| `POST /auth/logout` | No body | `204`, no body | Stateless sign-out; the client drops its token. |
| `POST /users` | `UserCreate` | `201 User` | Create a legacy/demo user without credentials. |
| `GET /users` | `limit` | `200 User[]` | List users alphabetically. |
| `GET /users/{user_id}` | Optional viewer identity | `200 Profile` | Profile plus follow/clip counts. |
| `GET /users/{user_id}/clips` | `cursor`, `limit`, `state` | `200 FeedPage` | User clips visible to the viewer. |
| `GET /users/{user_id}/analytics` | `days` | `200 Analytics` | Owner-only dashboard metrics. |
| `POST /users/{user_id}/follow` | No body | `200 FollowResult` | Follow idempotently. |
| `DELETE /users/{user_id}/follow` | No body | `200 FollowResult` | Unfollow idempotently. |
| `GET /users/{user_id}/followers` | `cursor`, `limit` | `200 UsersPage` | Followers, newest first. |
| `GET /users/{user_id}/following` | `cursor`, `limit` | `200 UsersPage` | Followed accounts, newest first. |

#### Uploads, sessions, and persisted highlights

| Method and path | Request | Success response | Purpose |
|---|---|---|---|
| `POST /uploads` | `UploadCreate` | `201 UploadReservation` | Reserve a session and presigned storage PUT. |
| `POST /uploads/{session_id}/complete` | No body | `202 Session` | Verify upload and queue processing. |
| `GET /sessions/{session_id}` | Path ID | `200 Session` | Read session metadata/status. |
| `GET /sessions/{session_id}/status` | Path ID | `200 text/event-stream` | Stream `SessionStatusEvent` messages. |
| `POST /sessions/{session_id}/reprocess` | No body | `202 SessionStatusEvent` | Retry/rebuild processing. |
| `GET /sessions/{session_id}/playlist.m3u8` | `start_ms`, `end_ms` | HLS playlist text | Play all or a window of a session. |
| `POST /sessions/{session_id}/frame-highlights` | Optional `FrameHighlightsRequest` | `202 FrameHighlightsResult` | Start/reuse persisted frame-ranked clips. |
| `GET /sessions/{session_id}/frame-highlights` | Path ID | `200 FrameHighlightsResult` | Poll scores and generated drafts. |

#### Clips, engagement, and generated content

| Method and path | Request | Success response | Purpose |
|---|---|---|---|
| `POST /clips` | `ClipCreate` | `201 Clip` | Create a time-range clip. |
| `GET /clips/{clip_id}` | Optional viewer identity | `200 ClipDetail` | Clip plus events/transcript. |
| `PATCH /clips/{clip_id}` | `ClipPatch` | `200 Clip` | Owner trim/title update. |
| `DELETE /clips/{clip_id}` | No body | `204`, no body | Delete an owned clip. |
| `POST /clips/{clip_id}/publish` | No body | `200 Clip` | Publish to MinedTV and trigger default virality. |
| `POST /clips/{clip_id}/unpublish` | No body | `200 Clip` | Return to private draft. |
| `POST /clips/{clip_id}/mark-ready` | No body | `200 Clip` | Put in private ready-to-post state. |
| `GET /clips/{clip_id}/playlist.m3u8` | Path ID | HLS playlist text | Play the clip range. |
| `POST /clips/{clip_id}/like` | No body | `200 EngagementCounts` | Like idempotently. |
| `DELETE /clips/{clip_id}/like` | No body | `200 EngagementCounts` | Remove like idempotently. |
| `POST /clips/{clip_id}/view` | Optional viewer identity | `200 EngagementCounts` | Record a deduplicated view. |
| `POST /clips/{clip_id}/export` | No body | `202 ExportResult` | Start/reuse MP4 export. |
| `GET /clips/{clip_id}/export` | Path ID | `200 ExportResult` | Poll MP4 export. |
| `POST /clips/{clip_id}/creator-pack` | No body | `202 ClipCreatorPackResult` | Start/reuse AI metadata generation. |
| `GET /clips/{clip_id}/creator-pack` | Path ID | `200 ClipCreatorPackResult` | Poll AI metadata generation. |
| `POST /clips/{clip_id}/highlights` | `ClipHighlightsIn` JSON | `202 ClipHighlightsResult` | Start/reuse the asynchronous AI-share render. |
| `GET /clips/{clip_id}/highlights` | Matching query options | `200 ClipHighlightsResult` | Poll stage/progress and retrieve the ready review payload. |
| `POST /clips/{clip_id}/virality` | `ClipViralityRequest` | `202 ClipViralityResult` | Start/reuse persona simulation. |
| `GET /clips/{clip_id}/virality` | Platform/audience/count query | `200 ClipViralityResult` | Poll persona simulation. |
| `GET /clips/{clip_id}/comments` | `cursor`, `limit` | `200 CommentsPage` | Read threaded comments. |
| `POST /clips/{clip_id}/comments` | `CommentCreate` | `201 Comment` | Comment or reply. |
| `DELETE /comments/{comment_id}` | No body | `204`, no body | Delete allowed comment/replies. |
| `POST /clips/{clip_id}/youtube` | `YouTubePostRequest` | `202 YouTubeUpload` | Queue YouTube upload. |
| `GET /clips/{clip_id}/youtube` | Path ID | `200 YouTubeUpload[]` | List/poll YouTube attempts. |

#### Discovery, notifications, and direct AI tools

| Method and path | Request | Success response | Purpose |
|---|---|---|---|
| `GET /feed` | `cursor`, `limit`, `game` | `200 FeedPage` | Public published feed. |
| `GET /feed/following` | `cursor`, `limit` | `200 FeedPage` | Authenticated following feed. |
| `GET /search` | Text/filter query | `200 SearchResponse` | Hybrid text search. |
| `POST /search/image` | Multipart `image` plus filters | `200 SearchResponse` | Visual screenshot search. |
| `GET /notifications` | `cursor`, `limit`, `unread_only` | `200 NotificationsPage` | Account inbox. |
| `GET /notifications/unread-count` | No body | `200 UnreadCount` | Inbox badge count. |
| `POST /notifications/read` | `MarkNotificationsRead` | `200 UnreadCount` | Mark selected/all read. |
| `POST /creator/analyze` | Multipart `video` | `200 CreatorPack` | Video-to-publishing metadata. |
| `POST /creator/simulate-analysis` | `AudienceSimulationRequest` | `200 AudienceSimulation` | Personas from reused analysis. |
| `POST /creator/simulate` | Multipart video/options | `200 AudienceSimulation` | Combined analysis/personas. |
| `POST /creator/virality` | Multipart video/options | `200 AudienceSimulation` | Frame-aware persona and video virality. |
| `POST /creator/highlights` | Multipart `video`, optional mode/captions/style | `200 DirectHighlights` | Render one portrait single highlight or montage. |
| `GET /creator/highlights/{run_id}/clips/{index}.mp4` | Optional `download` | MP4 binary | Stream/download temporary montage. |
| `GET /creator/highlights/{run_id}/frames/{frame_id}.jpg` | Path IDs | JPEG binary | Read selected-frame thumbnail. |

#### YouTube connection and operations

| Method and path | Request | Success response | Purpose |
|---|---|---|---|
| `GET /youtube/status` | Acting account | `200 YouTubeStatus` | Read configuration/connection. |
| `GET /youtube/connect` | Acting account | `200 YouTubeConnect` | Obtain Google consent URL. |
| `GET /youtube/callback` | Google `code`/`state`/`error` | HTML or `303` redirect | Complete OAuth; browser callback. |
| `DELETE /youtube/connection` | Acting account | `200 YouTubeStatus` | Revoke/forget connection. |
| `POST /warmup` | No body | `200 WarmupResponse` | Warm the embedder. |
| `GET /config` | No request | `200 RuntimeConfig` | Public capabilities and limits. |
| `GET /health` | No request | `200 HealthResponse` | Dependency health report. |

### Backend-wide frontend implementation notes

- Use the URLs returned by the API instead of constructing storage object URLs.
- Playlist endpoints return text, not JSON.
- Session status is SSE, not a normal JSON polling response.
- Direct upload has three steps: reserve, PUT to storage, complete.
- Creator direct upload is separate and sends multipart data directly to the API.
- Direct montage generation is synchronous and may take much longer than ordinary JSON calls; its returned assets are temporary.
- Feed pagination is keyset/cursor based, not page-number based.
- Export, frame highlights, saved-clip creator packs, clip virality, and YouTube posts are asynchronous polling APIs.
- Direct creator analysis and persona simulation are synchronous APIs.
- Do not expose owner-only draft/ready clips to other users; rely on backend `403`/`404` enforcement as well as UI guards.
- Anonymous and under-18 viewers do not receive age-restricted clips in feeds.
- Notification messages are already display-ready, while `type` and `data` are available for richer UI behavior.
- Keep millisecond session/clip positions separate from creator display timestamps.
- Treat `content_warnings`, persona results, and virality scores as generated guidance rather than moderation or analytics guarantees.
