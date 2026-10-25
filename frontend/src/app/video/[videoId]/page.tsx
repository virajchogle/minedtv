"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, Film, Loader2 } from "lucide-react";

import { ClipActions, PublishBadge } from "@/components/clip-actions";
import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import { HlsPlayer, type HlsPlayerHandle } from "@/components/hls-player";
import { Comments } from "@/components/comments";
import { RelatedClips } from "@/components/related-clips";
import { SearchPanel } from "@/components/search-panel";
import {
  fetchVideoWithSegments,
  formatTimestamp,
  recordView,
  streamUrlFor,
  type SearchResult,
  type Video,
} from "@/lib/api";

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
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading video…
      </div>
    );
  }

  if (error || !video) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 p-8">
        <BackToGallery />
        {error && /not found/i.test(error) && <ChooseUserNotice action="open your private videos" />}
        <div className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            {error && /not found/i.test(error)
              ? "This clip doesn't exist, or it's a private video that only its owner can see."
              : (error ?? "This video could not be loaded.")}
          </p>
        </div>
      </div>
    );
  }


  return (
    <div className="mx-auto max-w-5xl space-y-6 p-8">
      <BackToGallery />

      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{video.title}</h1>
          {video.publish_state && <PublishBadge state={video.publish_state} />}
        </div>
        {(video.uploader || video.game) && (
          <p className="text-sm text-muted-foreground">
            {video.uploader && <>@{video.uploader}</>}
            {video.uploader && video.game && " · "}
            {video.game}
          </p>
        )}
        {video.summary && (
          <p className="max-w-3xl pt-1 text-sm text-muted-foreground">{video.summary}</p>
        )}
        {video.topics.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {video.topics.map((topic) => (
              <span
                key={topic}
                className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground"
              >
                {topic}
              </span>
            ))}
          </div>
        )}
      </header>

      <div className="overflow-hidden rounded-xl border bg-black">
        <HlsPlayer
          ref={playerRef}
          src={streamUrlFor(video)}
          poster={video.thumbnail_url}
          initialSeek={startAt}
          onError={setPlaybackError}
          className="max-h-[60vh] w-full"
        />
      </div>

      {playbackError && (
        <p className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
          {playbackError}
        </p>
      )}

      <ClipActions video={video} onChange={setVideo} />

      {activeMoment && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border bg-muted/30 px-3 py-2 text-xs">
          <Film className="h-3.5 w-3.5 text-muted-foreground" />
          <span>
            Playing the moment at{" "}
            <span className="font-mono">{formatTimestamp(activeMoment.seek_seconds)}</span> —{" "}
            {activeMoment.match.label.toLowerCase()}
          </span>
          <button
            type="button"
            onClick={() => setActiveMoment(null)}
            className="ml-auto text-muted-foreground underline underline-offset-2 hover:text-foreground"
          >
            Clear
          </button>
        </div>
      )}

      <SearchPanel
        // Keyed by video so navigating between videos resets the panel state
        // rather than carrying the previous video's results across.
        key={video.video_id}
        scope="video"
        videoId={video.video_id}
        placeholder={`Search in “${video.title}”…`}
        scopeLabel={
          <span className="flex items-center gap-1.5">
            <Film className="h-3.5 w-3.5" />
            Searching in this video only
          </span>
        }
        onOpenResult={openResult}
        disabled={!video.searchable}
        disabledMessage={
          video.processing_status === "failed"
            ? `Processing failed, so this video is not searchable. ${video.processing_error ?? ""}`
            : "This video is still being indexed. Search will open once it is ready."
        }
      />

      {video.kind === "clip" && <Comments clipId={video.video_id} />}

      {video.game && <RelatedClips game={video.game} excludeId={video.video_id} />}

      {video.processing_status === "visual_only" && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
          Only the visual index is available for this video, so searches match on appearance
          rather than spoken content.
        </p>
      )}
    </div>
  );
}

function BackToGallery() {
  return (
    <Link
      href="/library"
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" />
      All videos
    </Link>
  );
}
