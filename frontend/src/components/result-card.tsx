"use client";

import { useState } from "react";
import { ChevronDown, Clock, Play } from "lucide-react";

import { MatchBadge } from "@/components/match-badge";
import {
  absoluteUrl,
  formatTimestamp,
  type SearchResult,
  type SignalBreakdown,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const SIGNAL_NAMES: Record<SignalBreakdown["name"], string> = {
  semantic_visual: "Visual similarity",
  semantic_text: "Transcript / scene meaning",
  keyword: "Keyword match",
  rerank: "Gemini rerank",
};

function SignalRow({ signal }: { signal: SignalBreakdown }) {
  const percent = Math.round(signal.calibrated * 100);
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-3 text-xs">
        <span className="font-medium">{SIGNAL_NAMES[signal.name]}</span>
        <span className="font-mono text-muted-foreground">
          raw {signal.raw.toFixed(3)} · calibrated {signal.calibrated.toFixed(2)} · weight{" "}
          {signal.weight.toFixed(2)}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary/70 transition-all duration-500"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">{signal.detail}</p>
    </div>
  );
}

export function ResultCard({
  result,
  onOpen,
  showVideoTitle = true,
}: {
  result: SearchResult;
  onOpen: (result: SearchResult) => void;
  showVideoTitle?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const thumbnail = absoluteUrl(result.thumbnail_url);
  const evidence = result.transcript ?? result.scene_description;

  return (
    <article
      className={cn(
        "overflow-hidden rounded-xl border bg-card transition-colors",
        result.match.bucket === "no_reliable_match"
          ? "border-border/60 opacity-75"
          : "border-border hover:border-primary/50"
      )}
    >
      <div className="flex gap-4 p-3">
        <button
          type="button"
          onClick={() => onOpen(result)}
          className="group relative aspect-video w-40 shrink-0 overflow-hidden rounded-lg bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Play ${result.video_title} at ${formatTimestamp(result.seek_seconds)}`}
        >
          {thumbnail ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={thumbnail}
              alt=""
              className="h-full w-full object-cover transition-transform group-hover:scale-105"
            />
          ) : (
            <div className="flex h-full items-center justify-center">
              <Play className="h-6 w-6 text-muted-foreground/40" />
            </div>
          )}
          <span className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/40">
            <Play className="h-8 w-8 fill-white text-white opacity-0 transition-opacity group-hover:opacity-100" />
          </span>
          <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1.5 py-0.5 font-mono text-[11px] text-white">
            {formatTimestamp(result.seek_seconds)}
          </span>
        </button>

        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              {showVideoTitle && (
                <p className="truncate text-sm font-semibold">{result.video_title}</p>
              )}
              {showVideoTitle && (result.uploader || result.game) && (
                <p className="truncate text-xs text-muted-foreground">
                  {result.uploader && <>@{result.uploader}</>}
                  {result.uploader && result.game && " · "}
                  {result.game}
                </p>
              )}
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Clock className="h-3 w-3" />
                {formatTimestamp(result.start_seconds)} – {formatTimestamp(result.end_seconds)}
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <MatchBadge bucket={result.match.bucket} />
              <span className="font-mono text-[11px] text-muted-foreground">
                {Math.round(result.confidence * 100)}% sure
              </span>
            </div>
          </div>

          {evidence ? (
            <p className="line-clamp-2 text-sm text-muted-foreground">
              {result.transcript ? `“${result.transcript}”` : evidence}
            </p>
          ) : (
            <p className="text-sm italic text-muted-foreground">
              Matched on the sampled frame; no transcript or scene description is indexed here.
            </p>
          )}

          {result.moments.length > 1 && (
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {result.moments.slice(1).map((moment) => (
                <button
                  key={moment.offset_seconds}
                  type="button"
                  onClick={() => onOpen({ ...result, seek_seconds: moment.offset_seconds })}
                  title={moment.snippet ?? moment.signals.join(", ")}
                  className="inline-flex max-w-[16rem] items-center gap-1 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
                >
                  <span className="font-mono">{formatTimestamp(moment.offset_seconds)}</span>
                  <span className="truncate">
                    {moment.label ?? (moment.snippet ? `“${moment.snippet}”` : moment.signals.join(" + "))}
                  </span>
                  <span className="opacity-70">{Math.round(moment.confidence * 100)}%</span>
                </button>
              ))}
            </div>
          )}

          <button
            type="button"
            onClick={() => setExpanded((open) => !open)}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
            aria-expanded={expanded}
          >
            <ChevronDown
              className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-180")}
            />
            Why this matched
          </button>
        </div>
      </div>

      {expanded && (
        <div className="space-y-3 border-t bg-muted/25 px-4 py-3">
          <div className="flex items-baseline justify-between gap-3">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Score breakdown
            </h4>
            <span className="font-mono text-xs text-muted-foreground">
              evidence {result.match.evidence_score.toFixed(2)} · fusion{" "}
              {result.fusion_score.toFixed(4)}
            </span>
          </div>

          <div className="space-y-3">
            {result.match.signals.map((signal) => (
              <SignalRow key={signal.name} signal={signal} />
            ))}
          </div>

          <ul className="space-y-1 border-t border-border/50 pt-2 text-xs text-muted-foreground">
            {result.match.reasons.map((reason) => (
              <li key={reason}>• {reason}</li>
            ))}
          </ul>

          {result.transcript && (
            <p className="rounded-md bg-background/60 p-2 text-xs">
              <span className="font-semibold">Transcript · </span>
              {result.transcript}
            </p>
          )}
          {result.scene_description && (
            <p className="rounded-md bg-background/60 p-2 text-xs">
              <span className="font-semibold">Scene · </span>
              {result.scene_description}
            </p>
          )}
          {result.matched_terms.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Query terms found in this segment: {result.matched_terms.join(", ")}
            </p>
          )}

          <p className="border-t border-border/50 pt-2 text-[11px] leading-relaxed text-muted-foreground/70">
            Confidence comes from the backend: each signal is scored against a generic baseline
            (so &ldquo;it&rsquo;s a gameplay frame&rdquo; doesn&rsquo;t count as a match), and agreeing
            signals raise it. It&rsquo;s a ranking aid, not a probability.
          </p>
        </div>
      )}
    </article>
  );
}
