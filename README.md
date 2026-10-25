<p align="center">
  <img src="docs/screenshots/splash.jpg" alt="MinedIt" width="420">
</p>

<h1 align="center">MinedIt</h1>

<p align="center">
  <b>Your moments. Rediscovered.</b><br>
  Upload your gameplay, then search it the way you'd describe it: <i>"the clutch on Bind"</i>, <i>"sniper through smoke"</i>, <i>"when my friend screamed"</i>.<br>
  MinedIt jumps to the exact second, cuts the highlights, scores how viral they'll be and makes a vertical edit ready for Shorts.
</p>

<p align="center">
  <a href="https://minedtv.vercel.app"><b>Try it live →</b></a>
  &nbsp;·&nbsp; <a href="backend/README.md">Backend guide</a>
  &nbsp;·&nbsp; <a href="backend/docs/android-integration.md">API guide for apps</a>
  &nbsp;·&nbsp; <a href="https://github.com/rishikesh-web/MinedTv">Android app</a>
  &nbsp;·&nbsp; <a href="NOTES.md">Team notes</a>
</p>

<p align="center">Built for the Medal.tv hackathon.</p>

<p align="center">
  <img src="docs/screenshots/home.jpg" alt="MinedIt home page" width="100%">
</p>

## Contents

- [What it does](#what-it-does)
- [A tour of the app](#a-tour-of-the-app)
- [How it works](#how-it-works)
  - [Architecture](#architecture)
  - [What happens to an upload](#what-happens-to-an-upload)
  - [How search works](#how-search-works)
  - [How virality is scored](#how-virality-is-scored)
  - [How a montage is made](#how-a-montage-is-made)
  - [Content moderation](#content-moderation)
  - [Clips are views](#clips-are-views)
- [API at a glance](#api-at-a-glance)
- [Repository layout](#repository-layout)
- [Run it locally](#run-it-locally)
- [Tests and deploys](#tests-and-deploys)
- [Team](#team)

---

## What it does

Gaming clips pile up fast, and the moment you want is always somewhere in a 40-minute recording. MinedIt makes every second of your footage searchable and does the creator busywork for you:

| | |
|---|---|
| 🔎 **Search by description** | Type what happened ("AWP through smoke", "he's one shot") and get the exact second, with a confidence score and the reason it matched. Works across everything, inside one clip, or from a screenshot. |
| ✂️ **Automatic highlights** | Every upload is scored moment by moment and the strongest moments become clips on their own. |
| 📈 **Virality score** | Each clip gets a 0 to 100 score with a moment-by-moment curve and the signals behind it. |
| 🎬 **Montage & best moment** | One click makes a 9:16 edit of the best moments (or just the single best one), framed for Shorts, TikTok or Reels, with burned-in captions and a hook line. |
| ▶️ **Post to YouTube** | Connect your channel once, then post a clip or its montage straight from MinedIt, with the title, description and tags written for you. |
| ✨ **AI creator pack** | Title ideas, a caption, hashtags, YouTube metadata and key moments for every clip (Gemini). |
| 💬 **Social** | Publishing, likes, comments with replies, follows, a following feed, notifications and related clips. |
| 📊 **Creator dashboard** | Real daily views (counted once per viewer), likes and comments, an income projection, per-clip forecasts and audience flow. |
| 📱 **Shorts / Reels** | Vertical clips stay vertical end to end, and the API serves a separate Reels feed for the Android app. |

## A tour of the app

### Search every moment

<p align="center">
  <img src="docs/screenshots/search.jpg" alt="Searching for 'sniper through smoke' finds the moment in a CS2 clip" width="100%">
</p>

"sniper through smoke" finds the Dust II clip with a strong match (77% sure) and the exact timestamps where it happens. Each result shows which signals matched (visual, speech, keyword, event) and plays from the right second. Search runs over published clips for everyone, and over your private drafts too when you search your own library.

### Your clip, everything around it

<p align="center">
  <img src="docs/screenshots/clip.jpg" alt="A clip page with the owner's publishing, YouTube and montage tools" width="100%">
</p>

The clip page plays the clip over HLS. Viewers get likes, share, search inside the clip, comments with replies and more clips from the same game. Owners also get a side column of tools:

1. **Publishing.** Uploads land in *My videos*, private. Publishing puts a clip in the feed, search and your profile; unpublishing takes it back.
2. **Post to YouTube.** OAuth with your Google account, then a background upload with the creator pack's title, description and tags. The post's status and link appear on the page.
3. **Montage & best moment.** Pick the cut, the platform, the caption style and whether to add a hook line. The render runs in the background with live progress, then you can preview, download or post it.
4. **Virality** and the **AI creator pack** (below), plus an **MP4 export** for anywhere else.

### Know what will hit

<p align="center">
  <img src="docs/screenshots/insights.jpg" alt="Virality score with a moment-by-moment curve, the signals behind it, and comments" width="100%">
</p>

The virality panel shows the score and verdict (weak, mixed 35+, promising 55+, strong 75+), where the clip peaks, and what drives the score. The creator pack below it is generated once per clip and cached.

<p align="center">
  <img src="docs/screenshots/montage.jpg" alt="Frames from a generated vertical montage" width="100%">
  <br><sub>Frames from a real montage: a 42-second CS2 clip cut down to its best 13.5 seconds and reframed to 9:16 over a blurred fill.</sub>
</p>

### Watch your numbers

<p align="center">
  <img src="docs/screenshots/dashboard.jpg" alt="Creator dashboard with expected income, daily views, likes and comments, a per-clip forecast and audience flow" width="100%">
</p>

Every number comes from real tracked data: views (one per viewer per clip), likes, comments and new followers per day over 7, 30 or 90 days, compared with the period before. On top of that:

- **Expected income** projects earnings at an assumed TikTok RPM ($0.04 per 1,000 views, adjustable). It's clearly labelled as illustrative.
- **Forecast** projects one clip's next 15 to 365 days in conservative, expected and breakout scenarios. Each clip's curve is anchored to its publish day and scaled by its virality score.
- **Audience** shows how each game's views flowed into likes and comments.
- Every clip with its views, likes, comments and virality score, sortable.

### Drop it in, we do the rest

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/upload.jpg" alt="Upload page"></td>
    <td width="50%"><img src="docs/screenshots/explore.jpg" alt="Explore feed, browsable by game"></td>
  </tr>
  <tr>
    <td align="center"><sub>Upload: MP4, MOV, MKV, WebM and more, up to 90 minutes and 4 GB</sub></td>
    <td align="center"><sub>Explore: the latest clips, browsable by game</sub></td>
  </tr>
</table>

---

## How it works

### Architecture

```
  Browser ──▶ Next.js on Vercel ──/api/minedtv proxy (adds the API key)──┐
  Android app ───────────────────────────────────────────────────────────┤
                                                                         ▼
                                                     FastAPI on Cloud Run (minedtv-api)
                                                                         │
     ┌────────────────────────┬────────────────────────┬─────────────────┤
     ▼                        ▼                        ▼                 ▼
  Cloudflare R2         Postgres + pgvector       Redis (Upstash)    Google OAuth
  video, HLS segments,  (Supabase): sessions,     job queue, view    YouTube Data API
  thumbnails, renders   clips, frames, vectors,   and like counters,
                        transcripts, events,      search cache, job
                        social, analytics         status
                                                         │
                                                         ▼
                                     RQ worker (Cloud Run Job, every minute)
                                     ffmpeg · CLIP + Whisper on Modal T4 GPUs · Gemini
```

| Layer | Technology |
|---|---|
| **Web** | Next.js 16, React 19, Tailwind 4, Framer Motion, ECharts · [`frontend/`](frontend/) |
| **API** | FastAPI, async SQLAlchemy, Alembic migrations, Pydantic · [`backend/app/`](backend/app/) |
| **Worker** | RQ on Redis, run as a Cloud Run Job that drains the queue every minute |
| **Search** | pgvector (HNSW, cosine), Postgres full-text search, reciprocal rank fusion |
| **Models** | CLIP ViT-L/14 (768-dim) and Whisper large-v3-turbo on Modal T4 GPUs; Gemini for creator packs, captions and moderation |
| **Media** | ffmpeg: HLS, thumbnails, frame sampling, MP4 export, 9:16 montages with ASS captions |
| **Storage** | Cloudflare R2 (S3 API); uploads go straight from the client with presigned URLs |
| **Infra** | Cloud Run, Supabase, Upstash, R2, Modal, Vercel, GitHub Actions |

The API key never reaches the browser: the web app calls its own `/api/minedtv/*` route, which forwards to the API with the key attached on the server, and turns the login cookie into a bearer token.

### What happens to an upload

1. **Upload.** `POST /uploads` creates a session and returns a presigned URL. The file goes straight to R2, never through the API. `POST /uploads/{id}/complete` checks it arrived and queues processing.
2. **Probe.** ffprobe reads duration, frame rate, audio and the display size (with phone rotation applied, so portrait recordings count as vertical).
3. **Segment.** The video becomes 2-second HLS segments at up to 720p. Vertical video is capped on its short side, so it stays 720×1280.
4. **Thumbnails and frames.** A poster frame, then one frame per second, each embedded with CLIP on a GPU and stored as a vector.
5. **Audio.** Whisper transcribes the speech into timed lines, stored with a full-text index.
6. **Moderate.** Gemini checks the transcript and a sample of frames (see [Content moderation](#content-moderation)).
7. **Highlights.** Event detection (kills, clutches, wins) through a pluggable detector interface.
8. **Finalize.** Default clips are created, then the frame scorer rates every moment and cuts the strongest windows into highlight clips. Clips start private.

Each step is idempotent and recorded, so a failed upload can resume from where it stopped (`POST /sessions/{id}/reprocess`). Progress is visible on `GET /sessions/{id}` and as a live event stream.

### How search works

A query runs through four signals in parallel:

| Signal | What it matches | How |
|---|---|---|
| **Visual** | What the frames look like | The query's CLIP text embedding against every frame vector (pgvector HNSW), contrasted with a "generic gameplay" baseline so only distinctive matches count |
| **Speech** | What was said, by meaning | The query against transcript line embeddings |
| **Keyword** | What was said, word for word | Postgres `websearch_to_tsquery` and `ts_rank_cd` over the transcripts |
| **Event** | Detected highlights | Query words mapped to event types (kill, clutch, ace, win, ...) |

Weak hits are dropped by per-signal thresholds, the rest are fused with **reciprocal rank fusion** (k = 60), grouped into moments 5 seconds apart, and turned into a 0 to 1 **confidence** that's comparable across queries. Each upload's matches resolve to the most specific published clip containing the best moment, so private footage never leaks into public results. Results are cached in Redis for 5 minutes. Screenshot search (`POST /search/image`) uses the same pipeline with the image's CLIP embedding.

### How virality is scored

The frame scorer rates every sampled frame from 0 to 1, from signals the pipeline already computed, with no extra model calls:

- **Looks like a highlight:** how close the frame's CLIP embedding is to prompts like "an exciting climactic gaming highlight" versus "ordinary uneventful gameplay", ranked within the upload.
- **Something changes:** how different the frame is from its neighbours.
- **Sustained moment:** a wider window of strong, visible frames, so a held moment beats one flashy cut.
- **Detected events** and **excited reactions** from the event detector and the transcript.
- **Easy to see:** brightness, contrast and visible area, which gates the purely visual evidence.

A clip's virality is the mean of its three strongest moments × 100, compared with the rest of its upload. The same scores choose where highlight clips are cut, and they feed the Reels ranking and the dashboard forecast.

### How a montage is made

`POST /clips/{id}/highlights` queues a render with the chosen options (platform, montage or single best moment, captions on or off, caption style, hook line). The worker:

1. exports the clip and builds (or reuses) its creator pack,
2. scores its frames and picks the strongest non-overlapping windows,
3. writes captions from the transcript plus a hook line,
4. renders each window to 720×1280 over a blurred fill, joins them and burns in the captions,
5. stores the MP4 and a manifest with the moments, captions, a suggested caption and hashtags.

Renders are cached by their options, so asking again is instant. `POST /clips/{id}/youtube` with a `montage` body posts the rendered file instead of the plain clip.

### Content moderation

Gemini classifies each upload's transcript and a sample of its frames as **none**, **mild** or **severe**, with itemized, timestamped findings. Mild content (profanity, crude humour) is allowed but marked 18+ and hidden from viewers who aren't signed-in adults. Severe content (explicit sexual content, slurs and hate speech, credible threats against real people, promotion of self-harm, real-world gore) stops processing and the upload is marked `blocked`. Ordinary game violence is never flagged on its own.

### Clips are views

A clip is a `start_ms..end_ms` range over its upload's segments, not a separate file. Its HLS playlist is built on request from the segment rows, so trimming or extending a clip is a `PATCH` with nothing re-encoded, and a thousand clips of one upload cost no extra storage.

---

## API at a glance

Interactive docs live at `/docs` on the API. Every route needs `X-API-Key`; actions that belong to a user take a login token or `X-User-Id`.

| Area | Endpoints |
|---|---|
| **Uploads** | `POST /uploads`, `POST /uploads/{id}/complete` (with `as_reel` and `reel_of` for vertical reels) |
| **Sessions** | `GET /sessions/{id}`, `GET /sessions/{id}/playlist.m3u8`, `POST /sessions/{id}/reprocess`, frame highlight runs |
| **Clips** | create, get, `PATCH`, delete, `playlist.m3u8`, like, view, publish, unpublish |
| **Creator tools** | `/clips/{id}/export`, `/creator-pack`, `/highlights` (montage), `/virality` |
| **Search** | `GET /search`, `POST /search/image` (filters: game, user, dates, `format=short\|long`) |
| **Feeds** | `GET /feed`, `GET /feed/following`, `GET /users/{id}/clips` (all with `format` and `sort=new\|top`) |
| **Social** | comments and replies, follows, followers and following, notifications with unread counts |
| **YouTube** | connect, callback, status, disconnect, `POST /clips/{id}/youtube`, upload history |
| **Accounts** | `/auth/signup`, `/auth/login`, `/auth/me`, `/auth/logout` |
| **Analytics** | `GET /users/{id}/analytics?days=30` |
| **Standalone tools** | `/creator/analyze`, `/creator/highlights`, `/creator/simulate` for videos that aren't stored |

Full request and response shapes: [`backend/docs/android-integration.md`](backend/docs/android-integration.md) and the mock responses in [`backend/docs/api-examples/`](backend/docs/api-examples/).

## Repository layout

```
backend/
  app/
    api/          FastAPI routers: uploads, sessions, clips, search, feed, social, youtube, analytics, ...
    db/           SQLAlchemy models and Alembic migrations
    ml/           model interfaces, Modal adapters, Gemini creator/captions/moderation, stubs
    services/     search, frame virality, playlists, storage, counters, formats, YouTube
    worker/       the processing pipeline, exports, creator packs, montages, YouTube posting
  modal_app.py    CLIP and Whisper on Modal GPUs
  scripts/        seeding, load testing, GPU warm-up, maintenance
  tests/          unit tests and an end-to-end pipeline test against real Postgres and ffmpeg
  deploy/         Cloud Run deploy script and GitHub keyless-auth setup
frontend/
  src/app/        pages: home, explore, library, upload, video/[id], dashboard, profile, settings, login
  src/components/ UI, charts, hero, clip tools
  src/lib/        API client, types, forecast math
  src/app/api/    the server-side proxy and auth routes
docs/screenshots/ the images in this README
.github/workflows deploy-web.yml and deploy-backend.yml
```

## Run it locally

**Backend** (Postgres with pgvector, Redis, S3-compatible storage, migrations, API and worker, with stub models so no GPU is needed):

```bash
cd backend
docker-compose up -d --build
curl localhost:8000/health
open http://localhost:8000/docs
```

Load demo data with `python -m scripts.seed ./demo_videos --reset` (one folder per game). See [`backend/README.md`](backend/README.md) for real models, environment settings and scripts.

**Web app:**

```bash
cd frontend
cp .env.example .env.local   # set MINEDTV_API_KEY (and MINEDTV_API_BASE_URL for a local API)
npm install
npm run dev
```

## Tests and deploys

```bash
cd backend && .venv/bin/pytest          # 110+ tests, including the full pipeline on a generated video
cd frontend && npx tsc --noEmit && npm run build
```

Deploys are automatic on every push to `main`:

- **Web** (`frontend/**`): GitHub Actions builds and deploys to Vercel production.
- **Backend** (`backend/**`): tests run against real Postgres and Redis while the API and worker images build in parallel with a layer cache; then the database is migrated, the API is rolled out, the worker is updated and `/health` is checked. Google Cloud access is keyless, through Workload Identity Federation.
