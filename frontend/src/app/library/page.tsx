"use client";

/**
 * My Library — the acting user's own clips: My videos (private; uploads land
 * here), Published (public on MinedTV) and On YouTube (posted from MinedTV).
 * Search here is scoped to your clips and includes private ones.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Upload, X } from "lucide-react";

import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import { SiteNav } from "@/components/hero/site-nav";
import { SearchPanel } from "@/components/search-panel";
import { Pill, PillRow } from "@/components/ui/pill";
import { ScreenTitle } from "@/components/ui/screen-header";
import { VideoCard } from "@/components/video-card";
import { fetchMyVideos, type SearchResult, type Video } from "@/lib/api";

// Clips being processed change state server-side, so the list re-polls while any are working.
const POLL_INTERVAL_MS = 5000;

type Bucket = "all" | "mine" | "published" | "youtube";

const BUCKETS: { id: Bucket; label: string; hint?: string }[] = [
  { id: "all", label: "All" },
  { id: "mine", label: "My videos", hint: "Private: only you can see these. Publish one to put it on MinedTV." },
  { id: "published", label: "Published", hint: "Public on MinedTV. Open one to post it to YouTube." },
  { id: "youtube", label: "On YouTube", hint: "Posted to YouTube from MinedTV." },
];

const inBucket = (video: Video, bucket: Bucket) =>
  bucket === "all" ||
  (bucket === "mine" && video.publish_state !== "published") ||
  (bucket === "published" && video.publish_state === "published") ||
  (bucket === "youtube" && Boolean(video.youtube_url));

export default function LibraryPage() {
  // useSearchParams needs a Suspense boundary for static rendering.
  return (
    <Suspense>
      <Library />
    </Suspense>
  );
}

/** After Google's consent screen, /youtube/callback lands here with ?youtube=connected|error. */
function YouTubeConnectBanner() {
  const params = useSearchParams();
  const router = useRouter();
  const result = params.get("youtube");
  if (result !== "connected" && result !== "error") return null;
  const ok = result === "connected";
  return (
    <div
      className={
        ok
          ? "flex items-start gap-2 rounded-lg border border-[var(--mtv-green)]/40 bg-[var(--mtv-green)]/10 p-3 text-sm text-[var(--mtv-green)]"
          : "flex items-start gap-2 rounded-lg border border-[var(--mtv-red)]/40 bg-[var(--mtv-red)]/10 p-3 text-sm text-[var(--mtv-red)]"
      }
    >
      {ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
      <p className="flex-1">
        {ok
          ? "YouTube connected. Open a published clip and use Post to YouTube."
          : `Couldn't connect YouTube${params.get("message") ? `: ${params.get("message")}` : "."}`}
      </p>
      <button type="button" onClick={() => router.replace("/library")} aria-label="Dismiss">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

function Library() {
  const router = useRouter();
  const me = useCurrentUser();
  const [bucket, setBucket] = useState<Bucket>("all");
  const [allClips, setAllClips] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!me) {
      setAllClips([]);
      setLoading(false);
      return;
    }
    try {
      setAllClips(await fetchMyVideos("all", 100));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load your clips");
    } finally {
      setLoading(false);
    }
  }, [me]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  const videos = allClips.filter((v) => inBucket(v, bucket));
  const counts = Object.fromEntries(BUCKETS.map((b) => [b.id, allClips.filter((v) => inBucket(v, b.id)).length]));

  const processing = allClips.filter((v) => !v.searchable && v.processing_status !== "failed");
  useEffect(() => {
    if (processing.length === 0) return;
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [processing.length, load]);

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

        <YouTubeConnectBanner />

        {!me ? (
          <ChooseUserNotice action="see your videos" />
        ) : (
          <>
            <SearchPanel
              scope="gallery"
              mine
              placeholder={`Search ${me.username}'s clips, including private ones…`}
              large
              scopeLabel={<span>Searching your clips · {counts.all} total</span>}
              onOpenResult={openResult}
              disabled={counts.all === 0}
              disabledMessage={loading ? "Loading your clips…" : "Upload a video to start searching."}
            />

            <section className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <PillRow>
                  {BUCKETS.map((b) => (
                    <Pill key={b.id} selected={bucket === b.id} onClick={() => setBucket(b.id)}>
                      {b.label} · {counts[b.id] ?? 0}
                    </Pill>
                  ))}
                </PillRow>
                <button
                  type="button"
                  onClick={() => void load()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--mtv-divider)] px-3 py-1.5 text-xs transition-colors hover:bg-[var(--mtv-surface-high)]"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Refresh
                </button>
              </div>

              {BUCKETS.find((b) => b.id === bucket)?.hint && (
                <p className="text-xs text-[var(--mtv-text-2)]">{BUCKETS.find((b) => b.id === bucket)?.hint}</p>
              )}


              {loading && (
                <div className="flex items-center gap-2 text-sm text-[var(--mtv-text-2)]">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading your clips…
                </div>
              )}

              {error && (
                <div className="flex items-start gap-2 rounded-lg border border-[var(--mtv-red)]/40 bg-[var(--mtv-red)]/10 p-3 text-sm text-[var(--mtv-red)]">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    <p>{error}</p>
                    <button type="button" onClick={() => void load()} className="mt-1 underline underline-offset-2">
                      Try again
                    </button>
                  </div>
                </div>
              )}

              {!loading && !error && videos.length === 0 && (
                <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-[var(--mtv-divider)] py-16 text-center">
                  <Upload className="h-10 w-10 text-[var(--mtv-text-2)]/40" />
                  <p className="text-sm">
                    {bucket === "all" ? "You haven't uploaded anything yet." : "Nothing in this bucket."}
                  </p>
                  {bucket === "all" && (
                    <Link href="/upload" className="text-sm text-[var(--mtv-gold)] underline underline-offset-2">
                      Upload your first video
                    </Link>
                  )}
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
          </>
        )}
      </div>
    </div>
  );
}
