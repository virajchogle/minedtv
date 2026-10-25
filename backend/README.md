# MinedTV backend

Stores, processes and serves gameplay recordings with plain-language search ("the clutch on Bind", "when my friend screamed") that jumps to the exact second.

Clips are **views**: a clip is a `start_ms..end_ms` range over a session's 2-second HLS segments, so extending or trimming a clip is just a PATCH. Nothing is re-uploaded or re-encoded.

```
client ──POST /uploads──▶ API ──presigned PUT URL──▶ client ──PUT video──▶ R2
client ──POST /uploads/{id}/complete──▶ API ──enqueue──▶ Redis (RQ) ──▶ worker
worker: probe → segment (720p HLS) → thumbnails → frames (1 fps + CLIP) → audio (Whisper) → highlights → finalize
                                           │                         │
                                     Modal T4 GPU  ◀─────────────────┘   (stubs locally)
client ──GET /clips/{id}/playlist.m3u8──▶ API builds the playlist from segment rows ──▶ segments stream from R2
```

| Piece | Local | Hosted (free tiers) |
|---|---|---|
| API | uvicorn in compose | Cloud Run service (us-east1) |
| Worker | RQ worker in compose | Cloud Run Job, run every minute |
| Postgres + pgvector | `pgvector/pgvector:pg16` | Supabase |
| Redis | `redis:7` | Upstash |
| Object storage | SeaweedFS (S3 API)* | Cloudflare R2 |
| Embeddings + transcription | stubs, or CPU models | Modal (T4) |

\* MinIO no longer publishes public images, so SeaweedFS stands in for S3 locally.

---

## Local setup

Prereqs: Docker (Docker Desktop, or `colima start` plus `brew install docker-compose`), Python 3.11+, ffmpeg.

```bash
cd backend
docker-compose up -d --build       # postgres, redis, s3, migrations, api, worker
curl localhost:8000/health         # {"status":"ok",...}
open http://localhost:8000/docs    # interactive API docs
```

To run scripts and tests from your machine:

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env               # the defaults already point at the compose services
.venv/bin/pytest                   # unit tests + end-to-end pipeline (needs compose postgres)
```

### Load the demo

```bash
# demo_videos/<Game>/<anything>.mp4, e.g. demo_videos/Valorant/ranked-bind.mp4
.venv/bin/python -m scripts.seed ./demo_videos --reset
```

This wipes the database and stored media (`--reset`), creates the demo users ShadowSniper, NovaQueen and xPixel, deals the videos out to them, and runs the full pipeline. Add `--queue` to hand the work to the worker instead of processing in the script, or `--jobs 2` to process two at a time. It works against whatever `.env` points at, including Supabase/R2/Modal.

```bash
.venv/bin/python -m scripts.load_test -n 200 -c 10     # search latency (p50/p95/p99)
.venv/bin/python -m scripts.export_api_docs            # regenerate docs/openapi.json + docs/api-examples/
```

### Testing on a phone or emulator

Presigned URLs embed the storage host, so it must be reachable from the device:
- Android emulator: `S3_PUBLIC_ENDPOINT_URL=http://10.0.2.2:8333 docker-compose up -d`, API at `http://10.0.2.2:8000`
- Real phone on the same Wi-Fi: use your laptop's LAN IP for both.

---

## API

Full spec: [`docs/openapi.json`](docs/openapi.json), or `/docs` on a running server. Example responses for building the UI against mock data are in [`docs/api-examples/`](docs/api-examples/).

**API key:** when `API_KEYS` is set (it is in production), send `X-API-Key: <key>` on every request. Browser `EventSource` can't set headers, so `?api_key=<key>` also works. `/health`, `/docs` and `*.m3u8` playlists don't need it, so video players can fetch playlists directly. Get the key from whoever holds `.env.prod`. Don't commit it into a public repo; it's a speed bump against random traffic, not real auth.

**Publish states:** a clip is `draft` (private, "My videos") or `published` (in the feed, search and other people's view of a profile). `ready` is a legacy private state kept for older clients. Unpublished clips are visible only to their owner: `GET /clips/{id}` returns 404 to anyone else, and `GET /users/{id}/clips?state=draft|ready|published|unpublished|all` is for the owner. Searching with `user_id` set to yourself includes your unpublished clips. Clip responses carry `youtube_url` once the clip has been posted to YouTube (`POST /clips/{id}/youtube`, for published clips). Clips the pipeline creates start as `NEW_CLIP_PUBLISH_STATE` (default `draft`). HLS playlists stay reachable by clip ID (players can't send headers), so treat an unpublished clip's ID as private.

**Social:** comments allow one level of replies (replying to a reply attaches to its top-level comment) and are limited to 1000 characters. Only clips you can see can be commented on, so drafts are owner-only. Deleting a comment deletes its replies. Counts (comments, followers, following) are computed from the rows on each read, so they can't drift. **Notifications** are written in the same transaction as the action that causes them:
- a like on your clip, written once per person per clip
- a comment on your clip
- a reply to your comment
- a new follower, written once per person
- your upload finishing processing, once per upload
- your virality check finishing

Nobody is notified about their own actions. Each notification carries a ready-to-show `message`.

**YouTube posting:** a user connects their channel once. `GET /youtube/connect` returns a Google sign-in URL; after they approve, Google redirects to `/youtube/callback`, which stores an encrypted refresh token. That callback route is exempt from the API key, and a signed, 15-minute `state` value ties it to the user who started.

Clips in the **ready** bucket (or already published) can be posted with `POST /clips/{id}/youtube`. Title, description and tags default to the AI creator pack's YouTube metadata. The worker renders the MP4, uploads it with YouTube's resumable upload, records the video link, and sends a `youtube_posted` notification on success or failure.

Limits:
- Until the Google project passes YouTube's API audit, uploaded videos may be forced to private.
- The default quota allows about 6 uploads a day.
- In OAuth "testing" mode, only Google accounts listed as test users can connect.

For TikTok and Reels, use the MP4 export plus the phone's share sheet instead: their posting APIs need an app review first.

**Identity:** `POST /auth/signup {username, email, password}` or `POST /auth/login {login, password}` (login = username or email) returns a token; send it as `Authorization: Bearer <token>` (it lasts `AUTH_TOKEN_TTL_DAYS`, and `GET /auth/me` returns the account). While `REQUIRE_LOGIN=false` (the default, for testing), `X-User-Id` picks who a request acts as, with or without a token, so demo clients keep working and anyone can act as any user; `POST /users` still makes password-less demo users. With `REQUIRE_LOGIN=true`, a token is required and only dev accounts (email in `DEV_EMAILS`) may act as someone else via `X-User-Id` (others get 403). `/auth/me` reports this as `can_act_as`. Reads work without either; when one is sent, `liked_by_me` is filled in.

| Method | Path | Example |
|---|---|---|
| POST | `/users` · GET `/users`, `/users/{id}` | `users.create.json`, `users.list.json` |
| POST | `/uploads` → PUT the file to `upload_url` with `headers` | `uploads.create.json` |
| POST | `/uploads/{session_id}/complete` | `uploads.complete.json` |
| GET | `/sessions/{id}` | `sessions.get.json`, `sessions.get.failed.json` |
| GET | `/sessions/{id}/status` (SSE `status` events, closes when `done`) | `sessions.status.sse.txt` |
| POST | `/sessions/{id}/reprocess` (resumes from the failed step) | `sessions.reprocess.json` |
| POST/GET | `/sessions/{id}/frame-highlights` (owner only; POST starts, GET polls) | `sessions.frame-highlights.json` |
| GET | `/sessions/{id}/playlist.m3u8?start_ms=&end_ms=` | |
| GET | `/feed?cursor=&limit=&game=` | `feed.json` |
| GET | `/clips/{id}` (with events + transcript in range) | `clips.get.json` |
| GET | `/clips/{id}/playlist.m3u8` | `clips.playlist.m3u8` |
| POST | `/clips` · PATCH `/clips/{id}` · DELETE `/clips/{id}` | `clips.create.json`, `clips.patch.json` |
| POST/DELETE | `/clips/{id}/like` · POST `/clips/{id}/view` | `clips.like.json`, `clips.view.json` |
| POST/GET | `/clips/{id}/export` (MP4 for TikTok/Reels; POST starts it, GET polls until `ready`) | `clips.export.*.json` |
| POST | `/clips/{id}/publish` · `/unpublish` · `/mark-ready` (owner only) | `clips.publish.json` |
| POST/GET | `/clips/{id}/creator-pack` (Gemini titles, captions, YouTube metadata for an uploaded clip) | |
| GET/POST | `/clips/{id}/virality` (frame-scorer score, verdict, signals and per-moment curve; owner only. POST scores an upload from before auto-scoring) | |
| GET/POST | `/clips/{id}/comments` (top-level newest first, each with replies; POST `{body, parent_id?}`) · DELETE `/comments/{id}` (author or clip owner) | `comments.list.json` |
| GET | `/users/{id}` (profile: follower/following counts, published clip count, `followed_by_me`, `follows_me`) | `users.profile.json` |
| POST/DELETE | `/users/{id}/follow` · GET `/users/{id}/followers` · `/users/{id}/following` · GET `/feed/following` | `users.follow.json` |
| GET | `/youtube/status` · `/youtube/connect` (returns `auth_url`) · DELETE `/youtube/connection` | |
| POST/GET | `/clips/{id}/youtube` (post a **ready** clip to your channel; `{title?, description?, tags?, privacy}`) | |
| GET | `/notifications?unread_only=` · `/notifications/unread-count` · POST `/notifications/read` `{ids}` or `{all: true}` | `notifications.json` |
| POST | `/warmup` (wake the GPU; call on app launch without awaiting) | |
| GET | `/users/{id}/clips` | `users.clips.json` |
| GET | `/search?q=&game=&user_id=&from=&to=&limit=` | `search.json` |
| POST | `/search/image` (multipart `image`, optional `game`, `user_id`, `limit`) | `search.image.json` |
| POST | `/creator/analyze` (multipart `video`) | Gemini-generated transcript, summary, captions, and platform metadata |
| POST | `/creator/highlights` (multipart `video`) | `creator.highlights.json` |
| POST | `/creator/simulate` (multipart `video`, `platform`, optional `target_audience`, `persona_count`) | `creator.simulate.json` |
| POST | `/creator/simulate-analysis` (JSON with an `/creator/analyze` result plus persona options) | `creator.simulate.json` |
| GET | `/health` | `health.json` |

**Frame highlights:** this runs automatically when an upload finishes processing (`AUTO_FRAME_HIGHLIGHTS`,
default on): its clips replace the pipeline's event-based ones, which are kept only if the scorer can't cut
any. A clip's virality (`/clips/{id}/virality`) is the average of its strongest frame scores. To re-run by
hand after a session is ready, POST `/sessions/{id}/frame-highlights` with an optional
`{"count": 3, "clip_duration_ms": 30000}` body, then poll GET until `status` is `ready`. The worker reuses
the sampled frame embeddings, visibility measurements, detector events, and transcript already produced by
the upload pipeline; it does not decode or upload the video again. Legacy frames calculate and persist their
visibility the first time they are scored. Each frame gets visual, novelty, visibility, sustained-scene, event,
and speech component scores. The strongest non-overlapping peaks become draft clips with
`generation_source: "frame_virality"`, while existing pipeline and manual clips are preserved. Viral prompt
embeddings are cached per worker process, and a repeat POST with unchanged options returns the stored result.

**Standalone montage:** `POST /creator/highlights` accepts the video itself as multipart form data, samples and
scores frames in one pass, then selects up to six distinct major moments based on source length and signal
strength. Absolute luminance/visible-area/contrast scoring prevents nearly black frames from winning on CLIP
similarity alone, while an eight-second neighborhood signal favors sustained action over isolated title cards or
cuts. Each moment expands through nearby supporting frames, preserves short score dips for setup/payoff, and is
kept to a concise 4-10 second range. Weak local maxima are discarded instead of padding the output. The selected
ranges are rendered chronologically and joined into one phone-compatible 720x1280 H.264/AAC montage: a blurred
9:16 background fills the screen while the sharp source remains fully visible instead of being cropped. The
assembled audio is transcribed once and timed speech/accessibility cues are burned into the final montage. A
configured `TRANSCRIBER_BACKEND` is tried first; Gemini provides the compact-audio fallback when `GEMINI_API_KEY`
is set. If neither provider produces cues, the montage still succeeds and reports
`captions_burned: false`. The response includes playback/download URLs, output dimensions, caption count, and
caption source, plus every source range included in `moments`. It does not create a user or session and does not need Postgres, Redis, object storage, or the
persona simulator.
It does require `ffmpeg`/`ffprobe` and a real CLIP-compatible embedder for meaningful visual rankings. Direct
outputs expire after `STANDALONE_HIGHLIGHT_TTL_S` (24 hours by default). The API container installs FFmpeg;
local Windows setups can point `FFMPEG_BINARY` and `FFPROBE_BINARY` at project-local executables.

**Playback:** hand `playlist_url` to ExoPlayer/Media3 (Android), AVPlayer (iOS) or hls.js (web). Playback is segment-granular. The playlist starts at the segment containing `start_ms`, with `EXT-X-START` set to the exact offset. Segment URLs are presigned GETs valid for an hour, or plain public URLs if `STORAGE_PUBLIC_BASE_URL` is set. Re-fetch the playlist if a player sits open longer than that.

**Search results** contain one entry per session, and weak matches are filtered out. Visual search embeds the query with a few phrasings ("a first-person view of a player holding {query}"…) and subtracts the similarity to generic gameplay, so the subject decides rather than "it's an FPS frame". A frame must score at least 0.035 on that contrastive scale and at least 75% of the query's best frame. Speech is scored the same way against generic talking: at least 0.03, and lines under 3 words such as "Yeah" don't count for meaning-based matching. A match on speech alone needs a stronger score (0.06). Keyword and event matches always count. Results are ordered by `confidence`, with the fusion score breaking ties. These thresholds were measured on the team's real clips with CLIP ViT-L/14; re-measure them if the model changes. `confidence` (0–1) is comparable across queries, unlike the raw `score`. `moments` lists the best moment first, then up to 3 more in the same session, each with `offset_ms` (where to seek in that result's playlist), `confidence`, `signals`, the event `label`, the transcript `snippet` and a `thumbnail_url`.

`kind: "clip"` means an existing clip contains the match. `kind: "session"` means no clip does, and `start_ms..end_ms` is a suggested ±15 s window you can turn into a clip with `POST /clips`. Seek to `match_t_ms - start_ms` within the playlist. `signals` says which of `visual`, `speech`, `keyword`, `event` matched.

---

## Plugging in real models

### Gemini creator engine

Set `GEMINI_API_KEY` to enable `POST /creator/analyze`. The endpoint accepts a multipart video and returns a typed content pack containing a factual description, concise summary, transcript, key moments, caption, title options, hashtags, YouTube metadata, and Reddit copy. `GEMINI_MODEL`, `CREATOR_FRAME_SAMPLE_FPS`, `CREATOR_INLINE_LIMIT_MB`, and `CREATOR_MAX_UPLOAD_MB` tune the engine; see `.env.example`.

The reusable engine lives in `app/ml/gemini_creator.py`. Small videos are sent inline, larger videos use Gemini's Files API, and temporary local and remote files are removed after each request.

The recommended integrated flow calls `POST /creator/analyze` once, renders that content pack, and sends the same JSON to `POST /creator/simulate-analysis`. The persona simulator therefore never reads or parses the video again. `POST /creator/simulate` remains as a standalone convenience route for clients that have not already analyzed the upload. The panel is split across target, adjacent-interest, and outsider audiences and uses the speed-oriented `CREATOR_PERSONA_MODEL` independently from the full creator parser model. Local deterministic scoring calculates engagement signals and decides whether the simulated sharing cascade reaches each layer. The default panel is 9 personas and can be tuned with `CREATOR_PERSONA_COUNT` or the request's `persona_count` field (3-15). Results are explicitly synthetic feedback, not real audience analytics or a guarantee of reach.

The simulator creates a `creator.persona_panel` OpenTelemetry span with model, platform, panel size, score, and cascade depth. With current FastAPI versions, set `FASTAPI_OTEL_AUTO_CONFIGURE=true`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`, and `OTEL_SERVICE_NAME` to send request and simulator traces to SigNoz; see `.env.example` for the variable names.

Contracts are in [`app/ml/interfaces.py`](app/ml/interfaces.py):

```python
class Embedder(Protocol):            # CLIP-style: images and text in one space
    dim: int
    def embed_images(self, images: list[bytes]) -> list[list[float]]: ...   # JPEG bytes in
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

class Transcriber(Protocol):
    def transcribe(self, audio_path: str) -> list[TranscriptChunk]: ...      # start_ms, end_ms, text, speaker

class HighlightDetector(Protocol):
    def detect(self, video_path: str, session_id: str) -> list[DetectedEvent]: ...  # t_ms, type, score, metadata
```

Write a class with those methods anywhere importable (e.g. `app/ml/highlights.py`) and select it by env var. The class is constructed with no arguments.

```bash
HIGHLIGHT_BACKEND=app.ml.highlights:MyDetector
EMBEDDER_BACKEND=modal               # or stub, or my.module:Class
TRANSCRIBER_BACKEND=modal
```

Notes for each team:
- **Embedder:** vectors must be `EMBEDDING_DIM` long and L2-normalized. Text queries search frames, so image and text vectors must share a space (CLIP, SigLIP and similar). Default is 768 (CLIP ViT-L/14). PixelPull's ViT-B/32 is **512**. Pick before seeding real data, because changing the size means editing `EMBEDDING_DIM`, adding a migration that alters both vector columns, and re-running the pipeline. The API refuses to start an embedder whose `dim` doesn't match.
- **Transcriber:** gets a mono 16 kHz Opus file. Return chunks at whatever granularity you have; the pipeline merges them into 5–10 s windows. Set `speaker` if you can diarize, because search snippets show it.
- **Highlight detector:** gets the original upload. Use `type` values from `KNOWN_EVENT_TYPES` (`kill`, `multikill`, `headshot`, `clutch`, `ace`, `win`, `death`, `loud`, `funny`) so text search can match them; synonyms live in `EVENT_SYNONYMS` in `app/services/search.py`. `score` should be in 0..1. The top `AUTO_CLIP_COUNT` events become ±15 s auto clips.
- **Run a CPU version locally** with `pip install -r requirements-ml.txt`, then `EMBEDDER_BACKEND=app.ml.models:ClipEmbedder` and `TRANSCRIBER_BACKEND=app.ml.models:WhisperTranscriber`.
- After swapping models, reprocess existing sessions with `POST /sessions/{id}/reprocess` (or re-seed).

## Modal (GPU inference)

```bash
pip install modal && modal setup          # once, opens a browser to log in
cd backend
modal deploy modal_app.py                 # builds the image, deploys Embedder + Transcriber on T4
modal run modal_app.py                    # smoke test: prints "embedder ok: dim=768"
```

Then set `EMBEDDER_BACKEND=modal` and `TRANSCRIBER_BACKEND=modal`. Locally, the adapter uses your `~/.modal.toml`. On Cloud Run, set `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` (from modal.com → Settings → API Tokens).

Before a demo, run `python -m scripts.gpu_warm on` to keep one GPU container warm (about $0.60/hour), and `python -m scripts.gpu_warm off` afterwards. The app can also call `POST /warmup` at launch.

Containers scale to zero after 5 idle minutes. The first call after that is a cold start of about 30–60 s, which also hits the first search. Before a demo, run one search or `modal run modal_app.py` to warm it up.

## Deploying (Cloud Run, us-east1)

1. **Supabase:** create a project in a US East region. In SQL editor run `create extension if not exists vector;`. Copy the transaction pooler URI (port 6543) and change `postgresql://` to `postgresql+asyncpg://`.
2. **R2:** create bucket `minedtv` and an R2 API token with Object Read & Write. Optional: enable the bucket's public r2.dev URL and set `STORAGE_PUBLIC_BASE_URL`, which makes segment and thumbnail URLs cacheable.
3. **Upstash:** create a Redis DB in us-east-1 and copy the `rediss://` URL.
4. Fill `.env.prod` from `.env.example` with `APP_ENV=prod`, `DB_PGBOUNCER=true`, the R2 endpoint, `EMBEDDER_BACKEND=modal`, `TRANSCRIBER_BACKEND=modal` and the Modal tokens. Then run, from your machine:
   ```bash
   set -a; source .env.prod; set +a          # point the tools at prod for this shell
   .venv/bin/alembic upgrade head           # schema into Supabase
   .venv/bin/python -m scripts.init_storage # bucket CORS for the web UI
   ```
5. Install `gcloud`, run `gcloud auth login`, then:
   ```bash
   PROJECT_ID=<your-project> ./deploy/cloudrun.sh
   ```
   This builds both linux/amd64 images locally with `docker buildx` and pushes them to Artifact Registry (`BUILD=cloud` uses Cloud Build instead), deploys the API as a Cloud Run service, deploys the worker as a **Cloud Run Job** (`python -m app.worker --burst`, which drains the queue and exits), and creates a Cloud Scheduler tick that starts it every minute. Processing therefore starts within about a minute of upload.
6. Set `PUBLIC_API_BASE_URL` to the printed API URL in `.env.prod` and re-run with `SKIP_BUILD=1`.

Seed the hosted demo from your laptop by pointing `.env` at prod (`set -a; source .env.prod; set +a`) and running `python -m scripts.seed ./demo_videos --reset`. Processing runs on your machine, and data lands in Supabase/R2/Modal.

### Free-tier watch list

| Service | Limit | Where it bites |
|---|---|---|
| Supabase | 500 MB DB; pauses after 7 days idle | 768-d vectors + HNSW use about 6–8 KB per frame, so 1 fps fits roughly 15–20 hours of footage. Lower `FRAME_SAMPLE_FPS` for long VODs. |
| R2 | 10 GB storage, 1M writes/month | 720p is about 0.5–1 GB per hour. Each session hour is about 5.4k writes (segments + frame thumbnails). |
| Upstash | 500K commands/month | Each worker-job tick uses about 30 commands, so the every-minute scheduler uses about 40K a day. Fine for the hackathon; pause it afterwards with `gcloud scheduler jobs pause minedtv-worker-tick --location us-east1`. Don't leave a long-running RQ worker polling Upstash. |
| Modal | $30/month credit | A T4 costs about $0.60/hour while warm. Whisper large-v3-turbo transcribes an hour of audio in a few minutes. |
| Cloud Run | 180K vCPU-s and 2M requests/month | The worker job uses 2 vCPU while processing, roughly 1–2× realtime for a 720p transcode. An always-on worker service would use the free allowance in about a day, which is why the worker is a job. |

---

## Layout

```
app/
  main.py            FastAPI app, CORS, /health, counter flush loop
  config.py          every setting (env vars / .env)
  log.py             JSON logs; session_id + step bound on every pipeline line
  schemas.py         all request/response models
  db/                models, engine, Alembic migrations
  api/               routers: uploads, sessions, clips, feed, search, users, creator
  services/          storage (S3/R2/local), playlist, search (RRF), counters, serialize
  worker/            pipeline steps, ffmpeg wrappers, RQ job + worker entry point
  ml/                Gemini creator + audience simulator, interfaces, stubs, registry, Modal adapter, real CLIP/Whisper
modal_app.py         Modal GPU app
scripts/             seed, load_test, export_api_docs, init_storage
deploy/              Cloud Build config + Cloud Run deploy script
tests/               playlist, clip validation, RRF/fusion, end-to-end pipeline
```

### Processing details

- Each step is idempotent: it deletes its own previous output for the session, then writes. `sessions.last_step` records progress. On failure the session gets `status=failed`, `failed_step` and `error`. `POST /sessions/{id}/reprocess` resumes after `last_step`, while reprocessing a ready session redoes every step. User-made clips survive reprocessing; auto clips are regenerated.
- Segments are transcoded with forced keyframes every 2 s (`-force_key_frames`, `-sc_threshold 0`), so every segment starts on a keyframe and a playlist can start at any segment.
- Search runs four queries in parallel (pgvector cosine on frames and transcripts, Postgres full-text on transcripts, event-type match), fuses them with reciprocal rank fusion (k=60), clusters hits within ±2.5 s into moments, keeps the best moment per session, and resolves it to the narrowest clip containing it. Results are cached in Redis for 5 minutes.
- Likes and views increment Redis hashes. Every 30 s the API atomically renames each hash and adds the deltas to Postgres, so displayed counts stay live in between flushes.
