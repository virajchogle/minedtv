# Connecting the MinedIt Android app

Drop-in code for [rishikesh-web/MinedTv](https://github.com/rishikesh-web/MinedTv). It fits the app's existing
`Clip`, `SearchRepository` and `AppServices` so the screens don't change. Networking uses
`HttpURLConnection` + `org.json` (both built into Android), so it needs no new HTTP or JSON libraries.

- Base URL: `https://minedtv-api-818252181045.us-east1.run.app` (interactive docs at `/docs`)
- Every request needs `X-API-Key: <key>`. Requests that act as a user also need `X-User-Id: <uuid>`.
- Real sign-in exists too: `POST /auth/login {"login": "<username or email>", "password": "..."}` (or
  `/auth/signup {"username", "email", "password"}`) returns `{token, expires_at, user}`. Send
  `Authorization: Bearer <token>` and the API knows who you are without `X-User-Id`. While testing
  (`REQUIRE_LOGIN=false` on the server), `X-User-Id` alone keeps working and anyone may act as any user,
  so keep the demo-user picker; moving to login can wait until after the demo.
- `*.m3u8` playlist URLs need no key, so the player can fetch them directly.
- Example responses for every endpoint: [`api-examples/`](api-examples/)

## 1. Keep the key out of git

`local.properties` (already gitignored):
```properties
minedtv.apiKey=<the key>
minedtv.userId=ef57c626-6b84-4da9-af1a-bdf00eb0470d
```

`app/build.gradle.kts`:
```kotlin
import java.util.Properties

val localProps = Properties().apply {
    rootProject.file("local.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}

android {
    defaultConfig {
        // ...
        buildConfigField("String", "API_BASE_URL", "\"https://minedtv-api-818252181045.us-east1.run.app\"")
        buildConfigField("String", "API_KEY", "\"${localProps.getProperty("minedtv.apiKey", "")}\"")
        buildConfigField("String", "DEMO_USER_ID", "\"${localProps.getProperty("minedtv.userId", "")}\"")
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}
```

`AndroidManifest.xml` (inside `<manifest>`):
```xml
<uses-permission android:name="android.permission.INTERNET" />
```

## 2. Give `Clip` the server's fields

Add defaulted fields at the end so `SampleData` and `MyLibrary` keep compiling:

```kotlin
data class Clip(
    val id: Int,
    val title: String,
    val game: String,
    val user: String,
    val views: Int,
    val likes: Int,
    val comments: Int,
    val duration: String,
    val age: String,
    val colors: List<Color>,
    // From the backend; null for sample data.
    val remoteId: String? = null,
    val sessionId: String? = null,
    val playlistUrl: String? = null,
    val thumbnailUrl: String? = null,
    val startMs: Long = 0,
    val endMs: Long = 0,
    val likedByMe: Boolean = false
)
```

## 3. API client

`data/api/MinedTvApi.kt`:
```kotlin
package com.example.minedtv.data.api

import com.example.minedtv.BuildConfig
import com.example.minedtv.data.Clip
import com.example.minedtv.data.SampleData
import com.example.minedtv.data.share.formatDuration
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.time.Duration
import java.time.Instant

class ApiException(val code: Int, message: String) : Exception(message)

object MinedTvApi {
    private val base = BuildConfig.API_BASE_URL.trimEnd('/')
    var userId: String = BuildConfig.DEMO_USER_ID

    suspend fun get(path: String): JSONObject = JSONObject(request("GET", path))
    suspend fun getArray(path: String): JSONArray = JSONArray(request("GET", path))
    suspend fun post(path: String, body: JSONObject? = null): JSONObject = JSONObject(request("POST", path, body))
    suspend fun delete(path: String): JSONObject = JSONObject(request("DELETE", path))

    private suspend fun request(method: String, path: String, body: JSONObject? = null): String =
        withContext(Dispatchers.IO) {
            val conn = (URL(base + path).openConnection() as HttpURLConnection).apply {
                requestMethod = method
                connectTimeout = 15_000
                readTimeout = 60_000 // first search after idle can take a while (GPU cold start)
                setRequestProperty("X-API-Key", BuildConfig.API_KEY)
                if (userId.isNotEmpty()) setRequestProperty("X-User-Id", userId)
                setRequestProperty("Accept", "application/json")
                if (body != null) {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json")
                    outputStream.use { it.write(body.toString().toByteArray()) }
                }
            }
            try {
                val code = conn.responseCode
                val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use { it.readText() }.orEmpty()
                if (code !in 200..299) throw ApiException(code, "HTTP $code: $text")
                text
            } finally {
                conn.disconnect()
            }
        }

    fun q(value: String): String = URLEncoder.encode(value, "UTF-8")

    // --- JSON -> app models -------------------------------------------------

    /** The app keys lists by Int id; derive a stable one from the UUID. */
    fun intId(uuid: String): Int = uuid.hashCode() and 0x7fffffff

    fun clipFrom(o: JSONObject): Clip {
        val game = o.optString("game").ifEmpty { "Unknown" }
        val durationMs = o.getLong("duration_ms")
        return Clip(
            id = intId(o.getString("id")),
            title = o.optString("title").ifEmpty { "Untitled" },
            game = game,
            user = o.getJSONObject("user").getString("username"),
            views = o.getLong("view_count").toInt(),
            likes = o.getLong("like_count").toInt(),
            comments = 0, // no comments API yet
            duration = formatDuration((durationMs / 1000).toInt()),
            age = ageOf(o.getString("created_at")),
            colors = SampleData.games.firstOrNull { it.name.equals(game, ignoreCase = true) }?.colors
                ?: SampleData.palettes[(game.hashCode() and 0x7fffffff) % SampleData.palettes.size],
            remoteId = o.getString("id"),
            sessionId = o.getString("session_id"),
            playlistUrl = o.getString("playlist_url"),
            thumbnailUrl = o.optString("thumbnail_url").ifEmpty { null },
            startMs = o.getLong("start_ms"),
            endMs = o.getLong("end_ms"),
            likedByMe = o.optBoolean("liked_by_me", false)
        )
    }

    private fun ageOf(iso: String): String = runCatching {
        val d = Duration.between(Instant.parse(iso), Instant.now())
        when {
            d.toMinutes() < 1 -> "now"
            d.toHours() < 1 -> "${d.toMinutes()}m"
            d.toDays() < 1 -> "${d.toHours()}h"
            d.toDays() < 7 -> "${d.toDays()}d"
            else -> "${d.toDays() / 7}w"
        }
    }.getOrDefault("")

    // --- endpoints ----------------------------------------------------------

    suspend fun feed(cursor: String? = null, limit: Int = 20): Pair<List<Clip>, String?> {
        val o = get("/feed?limit=$limit" + (cursor?.let { "&cursor=${q(it)}" } ?: ""))
        val items = o.getJSONArray("items")
        val clips = (0 until items.length()).map { clipFrom(items.getJSONObject(it)) }
        return clips to o.optString("next_cursor").ifEmpty { null }
    }

    suspend fun userClips(userId: String): List<Clip> {
        val items = get("/users/$userId/clips?limit=50").getJSONArray("items")
        return (0 until items.length()).map { clipFrom(items.getJSONObject(it)) }
    }

    suspend fun like(remoteId: String, liked: Boolean): JSONObject =
        if (liked) post("/clips/$remoteId/like") else delete("/clips/$remoteId/like")

    suspend fun view(remoteId: String) {
        post("/clips/$remoteId/view")
    }
}
```

Note: `org.json`'s `optString` returns the string `"null"` for JSON nulls on some Android versions. The
fields above that can be null (`game`, `title`, `thumbnail_url`, `next_cursor`) are worth guarding with
`if (o.isNull("x")) null else o.getString("x")` if you see literal "null" in the UI.

## 4. Real search behind the existing `SearchRepository`

`data/search/RemoteSearchRepository.kt`. Swap it in with `AppServices.searchRepository = RemoteSearchRepository()`:
```kotlin
package com.example.minedtv.data.search

import com.example.minedtv.data.Clip
import com.example.minedtv.data.SampleData
import com.example.minedtv.data.api.MinedTvApi
import com.example.minedtv.data.share.formatDuration
import org.json.JSONObject

class RemoteSearchRepository : SearchRepository {

    override suspend fun search(query: SearchQuery): SearchResponse {
        var path = "/search?q=${MinedTvApi.q(query.text)}&limit=${query.limit.coerceAtMost(50)}"
        if (query.scope == SearchScope.Library && MinedTvApi.userId.isNotEmpty()) path += "&user_id=${MinedTvApi.userId}"
        val o = MinedTvApi.get(path)
        val results = o.getJSONArray("results")
        val hits = (0 until results.length()).map { hitFrom(results.getJSONObject(it), query.scope) }
        val topScore = hits.maxOfOrNull { it.score } ?: 1f
        return SearchResponse(
            query = query.text,
            scope = query.scope,
            interpretation = SearchInterpretation(
                games = hits.map { it.clip.game }.distinct().take(3),
                events = hits.flatMap { h -> h.moments.map { it.label } }.distinct().take(4)
            ),
            // Server scores are small RRF numbers; rescale so the UI's 0..1 confidence looks sensible.
            hits = hits.map { it.copy(score = it.score / topScore) },
            tookMs = o.getLong("took_ms")
        )
    }

    private fun hitFrom(r: JSONObject, scope: SearchScope): SearchHit {
        val id = if (r.isNull("clip_id")) r.getString("session_id") else r.getString("clip_id")
        val start = r.getLong("start_ms")
        val end = r.getLong("end_ms")
        val match = r.getLong("match_t_ms")
        val game = if (r.isNull("game")) "Unknown" else r.getString("game")
        val signals = r.getJSONArray("signals").let { a -> (0 until a.length()).map { a.getString(it) } }
        val snippet = if (r.isNull("transcript_snippet")) null else r.getString("transcript_snippet")
        val clip = Clip(
            id = MinedTvApi.intId(id),
            title = if (r.isNull("title")) "Untitled" else r.getString("title"),
            game = game,
            user = r.getJSONObject("user").getString("username"),
            views = 0, likes = 0, comments = 0,
            duration = formatDuration(((end - start) / 1000).toInt()),
            age = "",
            colors = SampleData.games.firstOrNull { it.name.equals(game, ignoreCase = true) }?.colors ?: SampleData.palettes[0],
            remoteId = if (r.isNull("clip_id")) null else r.getString("clip_id"),
            sessionId = r.getString("session_id"),
            playlistUrl = r.getString("playlist_url"),
            thumbnailUrl = if (r.isNull("thumbnail_url")) null else r.getString("thumbnail_url"),
            startMs = start,
            endMs = end
        )
        // Moment times are relative to the clip/window, which is what the player sees.
        val momentAt = (match - start).coerceAtLeast(0)
        val moments = buildList {
            add(Moment(clip.id, momentAt, (momentAt + 4_000).coerceAtMost(end - start), labelFor(signals),
                snippet?.let { "“$it”" } ?: "Matched by ${signals.joinToString(" + ")}", 1f))
            if (scope == SearchScope.Library) {
                val others = r.getJSONArray("other_moments_ms")
                for (i in 0 until others.length()) {
                    val t = others.getLong(i) - start
                    if (t in 0..(end - start)) add(Moment(clip.id, t, t + 4_000, "Also here", "Another match", 0.7f))
                }
            }
        }.sortedBy { it.startMs }
        return SearchHit(clip, r.getDouble("score").toFloat(), moments)
    }

    private fun labelFor(signals: List<String>) = when {
        "event" in signals -> "Highlight"
        "speech" in signals || "keyword" in signals -> "Voice chat"
        else -> "On screen"
    }

    override suspend fun suggestions(prefix: String): List<String> =
        listOf("the clutch", "when my friend screamed", "headshot", "squad wipe", "victory", "funny moment")
            .filter { it.startsWith(prefix.lowercase()) }
}
```

## 5. Playing clips (Media3 ExoPlayer)

`gradle/libs.versions.toml`:
```toml
[versions]
media3 = "1.5.1"
coil = "3.0.4"

[libraries]
media3-exoplayer = { group = "androidx.media3", name = "media3-exoplayer", version.ref = "media3" }
media3-exoplayer-hls = { group = "androidx.media3", name = "media3-exoplayer-hls", version.ref = "media3" }
media3-ui = { group = "androidx.media3", name = "media3-ui", version.ref = "media3" }
coil-compose = { group = "io.coil-kt.coil3", name = "coil-compose", version.ref = "coil" }
coil-network = { group = "io.coil-kt.coil3", name = "coil-network-okhttp", version.ref = "coil" }
```
`app/build.gradle.kts`:
```kotlin
implementation(libs.media3.exoplayer)
implementation(libs.media3.exoplayer.hls)
implementation(libs.media3.ui)
implementation(libs.coil.compose)
implementation(libs.coil.network)
```

A player composable to replace the gradient box in `ClipDetailScreen` when `clip.playlistUrl != null`:
```kotlin
@OptIn(androidx.media3.common.util.UnstableApi::class)
@Composable
fun HlsPlayer(url: String, seekToMs: Long = 0, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val player = remember(url) {
        ExoPlayer.Builder(context).build().apply {
            setMediaItem(MediaItem.fromUri(url))
            prepare()
            if (seekToMs > 0) seekTo(seekToMs)
            playWhenReady = true
        }
    }
    DisposableEffect(player) { onDispose { player.release() } }
    AndroidView(
        factory = { PlayerView(it).apply { this.player = player; useController = true } },
        modifier = modifier
    )
}
```
Imports: `androidx.media3.common.MediaItem`, `androidx.media3.exoplayer.ExoPlayer`,
`androidx.media3.ui.PlayerView`, `androidx.compose.ui.viewinterop.AndroidView`,
`androidx.compose.ui.platform.LocalContext`.

For search hits, pass `seekToMs = moment.startMs` to jump straight to the matched second.

Thumbnails: replace the gradient in `ClipThumbnail` with
`AsyncImage(model = item.thumbnailUrl, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())`
when `item.thumbnailUrl != null` (import `coil3.compose.AsyncImage`).

## 6. Home feed

In `HomeScreen`, load once and fall back to sample data on error:
```kotlin
var remote by remember { mutableStateOf<List<Clip>?>(null) }
LaunchedEffect(seed) {
    remote = runCatching { MinedTvApi.feed().first }
        .onFailure { Logger.e("Feed failed", it) }
        .getOrNull()
}
val clips = remote?.takeIf { it.isNotEmpty() } ?: SampleData.clips
```

When a clip is opened, call `MinedTvApi.view(clip.remoteId!!)` once. Have the like button call
`MinedTvApi.like(clip.remoteId!!, liked)`.

## 7. Newer API features

- **Warm-up on launch:** fire `MinedTvApi.post("/warmup")` in a background coroutine when the app
  starts and ignore the result. It wakes the GPU so the first search is fast.
- **Real confidence:** each search result has `confidence` (0–1, comparable across queries). Use it
  instead of rescaling `score`. Weak matches are already filtered out server side.
- **Rich moments:** `moments` is a list (best first) of
  `{t_ms, offset_ms, confidence, signals, label, snippet, thumbnail_url}`. `offset_ms` is where to
  seek in that result's `playlist_url`. This replaces `match_t_ms - start_ms` and `other_moments_ms`, so the
  "Also here · Another match" placeholders can show real quotes, labels and thumbnails.
- **MP4 export for sharing:** `POST /clips/{id}/export` returns `status: "processing"`. Poll
  `GET /clips/{id}/export` every ~5 s until `status == "ready"`, then download `url` (a plain MP4)
  and hand it to TikTok or Instagram. It takes about 1 minute (the worker runs every minute).
  Exports are cached per clip range, so a second POST is instant.
- **AI share highlight:** for Share â†’ Enhance with AI, call `POST /clips/{id}/highlights` with
  `{"platform":"tiktok","mode":"single","captions":true,"caption_style":"bold","hook":true}`.
  Poll `GET /clips/{id}/highlights` with the same values as query parameters. Show `stage` and
  `progress` while `status == "processing"`; on `ready`, download `video_url`. The response also has
  timed `captions`, selected `moments` with human-readable `reason`, `summary`, `suggested_caption`,
  and `hashtags` for the Review screen. `mode=montage` joins several significant scenes. Results are
  cached per clip range and options. No source re-upload is needed.
- **Stable media URLs:** thumbnails, segments and exports now use a fixed public R2 URL, so Coil and
  ExoPlayer can cache them.

## 8. My videos, publishing and virality

The flow is **upload → My videos (private) → Publish → Post to YouTube**. A clip's `publish_state` is
`draft` (private, "My videos") or `published` (public). `ready` is a legacy private state: treat it like
`draft`. `POST /clips/{id}/mark-ready` still works but the web app no longer uses it.

- The feed, search and other users' profiles only show `published` clips. **New uploads start as
  `draft`, so add a Publish button** that calls `POST /clips/{id}/publish` (owner's `X-User-Id`).
  `POST /clips/{id}/unpublish` takes it back to private.
- On the user's own profile, `GET /users/{me}/clips?state=draft|ready|published|unpublished|all`
  (with `X-User-Id: {me}`) gives the buckets; `unpublished` = My videos. Each clip has `youtube_url`
  once it's been posted to YouTube. Anyone else only ever gets published clips.
- "Search your clips" (library scope) should pass `user_id={me}`. That search includes the user's own
  private clips; global search never does.
- **Virality (Nihal's frame scorer; the persona panel is gone):** every upload is scored moment by
  moment when it's processed, and its auto-clips are cut at the highest-scoring peaks. `GET
  /clips/{id}/virality` (owner only, no query options) returns `score` (0–100), `verdict`
  (weak/mixed/promising/strong), `peak_offset_ms`, `components` (visual, scene, novelty, event, speech,
  visibility, each 0–100) and `curve` (`[{offset_ms, score}]` for a "moment by moment" chart). Scores are
  relative to the rest of the same upload. If `status` is `none` (uploads from before this), `POST
  /clips/{id}/virality` scores it in a few seconds without touching any clips; poll GET. Remove the old
  platform/persona options, `result`, `score_samples` and the extra `/creator/simulate-analysis` panels.
- **Views:** `POST /clips/{id}/view` now counts once per viewer per clip every 30 minutes, and owners'
  own views don't count. Send `X-Viewer-Id: <random UUID kept per install>` when no user is picked, or
  every signed-out phone behind the same network counts as one viewer.
- **Analytics:** `GET /users/{me}/analytics?days=30` (owner only) returns real per-day `views`, `likes`,
  `comments`, `new_followers` (UTC days, zero-filled), `period` vs `previous_period` totals, and each clip's
  period stats plus `virality {status, score, verdict}`. Use it for the dashboard's charts
  instead of the demo data.
- **AI creator pack:** `POST /clips/{id}/creator-pack` returns titles, caption, hashtags and YouTube
  metadata for the clip. Poll `GET` the same way.

## 9. Comments, follows and the Inbox

- **Comments** (clip detail): `GET /clips/{id}/comments` returns top-level comments newest first, each with
  `replies` (oldest first), `reply_count` and `can_delete`, plus `total` and `next_cursor`. Post with
  `POST /clips/{id}/comments {"body": "...", "parent_id": null}`; set `parent_id` to reply. Delete with
  `DELETE /comments/{id}` (author or clip owner). Every clip response also has `comment_count`.
- **Profile:** `GET /users/{id}` (with `X-User-Id`) adds `follower_count`, `following_count`,
  `published_clip_count`, `followed_by_me` and `follows_me`.
- **Follow button:** `POST`/`DELETE /users/{id}/follow` returns `{following, follower_count}`. Lists are at
  `GET /users/{id}/followers` and `/following`.
- **Home "Following" tab:** `GET /feed/following` (same shape and pagination as `/feed`).
- **Inbox:** `GET /notifications` returns items with `type` (like, comment, reply, follow, upload_ready,
  virality_ready), a ready-to-show `message`, `actor`, `clip {id, title, thumbnail_url}`, `read` and
  `created_at`, plus `unread_count`. For the badge, poll `GET /notifications/unread-count`. When the
  Inbox opens, call `POST /notifications/read {"all": true}`, or send `{"ids": [...]}` for specific ones.

## 10. Post to YouTube

1. `GET /youtube/status` returns `{configured, connected, channel_title}`.
2. If not connected: `GET /youtube/connect` returns `auth_url`. Open it in a Custom Tab or browser. The user approves on Google and lands on a "YouTube connected" page (or the web app). Then check status again.
3. On a **published** clip: `POST /clips/{id}/youtube {"privacy": "unlisted"}`. Title, description and tags default to the AI creator pack; pass your own to override them. Then poll `GET /clips/{id}/youtube` until `status` is `published` and show the `url`. The owner also gets a `youtube_posted` notification.

Uploads are private-only until Google audits the app, and only Google accounts added as test users in
the Cloud console can connect (ask Viraj to add yours). Each clip in lists carries `youtube_url` once
posted: show an "On YouTube" badge or link with it. For TikTok and Reels, share the MP4 from `/clips/{id}/export` through the Android share sheet (`IntentPlatformPublisher`), since their APIs need an app review.

## 10b. Content moderation

Every upload's transcript and some sampled frames are checked by Gemini (Jasper's step, between
transcription and highlights):

- Sessions and clips carry `moderation_severity` (`none` | `mild` | `severe`), `age_restricted`
  (true for mild or severe) and, for the owner, `moderation_reason`. Show an 18+ badge or a
  tap-to-reveal cover on `age_restricted` clips.
- **Severe** content stops processing: the session's `status` becomes `blocked` (a new value next to
  `ready` and `failed`) and no clips are made. Treat `blocked` as finished, and show the owner
  `moderation_reason` instead of a spinner.

## 11. Uploading from the phone (optional)

1. `POST /uploads` with `{"filename": "x.mp4", "content_type": "video/mp4", "game": "Valorant", "title": "..."}`
   returns `upload_url` and `session_id`.
2. `PUT` the file bytes to `upload_url` with header `Content-Type: video/mp4`. Don't send the API key
   there; it's a direct R2 link.
3. `POST /uploads/{session_id}/complete`.
4. Poll `GET /sessions/{session_id}` (or stream `/sessions/{id}/status?api_key=...`) until
   `status == "ready"`. That's usually 1–2 minutes, since the worker starts within a minute.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `401 Missing or invalid API key` | `API_KEY` empty in `BuildConfig`: check `local.properties`, then rebuild. |
| `401 Unknown X-User-Id` | Wrong user UUID; `GET /users` lists them. |
| First search takes 10–30 s | The GPU model is cold-starting on Modal; it's fast after that. |
| Video won't play | Use `playlist_url` as is (it's HLS, `.m3u8`), and make sure `media3-exoplayer-hls` is included. |
| `"null"` shown as a title | See the `org.json` null note in section 3. |
