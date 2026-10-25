"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Search, X } from "lucide-react";

import { ResultCard } from "@/components/result-card";
import { Input } from "@/components/ui/input";
import {
  searchVideos,
  type MatchBucket,
  type SearchResponse,
  type SearchResult,
  type SearchScope,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const BUCKET_LABELS: Record<MatchBucket, string> = {
  strong: "strong",
  moderate: "moderate",
  weak: "weak",
  no_reliable_match: "no reliable match",
};

interface SearchPanelProps {
  scope: SearchScope;
  videoId?: string;
  placeholder: string;
  /** Rendered above the input so the active scope is never ambiguous. */
  scopeLabel: React.ReactNode;
  onOpenResult: (result: SearchResult) => void;
  disabled?: boolean;
  disabledMessage?: string;
  /** Bigger input + icons, for a page where this is the one focal action. */
  large?: boolean;
  /** Only the current user's clips (includes their drafts). */
  mine?: boolean;
}

export function SearchPanel({
  scope,
  videoId,
  placeholder,
  scopeLabel,
  onOpenResult,
  disabled = false,
  disabledMessage,
  large = false,
  mine = false,
}: SearchPanelProps) {
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef<AbortController | null>(null);

  // Changing scope must discard the previous mode's results immediately,
  // otherwise a gallery hit could linger on a single-video page.
  useEffect(() => {
    inFlight.current?.abort();
    setResponse(null);
    setError(null);
    setSearching(false);
  }, [scope, videoId, mine]);

  const clear = () => {
    inFlight.current?.abort();
    setQuery("");
    setResponse(null);
    setError(null);
    setSearching(false);
  };

  const run = async () => {
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
        signal: controller.signal,
        mine,
      });
      if (controller.signal.aborted) return;
      setResponse(result);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "Search failed");
      setResponse(null);
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  };


  const bucketSummary = response
    ? (Object.entries(response.bucket_counts) as [MatchBucket, number][])
        .filter(([, count]) => count > 0)
        .map(([bucket, count]) => `${count} ${BUCKET_LABELS[bucket]}`)
        .join(" · ")
    : "";

  return (
    <section className="space-y-4">
      <div className="space-y-2">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {scopeLabel}
        </div>

        <div className="relative">
          <button
            type="button"
            onClick={run}
            disabled={disabled}
            className={cn(
              "absolute left-4 top-1/2 -translate-y-1/2 disabled:opacity-40",
              large && "left-5"
            )}
            aria-label="Run search"
          >
            <Search
              className={cn(
                "text-muted-foreground transition-colors hover:text-foreground",
                large ? "h-6 w-6" : "h-5 w-5"
              )}
            />
          </button>

          <Input
            value={query}
            disabled={disabled}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") run();
              if (event.key === "Escape") clear();
            }}
            placeholder={placeholder}
            aria-label={placeholder}
            className={cn(
              "border-transparent bg-secondary/50 shadow-sm focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/40",
              large
                ? "h-16 pl-14 pr-14 text-lg font-semibold sm:text-xl"
                : "h-13 pl-12 pr-12 text-base"
            )}
          />

          {query && (
            <button
              type="button"
              onClick={clear}
              className={cn("absolute right-4 top-1/2 -translate-y-1/2", large && "right-5")}
              aria-label="Clear search"
            >
              <X
                className={cn(
                  "text-muted-foreground transition-colors hover:text-foreground",
                  large ? "h-6 w-6" : "h-5 w-5"
                )}
              />
            </button>
          )}
        </div>


        {disabled && disabledMessage && (
          <p className="text-xs text-muted-foreground">{disabledMessage}</p>
        )}
      </div>

      {searching && (
        <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Searching{scope === "video" ? " this video" : " every indexed video"}…
        </div>
      )}

      {error && (
        <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {!searching && response && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="text-lg font-semibold">
              {response.total_results} moment{response.total_results === 1 ? "" : "s"} for{" "}
              <span className="text-primary">“{response.query}”</span>
            </h2>
            <p className="font-mono text-xs text-muted-foreground">
              {response.latency_ms} ms · {response.pipeline}
            </p>
          </div>

          {bucketSummary && (
            <p className="text-xs text-muted-foreground">{bucketSummary}</p>
          )}

          {response.scope_enforced === "client" && (
            <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
              The API has no single-video filter, so this searched the whole library and
              narrowed the results in your browser. Moments in this video that fell outside
              the top matches overall will not appear.
            </p>
          )}

          {response.degraded.length > 0 && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200">
              <p className="font-medium">Some signals were unavailable for this search:</p>
              <ul className="mt-1 space-y-0.5">
                {response.degraded.map((note) => (
                  <li key={note}>• {note}</li>
                ))}
              </ul>
            </div>
          )}

          {response.total_results === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed py-16 text-center">
              <Search className="h-10 w-10 text-muted-foreground/30" />
              <p className="text-sm">
                Nothing in{" "}
                {scope === "video" ? "this video" : `${response.searchable_videos} indexed videos`}{" "}
                reliably matches “{response.query}”.
              </p>
              <p className="max-w-md text-xs text-muted-foreground">
                Try describing what is said or shown in the moment rather than naming the topic.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {response.results.map((result) => (
                <ResultCard
                  key={result.moment_id}
                  result={result}
                  onOpen={onOpenResult}
                  showVideoTitle={scope === "gallery"}
                />
              ))}
            </div>
          )}
        </div>
      )}

    </section>
  );
}
