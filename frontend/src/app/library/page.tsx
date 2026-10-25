"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, Loader2, RefreshCw, Upload } from "lucide-react";

import { SiteNav } from "@/components/hero/site-nav";
import { SearchPanel } from "@/components/search-panel";
import { ScreenTitle } from "@/components/ui/screen-header";
import { VideoCard } from "@/components/video-card";
import { fetchVideos, type SearchResult, type Video } from "@/lib/api";

// Videos being processed change state server-side, so the gallery re-polls
// while any of them is still working.
const POLL_INTERVAL_MS = 5000;

export default function GalleryPage() {
  const router = useRouter();
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setVideos(await fetchVideos());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load the library");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const processing = videos.filter(
    (video) => !video.searchable && video.processing_status !== "failed"
  );

  useEffect(() => {
    if (processing.length === 0) return;
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [processing.length, load]);

  const stats = useMemo(() => {
    const searchable = videos.filter((v) => v.searchable);
    return {
      searchable: searchable.length,
      segments: searchable.reduce((total, v) => total + v.segment_count, 0),
      failed: videos.filter((v) => v.processing_status === "failed").length,
    };
  }, [videos]);

  // A gallery result belongs to some other page: send the user to that video,
  // already seeked, so the single-video context is correct on arrival.
  const openResult = (result: SearchResult) => {
    router.push(`/video/${result.video_id}?t=${Math.floor(result.seek_seconds)}`);
  };

  return (
    <div className="min-h-screen bg-[var(--mtv-bg)] px-4 pb-16 pt-28 text-[var(--mtv-text)] sm:px-8 sm:pt-32">
      <SiteNav />

      <div className="mx-auto max-w-5xl space-y-10">
        <ScreenTitle
          action={
            <Link
              href="/upload"
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--mtv-gold)] px-3.5 py-2 text-[13px] font-bold text-[var(--mtv-on-gold)]"
            >
              <Upload className="h-3.5 w-3.5" />
              Upload
            </Link>
          }
        >
          My Library
        </ScreenTitle>

        <SearchPanel
          scope="gallery"
          placeholder="Search your clips…"
          large
          scopeLabel={
            <span>
              Searching all videos
              {stats.searchable > 0 && ` · ${stats.searchable} indexed`}
            </span>
          }
          onOpenResult={openResult}
          disabled={stats.searchable === 0}
          disabledMessage={
            loading ? "Loading your library…" : "Upload and index a video to start searching."
          }
        />

        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold">Library</h2>
              <p className="text-xs text-[var(--mtv-text-2)]">
                {stats.searchable} searchable · {stats.segments} indexed segments
                {processing.length > 0 && ` · ${processing.length} processing`}
                {stats.failed > 0 && ` · ${stats.failed} failed`}
              </p>
            </div>
            <button
              type="button"
              onClick={() => void load()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--mtv-divider)] px-3 py-1.5 text-xs transition-colors hover:bg-[var(--mtv-surface-high)]"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
          </div>

          {loading && (
            <div className="flex items-center gap-2 text-sm text-[var(--mtv-text-2)]">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading your library…
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-[var(--mtv-red)]/40 bg-[var(--mtv-red)]/10 p-3 text-sm text-[var(--mtv-red)]">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p>{error}</p>
                <button
                  type="button"
                  onClick={() => void load()}
                  className="mt-1 underline underline-offset-2"
                >
                  Try again
                </button>
              </div>
            </div>
          )}

          {!loading && !error && videos.length === 0 && (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-[var(--mtv-divider)] py-16 text-center">
              <Upload className="h-10 w-10 text-[var(--mtv-text-2)]/40" />
              <p className="text-sm">Your library is empty.</p>
              <Link
                href="/upload"
                className="text-sm text-[var(--mtv-gold)] underline underline-offset-2"
              >
                Upload your first video
              </Link>
            </div>
          )}

          {videos.length > 0 && (
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {videos.map((video) => (
                <VideoCard key={video.video_id} video={video} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
