"use client";

/**
 * The virality check's result, read top to bottom:
 *  - the headline: median score across the persona panels, its range, and the verdict;
 *  - how far it spreads: each audience layer's score against the bar it has to clear;
 *  - simulated engagement rates;
 *  - what the panel agreed on, and each persona's own reaction.
 *
 * One panel is noisy, so the backend runs several on the same AI analysis and keeps every
 * score (`score_samples`); older results have just the one.
 */

import { ArrowDownRight, ArrowUpRight, Check, Minus, TrendingUp, X } from "lucide-react";

import { VERDICT_CUTOFFS, median, verdictFor } from "@/lib/api";
import type { AudienceSimulation } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

type Verdict = "weak" | "mixed" | "promising" | "strong";

const VERDICT: Record<Verdict, { label: string; tone: string; Icon: typeof TrendingUp }> = {
  strong: { label: "Strong", tone: "text-[var(--mtv-green)]", Icon: TrendingUp },
  promising: { label: "Promising", tone: "text-[var(--mtv-gold)]", Icon: ArrowUpRight },
  mixed: { label: "Mixed", tone: "text-[var(--mtv-text-2)]", Icon: Minus },
  weak: { label: "Weak", tone: "text-[var(--mtv-red)]", Icon: ArrowDownRight },
};

/** Verdict as icon + word, so it never relies on colour alone. */
export function VerdictBadge({ verdict, score, className }: { verdict: Verdict; score?: number | null; className?: string }) {
  const v = VERDICT[verdict];
  return (
    <span className={cn("inline-flex items-center gap-1 text-[13px] font-semibold", v.tone, className)}>
      <v.Icon className="h-3.5 w-3.5" aria-hidden />
      {score != null && <span className="text-[var(--mtv-text)]">{Math.round(score)}</span>}
      {v.label}
    </span>
  );
}

/** Scores from every panel, or just the report's own for one-panel results. */
export function scoresOf(result: Pick<AudienceSimulation, "virality_score" | "score_samples">): number[] {
  return result.score_samples?.length ? result.score_samples : [result.virality_score];
}

/** 0–100 track with the verdict cut-offs, the panels' range as a band and the median as a dot. */
export function ScoreRange({ scores, compact = false }: { scores: number[]; compact?: boolean }) {
  const mid = median(scores);
  const lo = Math.min(...scores);
  const hi = Math.max(...scores);
  const cuts = [VERDICT_CUTOFFS.mixed, VERDICT_CUTOFFS.promising, VERDICT_CUTOFFS.strong];
  return (
    <div className={cn("relative w-full", compact ? "h-3" : "h-5")} role="img" aria-label={`Median ${Math.round(mid)} out of 100, range ${Math.round(lo)} to ${Math.round(hi)}`}>
      <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-[var(--mtv-surface-high)]" />
      {cuts.map((c) => (
        <div key={c} className="absolute top-0 h-full w-px bg-[var(--mtv-divider)]" style={{ left: `${c}%` }} />
      ))}
      {hi > lo && (
        <div
          className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-[var(--mtv-gold)]/35"
          style={{ left: `${lo}%`, width: `${hi - lo}%` }}
        />
      )}
      <div
        className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--mtv-gold)] ring-2 ring-[var(--mtv-surface)]"
        style={{ left: `${mid}%` }}
      />
    </div>
  );
}

const LAYER_LABEL: Record<string, string> = { target: "Target audience", adjacent: "Adjacent", outsider: "Outsiders" };

const ACTION_LABEL: Record<string, string> = {
  skip: "Skips",
  watch: "Watches",
  like: "Likes",
  comment: "Comments",
  save: "Saves",
  share: "Shares",
};

function Heading({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--mtv-text-2)]">{children}</p>;
}

/** A thin horizontal bar on a 0–100 scale, value at the tip. */
function Bar({ label, value, marker, detail }: { label: string; value: number; marker?: number; detail?: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr_2.5rem] items-center gap-3 text-[13px]">
      <span className="truncate text-[var(--mtv-text-2)]">{label}</span>
      <div className="relative h-2.5 rounded-full bg-[var(--mtv-surface-high)]">
        <div className="h-full rounded-full bg-[var(--mtv-gold)]" style={{ width: `${Math.max(1, Math.min(100, value))}%` }} />
        {marker != null && (
          <div className="absolute -top-1 h-[18px] w-0.5 rounded bg-[var(--mtv-text)]" style={{ left: `${marker}%` }} title={`Needs ${Math.round(marker)}`} />
        )}
      </div>
      <span className="text-right font-semibold tabular-nums">{Math.round(value)}</span>
      {detail && <span className="col-start-2 col-end-4 -mt-1.5 text-[11px] text-[var(--mtv-text-2)]">{detail}</span>}
    </div>
  );
}

export function ViralityReport({ result }: { result: AudienceSimulation }) {
  const scores = scoresOf(result);
  const mid = median(scores);
  const lo = Math.min(...scores);
  const hi = Math.max(...scores);
  const m = result.metrics;

  return (
    <div className="space-y-6 pt-1">
      {/* Headline */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-1">
          <p className="text-5xl font-bold leading-none">
            {Math.round(mid)}
            <span className="ml-1 text-base font-normal text-[var(--mtv-text-2)]">/100</span>
          </p>
          <VerdictBadge verdict={verdictFor(mid)} className="pb-1 text-sm" />
        </div>
        <ScoreRange scores={scores} />
        <div className="flex justify-between text-[11px] text-[var(--mtv-text-2)]">
          <span>
            {scores.length > 1
              ? `Median of ${scores.length} audience panels · range ${Math.round(lo)}–${Math.round(hi)}`
              : "One audience panel"}
          </span>
          <span>weak · mixed {VERDICT_CUTOFFS.mixed} · promising {VERDICT_CUTOFFS.promising} · strong {VERDICT_CUTOFFS.strong}</span>
        </div>
        <p className="text-[13px] text-[var(--mtv-text-2)]">
          Audience: <span className="text-[var(--mtv-text)]">{result.inferred_target_audience || result.inferred_niche}</span>
        </p>
      </div>

      {/* Spread */}
      <div className="space-y-3">
        <Heading>How far it spreads</Heading>
        <p className="text-[13px]">{result.cascade_summary}</p>
        <div className="space-y-3">
          {result.layers.map((l) => (
            <Bar
              key={l.layer}
              label={LAYER_LABEL[l.layer] ?? l.layer}
              value={l.score}
              marker={l.threshold}
              detail={
                <span className="inline-flex items-center gap-1">
                  {l.cleared_threshold ? <Check className="h-3 w-3 text-[var(--mtv-green)]" aria-hidden /> : <X className="h-3 w-3" aria-hidden />}
                  {l.cleared_threshold ? "Broke through" : "Didn't break through"} · needs {Math.round(l.threshold)} · {l.persona_count}{" "}
                  {l.persona_count === 1 ? "persona" : "personas"}
                </span>
              }
            />
          ))}
        </div>
      </div>

      {/* Engagement */}
      <div className="space-y-3">
        <Heading>Simulated engagement</Heading>
        <div className="space-y-2">
          {(
            [
              ["Watch", m.simulated_watch_rate],
              ["Watch to the end", m.simulated_completion_rate],
              ["Like", m.simulated_like_rate],
              ["Comment", m.simulated_comment_rate],
              ["Save", m.simulated_save_rate],
              ["Share", m.simulated_share_rate],
            ] as const
          ).map(([label, value]) => (
            <Bar key={label} label={label} value={value} />
          ))}
        </div>
        <p className="text-[11px] text-[var(--mtv-text-2)]">Percent of the simulated audience.</p>
      </div>

      {/* Consensus */}
      <div className="grid gap-4 sm:grid-cols-3">
        {(
          [
            ["What works", result.consensus_strengths],
            ["Risks", result.consensus_risks],
            ["Try changing", result.recommended_changes],
          ] as const
        ).map(([label, items]) =>
          items.length > 0 ? (
            <div key={label} className="space-y-1.5">
              <Heading>{label}</Heading>
              <ul className="list-disc space-y-1 pl-4 text-[13px]">
                {items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null
        )}
      </div>

      {/* Personas */}
      <div className="space-y-3">
        <Heading>What the personas said</Heading>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {result.persona_reviews.map((p) => (
            <div key={p.name} className="space-y-1.5 rounded-xl bg-[var(--mtv-surface-high)] p-3">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate text-[13px] font-semibold">{p.name}</p>
                <span className="shrink-0 text-[11px] text-[var(--mtv-text-2)]">{LAYER_LABEL[p.layer] ?? p.layer}</span>
              </div>
              <p className="text-[11px] text-[var(--mtv-text-2)]">
                Hook <span className="font-semibold text-[var(--mtv-text)]">{p.hook_score}</span> ·{" "}
                {ACTION_LABEL[p.primary_action] ?? p.primary_action}
              </p>
              {p.reaction && <p className="text-[13px]">“{p.reaction}”</p>}
              {p.friction && <p className="text-[11px] text-[var(--mtv-text-2)]">Friction: {p.friction}</p>}
            </div>
          ))}
        </div>
      </div>

      <p className="text-[11px] text-[var(--mtv-text-2)]">{result.disclaimer}</p>
    </div>
  );
}
