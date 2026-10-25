# Team notes

Who owns what, and where each open piece plugs into the backend. Update this as things land.

## Status

- **Web app (live):** https://minedtv.vercel.app. Vercel deploys every push to `main` automatically (root directory `frontend`, `MINEDTV_API_KEY` set in Vercel's settings). Local dev still needs `frontend/.env.local` with the key.
- **Backend (Viraj):** live at `https://minedtv-api-818252181045.us-east1.run.app`. Uploads, processing, HLS clips, hybrid search with confidence and moments, likes/views, MP4 export and `/warmup` are done. Ask Viraj privately for the API key.
- **Android app (Rishi):** connected to the live API using [`backend/docs/android-integration.md`](backend/docs/android-integration.md).
- **Creator analysis + audience personas (Nihal):** `/creator/analyze`, `/creator/simulate` and `/creator/simulate-analysis` are live. Clip-based versions: `/clips/{id}/creator-pack` and `/clips/{id}/virality` (unpublished clips only).
- **Social (Viraj):** comments with replies, follows plus a following feed, and notifications (like, comment, reply, follow, upload ready, virality ready) are live. The web frontend doesn't show them yet.
- **Publish states:** clips go `draft` → `ready` (to post to YouTube) → `published`; only published clips are public. Posting clips from the `ready` bucket to YouTube is built (`/youtube/*`, `/clips/{id}/youtube`); it needs the Google OAuth client set up in `.env.prod`.

## Open work

| Area | Owner | Where it plugs in |
|---|---|---|
| **Highlight detector**: kills, headshots, clutches, wins | Nihal (could build on the Gemini work) | Implement `HighlightDetector.detect(video_path, session_id) -> list[DetectedEvent]` in [`backend/app/ml/interfaces.py`](backend/app/ml/interfaces.py), then set `HIGHLIGHT_BACKEND=package.module:ClassName`. Use the `type` values in `KNOWN_EVENT_TYPES` so text search can match them. The top events become labelled auto-clips. |
| **Search model quality** | Jasper (PixelPull background) | The `Embedder` protocol in the same file. Speech search uses CLIP's text encoder, which is weak at matching sentences; a proper sentence embedder for transcripts is the biggest quality win. Changing the vector size means changing `EMBEDDING_DIM` plus a migration and reprocessing. Re-measure the similarity thresholds in `app/config.py` (`visual_min_score`, `speech_min_score`; visual search is contrastive, see `app/services/search.py`) for any new model. |
| **Enhance job**: 9:16 reframe, captions, trim | Nihal | The text side (titles, captions, hashtags, key moments) exists in `/creator/analyze`. The video side (crop to 9:16, burn in captions, trim, render) can build on the MP4 export in [`backend/app/worker/export.py`](backend/app/worker/export.py) and report progress the way export does. The app's `EnhanceRepository` defines the contract it expects. |
| **App wiring** | Rishi | In progress |
| **Real gameplay videos** | Everyone | Drop recordings into a folder (one subfolder per game) and run `python -m scripts.seed <folder> --queue` against prod. Search quality can't be judged on test patterns. |

## How to work on the backend

- Local stack: `cd backend && docker-compose up -d --build`. Stub models need no GPU.
- Tests: `cd backend && .venv/bin/pytest`
- Contracts and plug-in steps: "Plugging in real models" in [`backend/README.md`](backend/README.md)
- Deploying needs `backend/.env.prod` (only on Viraj's machine): `PROJECT_ID=minedtv-78e0 ./deploy/cloudrun.sh`

## Demo day

- `python -m scripts.gpu_warm on` before the demo (about $0.60/hour), and `off` after.
- After the hackathon, pause the worker scheduler so it stops using Upstash commands: `gcloud scheduler jobs pause minedtv-worker-tick --location us-east1`
