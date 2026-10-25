# Adaptive Music API

This document covers only the adaptive-background-music feature. The feature selects a licensed track based on a video's visuals, filename, and available dialogue, then mixes it with the original audio.

## Behavior summary

- Music catalog: `https://pub-415da819582e4b6390d0637419173960.r2.dev/music/catalog.json`
- Catalog size: 20 Kevin MacLeod tracks
- License: CC BY 4.0
- Supported catalog moods: `hype`, `action`, `epic`, `dark`, `horror`, `stealth`, `chiptune`, `funny`, `electronic`, and `rock`
- Mix level: 50% normally and 30% during detected speech
- Output audio: AAC, stereo, 48 kHz, 160 kbps
- Track storage: the selected MP3 is read from its public R2 URL and exists locally only inside the temporary render directory
- Attribution: every music response includes the exact `credit` line that clients must display wherever the track is used

Energetic gameplay is intentionally biased toward the `hype` pool. Clear horror, stealth, comedy, or victory signals can select their corresponding mood instead.

## Authentication

Production requests require the normal MinedIt API authentication:

```http
X-API-Key: <MINEDIT_API_KEY>
```

Stored-clip endpoints are owner-only and additionally use the same user authentication as the rest of the application. Local development may run without API-key enforcement depending on configuration.

## 1. Add music to a complete uploaded video

### `POST /creator/music`

Uploads a video, preserves the complete video without cutting or adding captions, selects one track, and returns after the mixed MP4 is ready. This is a synchronous request.

### Request

Content type:

```http
multipart/form-data
```

| Field | Type | Required | Description |
|---|---|---:|---|
| `video` | File | Yes | Video receiving the adaptive music bed. Supported extensions: MP4, MOV, MKV, WebM, M4V, AVI, MPEG, and MPG. |

The upload limit is controlled by `CREATOR_MAX_UPLOAD_MB`, which defaults to 500 MB.

### cURL example

```bash
curl -X POST "${API_BASE_URL}/creator/music" \
  -H "X-API-Key: ${MINEDIT_API_KEY}" \
  -F "video=@clip.mp4;type=video/mp4"
```

### JavaScript example

```ts
const form = new FormData();
form.set("video", file, file.name);

const response = await fetch(`${apiBaseUrl}/creator/music`, {
  method: "POST",
  headers: { "X-API-Key": apiKey },
  body: form,
});

if (!response.ok) throw new Error(await response.text());
const result: DirectMusicOut = await response.json();
```

### Successful response: `200 OK`

```json
{
  "run_id": "17724a7d-f712-4e10-8151-98446540684c",
  "filename": "fast-action-rush.mp4",
  "duration_ms": 15000,
  "width": 1920,
  "height": 1080,
  "speech_cue_count": 4,
  "transcript_source": "gemini",
  "music_mixed": true,
  "music": {
    "id": "volatile-reaction",
    "title": "Volatile Reaction",
    "artist": "Kevin MacLeod",
    "mood": "hype",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Volatile%20Reaction.mp3",
    "credit": "\"Volatile Reaction\" Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0 License"
  },
  "video_url": "https://api.example.com/creator/music/17724a7d-f712-4e10-8151-98446540684c.mp4",
  "download_url": "https://api.example.com/creator/music/17724a7d-f712-4e10-8151-98446540684c.mp4?download=true"
}
```

### Response fields

| Field | Type | Description |
|---|---|---|
| `run_id` | UUID string | Identifier for this temporary direct-upload render. |
| `filename` | String | Original uploaded filename. |
| `duration_ms` | Integer | Full output duration in milliseconds. The music-only endpoint does not shorten the video. |
| `width` | Integer | Original display width. |
| `height` | Integer | Original display height. |
| `speech_cue_count` | Integer | Number of timed speech cues used for dialogue-aware volume changes. May be `0`. |
| `transcript_source` | Enum | `transcriber`, `gemini`, or `none`. |
| `music_mixed` | Boolean | `true` when the returned MP4 contains the selected music. A music-only request fails instead of returning a successful response with `false`. |
| `music` | Object | Selected track and legally required attribution metadata. |
| `video_url` | URL string | Streamable MP4 URL. |
| `download_url` | URL string | Same MP4 with download disposition enabled. |

### `music` object

| Field | Type | Description |
|---|---|---|
| `id` | String | Stable catalog track identifier. |
| `title` | String | Track title. |
| `artist` | String | Track artist. |
| `mood` | String | Mood requested by the selection engine. |
| `license` | String | License name; currently `CC BY 4.0`. |
| `license_url` | URL string | Canonical license page. |
| `source_url` | URL string | Original publisher's source for the track. |
| `credit` | String | Exact attribution line. Display this in UI and include it in descriptions when publishing the video. |

## 2. Stream or download the completed video

### `GET /creator/music/{run_id}.mp4`

Streams the generated MP4 and supports normal HTTP byte-range playback.

Query parameter:

| Parameter | Type | Default | Description |
|---|---|---:|---|
| `download` | Boolean | `false` | When `true`, returns the filename `music-enhanced.mp4` as a download. |

Examples:

```http
GET /creator/music/17724a7d-f712-4e10-8151-98446540684c.mp4
GET /creator/music/17724a7d-f712-4e10-8151-98446540684c.mp4?download=true
```

Successful response:

```http
200 OK
Content-Type: video/mp4
Accept-Ranges: bytes
```

Direct-upload results are temporary and expire according to `STANDALONE_HIGHLIGHT_TTL_S`, which defaults to 24 hours.

## 3. Enable music on a stored clip highlight or montage

### Start the render

```http
POST /clips/{clip_id}/highlights
Content-Type: application/json
```

```json
{
  "platform": "tiktok",
  "mode": "montage",
  "captions": true,
  "caption_style": "bold",
  "hook": true,
  "music": true
}
```

`music` defaults to `true`. Set it to `false` to render without background music.

This endpoint is asynchronous and normally returns `202 Accepted` with `status: "processing"`.

### Poll the render

```http
GET /clips/{clip_id}/highlights?platform=tiktok&mode=montage&captions=true&caption_style=bold&hook=true&music=true
```

Important: every polling option must match the POST body, including `music`. These options identify the cached render. Omitting `music` or polling with a different value can query a different render and leave the UI appearing stuck on `processing`.

Frontend query construction:

```ts
new URLSearchParams({
  platform: options.platform,
  mode: options.mode,
  captions: String(options.captions),
  caption_style: options.caption_style,
  hook: String(options.hook),
  music: String(options.music),
});
```

### Processing response

```json
{
  "clip_id": "11b85c06-6175-49f5-a212-4e45b40e8684",
  "status": "processing",
  "stage": "analyzing",
  "progress": 0.42,
  "error": null,
  "start_ms": 12000,
  "end_ms": 52000,
  "platform": "tiktok",
  "mode": "montage",
  "captions_enabled": true,
  "caption_style": "bold",
  "hook_enabled": true,
  "music_enabled": true,
  "algorithm_version": null,
  "video_url": null,
  "download_url": null,
  "width": null,
  "height": null,
  "duration_ms": null,
  "frames_analyzed": 0,
  "captions_burned": false,
  "music_mixed": false,
  "music": null,
  "moments": [],
  "captions": [],
  "summary": null,
  "suggested_caption": null,
  "hashtags": []
}
```

### Ready response: music-related portion

The full response retains the highlight fields above. When ready, these fields describe the music result:

```json
{
  "status": "ready",
  "stage": "rendering",
  "progress": 1.0,
  "music_enabled": true,
  "music_mixed": true,
  "music": {
    "id": "volatile-reaction",
    "title": "Volatile Reaction",
    "artist": "Kevin MacLeod",
    "mood": "hype",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Volatile%20Reaction.mp3",
    "credit": "\"Volatile Reaction\" Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0 License"
  },
  "video_url": "https://cdn.example.com/highlights/clip-id/render.mp4",
  "download_url": "https://cdn.example.com/highlights/clip-id/render.mp4"
}
```

Meaning of the music state fields:

- `music_enabled`: the request asked for music.
- `music_mixed`: the finished MP4 actually contains music.
- `music`: selected track metadata; `null` while processing, when disabled, or if the optional music enhancement failed during a stored-highlight render.

## 4. Direct highlight upload with optional music

The existing direct highlight endpoint also accepts music:

```http
POST /creator/highlights
Content-Type: multipart/form-data
```

| Field | Type | Default |
|---|---|---:|
| `video` | File | Required |
| `mode` | `single` or `montage` | `montage` |
| `captions` | Boolean | `true` |
| `caption_style` | `bold`, `minimal`, or `gamer` | `bold` |
| `music` | Boolean | `true` |

Each object in the returned `clips` array includes:

```json
{
  "music_mixed": true,
  "music": {
    "id": "volatile-reaction",
    "title": "Volatile Reaction",
    "artist": "Kevin MacLeod",
    "mood": "hype",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "source_url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Volatile%20Reaction.mp3",
    "credit": "\"Volatile Reaction\" Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0 License"
  }
}
```

## 5. YouTube attribution behavior

No new YouTube request field is required. When `POST /clips/{clip_id}/youtube` posts a completed montage whose manifest has `music_mixed: true`, the backend automatically appends this to the description:

```text
Music: "Volatile Reaction" Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0 License
```

The credit is appended whether the description came from the AI creator pack or was supplied by the client, unless the exact credit is already present.

## Error responses

All JSON errors use FastAPI's standard shape:

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Typical cause |
|---:|---|
| `401` | Missing or invalid production API key/authentication. |
| `403` | Authenticated user does not own the stored clip. |
| `404` | Render ID does not exist or the temporary direct result expired. |
| `413` | Direct upload exceeds `CREATOR_MAX_UPLOAD_MB`. |
| `422` | Empty upload, unsupported video extension/content type, invalid highlight option, or stored clip exceeds configured limits. |
| `502` | R2 catalog/MP3 fetch, analysis, or FFmpeg mixing failed for `POST /creator/music`. |
| `503` | FFmpeg/ffprobe unavailable, Gemini unavailable where required, or stored-highlight job could not be queued. |

## Client implementation checklist

1. Use multipart `POST /creator/music` when the user uploads a video solely to add music.
2. Keep the request open until the synchronous response arrives.
3. Play `video_url` and use `download_url` for saving.
4. Display `music.title`, `music.artist`, `music.mood`, and the complete `music.credit` line.
5. Open `music.license_url` when the user requests license details.
6. For stored highlights, include `music` in both the POST body and every GET polling query.
7. Treat `music_mixed`, rather than `music_enabled`, as confirmation that the output contains music.
8. Do not cache direct result URLs permanently because they expire.
