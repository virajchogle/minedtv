"use client";

import { useEffect, useState } from "react";
import { Loader2, Moon, RefreshCw, Sun, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { PublishBadge } from "@/components/clip-actions";
import {
  BAND_MODERATE,
  BAND_STRONG,
  BAND_WEAK,
  STATUS_COPY,
  deleteVideo,
  fetchMyVideos,
  fetchServerConfig,
  formatDuration,
  reindexVideo,
  type Video,
} from "@/lib/api";
import type { ServerConfigOut } from "@/lib/minedtv-types";

export default function SettingsPage() {
  const [isDark, setIsDark] = useState(true);
  const [videos, setVideos] = useState<Video[]>([]);
  const [config, setConfig] = useState<ServerConfigOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  useEffect(() => {
    // Only your own clips: delete and re-index are owner actions.
    fetchMyVideos("all", 100)
      .then(setVideos)
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
    fetchServerConfig().then(setConfig).catch(() => setConfig(null));
  }, []);

  const toggleTheme = () => {
    const next = !isDark;
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("minedtv-theme", next ? "dark" : "light");
    setIsDark(next);
  };

  const handleDelete = async (video: Video) => {
    if (
      !window.confirm(
        `Delete the clip “${video.title}”? The original upload stays in your library's search index; only this clip goes.`
      )
    ) {
      return;
    }
    setBusyId(video.video_id);
    setError(null);
    try {
      await deleteVideo(video.video_id);
      setVideos((previous) => previous.filter((v) => v.video_id !== video.video_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Delete failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleReindex = async (video: Video) => {
    setBusyId(video.video_id);
    setError(null);
    try {
      // Reprocessing works on the whole upload (session), not a single clip.
      await reindexVideo(video.session_id ?? video.video_id);
      setVideos(await fetchMyVideos("all", 100));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Re-index failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Appearance, server configuration, and your clips.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
          <CardDescription>Choose your colour scheme.</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {isDark ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />}
            <span className="text-sm font-medium">{isDark ? "Dark mode" : "Light mode"}</span>
          </div>
          <Button variant="outline" onClick={toggleTheme} className="gap-2">
            {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            Switch to {isDark ? "light" : "dark"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Server configuration</CardTitle>
          <CardDescription>
            What the server runs with (read-only; set in the backend&apos;s environment).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-xs">
          {!config && <p className="text-muted-foreground">Backend unreachable.</p>}
          {config && (
            <>
              <ConfigRow label="Models">
                <ul className="space-y-0.5 font-mono">
                  <li>visual + text embeddings: {config.models.embedder}</li>
                  <li>speech to text: {config.models.transcriber}</li>
                  <li>highlight detector: {config.models.highlights}</li>
                  <li>
                    AI creator pack:{" "}
                    {config.models.creator
                      ? [config.models.creator, ...config.models.creator_fallbacks].join(" → ")
                      : "off (no Gemini key)"}
                  </li>
                  <li>creator persona tools: {config.models.personas ?? "off"}</li>
                </ul>
              </ConfigRow>
              <ConfigRow label="Search thresholds">
                <p className="font-mono">
                  {Object.entries(config.search)
                    .map(([name, value]) => `${name} ${value}`)
                    .join(" · ")}
                </p>
                <p className="mt-1 text-muted-foreground">
                  Similarity cut-offs for counting a frame or line as a match. Visual and speech scores are
                  contrastive: similarity to the query minus similarity to generic gameplay or talk.
                </p>
              </ConfigRow>
              <ConfigRow label="Match labels">
                <p className="font-mono">
                  strong ≥ {BAND_STRONG} · moderate ≥ {BAND_MODERATE} · weak ≥ {BAND_WEAK}
                </p>
                <p className="mt-1 text-muted-foreground">
                  How this app labels the confidence the server returns. Display bands, not probabilities.
                </p>
              </ConfigRow>
              <ConfigRow label="Features and limits">
                <p className="font-mono">
                  Gemini {config.features.gemini ? "on" : "off"} · YouTube posting{" "}
                  {config.features.youtube ? "on" : "off"} · accounts {config.features.accounts ? "on" : "off"} ·
                  uploads up to {config.limits.max_video_minutes} min / {(config.limits.max_upload_mb / 1024).toFixed(0)} GB
                </p>
              </ConfigRow>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Library</CardTitle>
          <CardDescription>
            Your clips. Re-index re-runs processing on the clip&apos;s upload (after a model change);
            delete removes the clip.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          {error && <p className="pb-3 text-sm text-destructive">{error}</p>}
          {loading && <p className="py-2 text-sm text-muted-foreground">Loading…</p>}
          {!loading && videos.length === 0 && (
            <p className="py-2 text-sm text-muted-foreground">No videos yet.</p>
          )}
          {videos.map((video) => (
            <div
              key={video.video_id}
              className="flex items-center justify-between gap-3 border-b border-border py-3 last:border-0"
            >
              <div className="min-w-0">
                <p className="flex items-center gap-2 truncate text-sm font-medium">
                  {video.title}
                  {video.publish_state && <PublishBadge state={video.publish_state} />}
                </p>
                <p className="text-xs text-muted-foreground">
                  {STATUS_COPY[video.processing_status].label} · {formatDuration(video.duration_seconds)}
                  {video.game && <> · {video.game}</>}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="gap-1.5"
                  onClick={() => handleReindex(video)}
                  disabled={busyId !== null}
                >
                  {busyId === video.video_id ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  Re-index
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
                  onClick={() => handleDelete(video)}
                  disabled={busyId !== null}
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </Button>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function ConfigRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      {children}
    </div>
  );
}
