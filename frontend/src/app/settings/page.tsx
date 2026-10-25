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
import {
  STATUS_COPY,
  deleteVideo,
  fetchSearchConfig,
  fetchMyVideos,
  reindexVideo,
  type SearchConfig,
  type Video,
} from "@/lib/api";

export default function SettingsPage() {
  const [isDark, setIsDark] = useState(true);
  const [videos, setVideos] = useState<Video[]>([]);
  const [config, setConfig] = useState<SearchConfig | null>(null);
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
    fetchSearchConfig().then(setConfig).catch(() => setConfig(null));
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
        `Delete “${video.title}”? Its frames, segments and index entries are removed permanently.`
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
          Appearance, retrieval configuration, and library management.
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
          <CardTitle>Retrieval configuration</CardTitle>
          <CardDescription>
            Read-only view of the server settings. Change these in the backend .env file.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-xs">
          {!config && <p className="text-muted-foreground">Backend unreachable.</p>}
          {config && (
            <>
              <div>
                <p className="mb-1 font-semibold uppercase tracking-wide text-muted-foreground">
                  Models
                </p>
                <ul className="space-y-0.5 font-mono">
                  {Object.entries(config.models).map(([role, model]) => (
                    <li key={role}>
                      {role}: {model}
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="mb-1 font-semibold uppercase tracking-wide text-muted-foreground">
                  Signal weights
                </p>
                <p className="font-mono">
                  {Object.entries(config.weights)
                    .map(([name, weight]) => `${name} ${weight}`)
                    .join(" · ")}
                </p>
              </div>
              <div>
                <p className="mb-1 font-semibold uppercase tracking-wide text-muted-foreground">
                  Calibration anchors
                </p>
                <p className="font-mono">
                  {Object.entries(config.calibration)
                    .map(([name, [lo, hi]]) => `${name} ${lo}–${hi}`)
                    .join(" · ")}
                </p>
                <p className="mt-1 text-muted-foreground">
                  Heuristic anchors that put each signal on a comparable 0–1 scale. They are
                  not probability calibrations.
                </p>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Library</CardTitle>
          <CardDescription>
            Re-index a video after changing the embedding model, or delete it permanently.
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
                <p className="truncate text-sm font-medium">{video.title}</p>
                <p className="text-xs text-muted-foreground">
                  {STATUS_COPY[video.processing_status].label} · {video.frame_count} frames ·{" "}
                  {video.segment_count} segments
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
