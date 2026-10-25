"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { AlertTriangle, Film, Loader2 } from "lucide-react";

import { EngagementBar, OwnerTools, PublishBadge } from "@/components/clip-actions";
import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import { SiteNav } from "@/components/hero/site-nav";
import { HlsPlayer, type HlsPlayerHandle } from "@/components/hls-player";
import { Comments } from "@/components/comments";
import { RelatedClips } from "@/components/related-clips";
import { SearchPanel } from "@/components/search-panel";
import {
  fetchVideoWithSegments,
  formatTimestamp,
  formatUploadDate,
  recordView,
  streamUrlFor,
  type SearchResult,
  type Video,
} from "@/lib/api";
import { usePageTitle } from "@/lib/use-page-title";

const noopSubscribe = () => () => {};

export default function VideoPage() {
  const params = useParams<{ videoId: string }>();
  const searchParams = useSearchParams();
  const videoId = params.videoId;
  // Set when arriving from a gallery result, so the player opens on the moment.
  const initialSeek = Number(searchParams.get("t") ?? "0");

  const playerRef = useRef<HlsPlayerHandle>(null);
  const [video, setVideo] = useState<Video | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  usePageTitle(video?.title || (error ? "Clip not found" : "Loading clip"));
  const [activeMoment, setActiveMoment] = useState<SearchResult | null>(null);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const startAt = Number.isFinite(initialSeek) && initialSeek > 0 ? initialSeek : 0;
  // Unpublished clips are only visible to their owner, so reload when the acting user changes.
  const me = useCurrentUser();
  const meId = me?.id ?? null;
  // The stored user is read after hydration; wait for it so the clip isn't fetched twice.
  const mounted = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  );

  useEffect(() => {
    if (!mounted) return;
    let cancelled = false;
    setLoading(true);
    fetchVideoWithSegments(videoId)
      .then((loaded) => {
        if (cancelled) return;
        setVideo(loaded.video);
        setError(null);
      })
      .catch((caught: Error) => {
        if (!cancelled) setError(caught.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [videoId, meId, mounted]);

  // Counted once per page view; failures are swallowed inside recordView.
  useEffect(() => {
    void recordView(videoId);
  }, [videoId]);

  // Seeking is handled inside the player, which defers until metadata lands.
  const openResult = useCallback((result: SearchResult) => {
    setActiveMoment(result);
    playerRef.current?.seekTo(result.seek_seconds);
    playerRef.current?.element?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  if (loading) {
    return (
      <Shell>
        <h1 className="sr-only">Loading clip</h1>
        <p className="flex items-center gap-2 text-sm text-[var(--mtv-text-2)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading clip…
        </p>
      </Shell>
    );
  }

  if (error || !video) {
    const missing = Boolean(error && /not found/i.test(error));
    return (
      <Shell>
        <h1 className="sr-only">{missing ? "Clip not found" : "Couldn't load clip"}</h1>
        <div className="max-w-2xl space-y-4">
          <p role="alert" className="flex items-start gap-2 text-sm text-[var(--mtv-red)]">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            {missing
              ? "This clip doesn't exist, or it's a private video only its owner can see."
              : (error ?? "This clip couldn't be loaded.")}
          </p>
          {missing && <ChooseUserNotice action="open your private videos" />}
        </div>
      </Shell>
    );
  }

  const isOwner = Boolean(me && video.owner_id === me.id);
  const meta = [video.uploader && `@${video.uploader}`, video.game, formatUploadDate(video.published_at ?? video.upload_date)]
    .filter(Boolean)
    .join(" · ");

  return (
    <Shell>
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-6">
          <div className="overflow-hidden rounded-2xl bg-black ring-1 ring-white/10">
            <HlsPlayer
              ref={playerRef}
              src={streamUrlFor(video)}
              poster={video.thumbnail_url}
              initialSeek={startAt}
              onError={setPlaybackError}
              className="max-h-[70vh] w-full"
            />
          </div>
          {playbackError && <p role="alert" className="text-xs text-[var(--mtv-red)]">{playbackError}</p>}

          <header className="space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{video.title}</h1>
              {isOwner && video.publish_state && video.publish_state !== "published" && (
                <PublishBadge state={video.publish_state} />
              )}
            </div>
            {meta && <p className="text-sm text-white/55">{meta}</p>}
          </header>

          <EngagementBar video={video} onChange={setVideo} />

          {activeMoment && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/70">
              <Film className="h-3.5 w-3.5" />
              <span>
                Playing the moment at <span className="font-mono">{formatTimestamp(activeMoment.seek_seconds)}</span> ·{" "}
                {activeMoment.match.label.toLowerCase()}
              </span>
              <button type="button" onClick={() => setActiveMoment(null)} className="underline underline-offset-2 hover:text-white">
                Clear
              </button>
            </div>
          )}

          <SearchPanel
            // Keyed by video so moving between clips resets the panel.
            key={video.video_id}
            scope="video"
            videoId={video.video_id}
            placeholder="Find a moment in this clip…"
            scopeLabel={<span>Search inside this clip</span>}
            onOpenResult={openResult}
            disabled={!video.searchable}
            disabledMessage={
              video.processing_status === "failed"
                ? `Processing failed, so this clip can't be searched. ${video.processing_error ?? ""}`
                : "This clip is still being indexed. Search opens once it's ready."
            }
          />

          {video.kind === "clip" && <Comments clipId={video.video_id} />}
        </div>

        <aside className="space-y-10">
          {isOwner && <OwnerTools video={video} onChange={setVideo} />}
          {video.game && <RelatedClips game={video.game} excludeId={video.video_id} />}
        </aside>
      </div>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen px-4 pb-20 pt-28 text-[var(--mtv-text)] sm:px-8 sm:pt-32">
      <SiteNav />
      <main id="main-content" className="mx-auto max-w-6xl">
        {children}
      </main>
    </div>
  );
}
