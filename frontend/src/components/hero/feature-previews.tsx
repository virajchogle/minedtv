"use client";

/**
 * Two live search previews on the landing page.
 *
 * These run the real backend search — same endpoints, same retrieval pipeline
 * and same match-strength values the app uses. Nothing here is simulated: if
 * the backend is unreachable or no videos are indexed, the card says so rather
 * than displaying invented clips or confidence numbers.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, Film, Library, Loader2, Search } from "lucide-react";
import { motion } from "framer-motion";

import { ResultCard } from "@/components/result-card";
import {
  fetchVideos,
  searchVideos,
  type SearchResponse,
  type SearchResult,
  type Video,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Availability = "checking" | "ready" | "empty" | "offline";

export function FeaturePreviews() {
  const [availability, setAvailability] = useState<Availability>("checking");
  const [videos, setVideos] = useState<Video[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchVideos()
      .then((all) => {
        if (cancelled) return;
        const searchable = all.filter((video) => video.searchable);
        setVideos(searchable);
        setAvailability(searchable.length > 0 ? "ready" : "empty");
      })
      .catch(() => {
        if (!cancelled) setAvailability("offline");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const focusVideo = videos[0];

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <PreviewCard
        icon={<Library className="h-4 w-4" />}
        eyebrow="Across your library"
        title="Search every clip at once"
        body="One natural-language query, ranked across every indexed video. Results are moments, not files."
        placeholder="the moment someone clutches a 1v3"
        availability={availability}
        scope="gallery"
        videoCount={videos.length}
      />
      <PreviewCard
        icon={<Film className="h-4 w-4" />}
        eyebrow={focusVideo ? `Inside “${focusVideo.title}”` : "Inside one clip"}
        title="Search within a single video"
        body="Scope the same engine to one video and get only its timestamps — enforced server-side, not filtered in the browser."
        placeholder="where the fight starts"
        availability={availability}
        scope="video"
        videoId={focusVideo?.video_id}
        videoCount={videos.length}
      />
    </div>
  );
}

function PreviewCard({
  icon,
  eyebrow,
  title,
  body,
  placeholder,
  availability,
  scope,
  videoId,
  videoCount,
}: {
  icon: React.ReactNode;
  eyebrow: string;
  title: string;
  body: string;
  placeholder: string;
  availability: Availability;
  scope: "gallery" | "video";
  videoId?: string;
  videoCount: number;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  const disabled = availability !== "ready" || (scope === "video" && !videoId);

  const run = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed || disabled) return;

    inFlight.current?.abort();
    const controller = new AbortController();
    inFlight.current = controller;

    setSearching(true);
    setError(null);
    try {
      const result = await searchVideos({
        query: trimmed,
        scope,
        videoId,
        limit: 3,
        signal: controller.signal,
      });
      if (!controller.signal.aborted) setResponse(result);
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : "Search failed");
        setResponse(null);
      }
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  }, [query, disabled, scope, videoId]);

  const openResult = (result: SearchResult) => {
    router.push(`/video/${result.video_id}?t=${Math.floor(result.seek_seconds)}`);
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-col rounded-2xl border border-white/10 bg-white/[0.03] p-5 backdrop-blur-sm"
    >
      <div className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-white/45">
        {icon}
        {eyebrow}
      </div>
      <h3 className="text-lg font-semibold text-white">{title}</h3>
      <p className="mt-1.5 text-sm leading-relaxed text-white/55">{body}</p>

      <div className="relative mt-4">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-white/35" />
        <input
          value={query}
          disabled={disabled}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void run();
          }}
          placeholder={placeholder}
          aria-label={title}
          className={cn(
            "h-11 w-full rounded-xl border border-white/10 bg-black/30 pl-10 pr-24 text-sm text-white placeholder:text-white/30",
            "focus:border-white/25 focus:outline-none focus:ring-2 focus:ring-white/15",
            disabled && "cursor-not-allowed opacity-50"
          )}
        />
        <button
          type="button"
          onClick={() => void run()}
          disabled={disabled || searching || !query.trim()}
          className="absolute right-1.5 top-1.5 h-8 rounded-lg bg-[var(--mtv-gold)] px-3 text-xs font-bold text-[var(--mtv-on-gold)] transition-opacity hover:opacity-90 disabled:opacity-35"
        >
          {searching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Search"}
        </button>
      </div>

      <div className="mt-3 flex-1">
        {availability === "checking" && (
          <p className="text-xs text-white/40">Connecting to the search backend…</p>
        )}

        {availability === "offline" && (
          <StatusNote
            tone="warn"
            text="The MinedTV backend isn’t reachable, so live search is unavailable here. Start it to try this."
          />
        )}

        {availability === "empty" && (
          <StatusNote
            tone="info"
            text="No indexed videos yet. Upload a clip and this searches it for real — no sample data is shown."
          />
        )}

        {error && <StatusNote tone="warn" text={error} />}

        {response && !searching && (
          <div className="space-y-2.5">
            <p className="text-xs text-white/40">
              {response.total_results} moment{response.total_results === 1 ? "" : "s"} ·{" "}
              {response.latency_ms}ms · {response.pipeline}
            </p>
            {response.total_results === 0 ? (
              <StatusNote
                tone="info"
                text={`Nothing in ${
                  scope === "video" ? "this video" : `${videoCount} indexed videos`
                } reliably matches that. The engine reports no reliable match rather than guessing.`}
              />
            ) : (
              response.results.map((result) => (
                <ResultCard
                  key={result.moment_id}
                  result={result}
                  onOpen={openResult}
                  showVideoTitle={scope === "gallery"}
                />
              ))
            )}
          </div>
        )}

        {!response && availability === "ready" && !error && (
          <p className="text-xs text-white/35">
            Live search against {videoCount} indexed video{videoCount === 1 ? "" : "s"}. Press
            Enter to run it.
          </p>
        )}
      </div>

      {scope === "gallery" && (
        <Link
          href="/library"
          className="mt-4 text-xs text-white/50 underline-offset-4 transition-colors hover:text-white hover:underline"
        >
          Open the full library →
        </Link>
      )}
      {scope === "video" && videoId && (
        <Link
          href={`/video/${videoId}`}
          className="mt-4 text-xs text-white/50 underline-offset-4 transition-colors hover:text-white hover:underline"
        >
          Open this video →
        </Link>
      )}
    </motion.section>
  );
}

function StatusNote({ tone, text }: { tone: "info" | "warn"; text: string }) {
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-xl border p-3 text-xs leading-relaxed",
        tone === "warn"
          ? "border-amber-400/25 bg-amber-400/5 text-amber-200/90"
          : "border-white/10 bg-white/[0.02] text-white/55"
      )}
    >
      <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{text}</span>
    </div>
  );
}
