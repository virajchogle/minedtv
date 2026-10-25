"use client";

/**
 * A clip's virality from the frame scorer: every sampled frame of the upload is scored 0–100
 * from data saved at upload (what the frame looks like, how much changes, detected events,
 * excited speech, readability), and the clip gets the average of its strongest frames.
 * Scores are relative to the rest of the same upload.
 */

import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus, TrendingUp } from "lucide-react";

import { VERDICT_CUTOFFS, formatTimestamp } from "@/lib/api";
import type { ClipViralityOut } from "@/lib/minedtv-types";
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

/** 0–100 track with the verdict cut-offs and the score as a dot. */
export function ScoreMeter({ score, compact = false }: { score: number; compact?: boolean }) {
  return (
    <div className={cn("relative w-full", compact ? "h-3" : "h-5")} role="img" aria-label={`${Math.round(score)} out of 100`}>
      <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-[var(--mtv-surface-high)]" />
      <div
        className="absolute left-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-[var(--mtv-gold)]/40"
        style={{ width: `${score}%` }}
      />
      {[VERDICT_CUTOFFS.mixed, VERDICT_CUTOFFS.promising, VERDICT_CUTOFFS.strong].map((c) => (
        <div key={c} className="absolute top-0 h-full w-px bg-[var(--mtv-divider)]" style={{ left: `${c}%` }} />
      ))}
      <div
        className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--mtv-gold)] ring-2 ring-[var(--mtv-surface)]"
        style={{ left: `${score}%` }}
      />
    </div>
  );
}

const SIGNALS: { key: keyof NonNullable<ClipViralityOut["components"]>; label: string; hint: string }[] = [
  { key: "visual", label: "Looks like a highlight", hint: "Action, skill or payoff, compared with the rest of the upload" },
  { key: "scene", label: "Sustained moment", hint: "Strength held across the surrounding scene" },
  { key: "novelty", label: "Something changes", hint: "Visual change between neighbouring frames" },
  { key: "event", label: "Detected events", hint: "Kills, clutches and other detected moments nearby" },
  { key: "speech", label: "Excited reactions", hint: "Hype or reaction speech nearby" },
  { key: "visibility", label: "Easy to see", hint: "Brightness, contrast and visible area" },
];

function Heading({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--mtv-text-2)]">{children}</p>;
}

const H = 120;

/** Score of every sampled frame across the clip; the peak is marked. Hover for exact values. */
function HypeCurve({ v }: { v: ClipViralityOut }) {
  const [hover, setHover] = useState<number | null>(null);
  const duration = Math.max(1, v.end_ms - v.start_ms);
  const pts = v.curve;
  if (pts.length < 2) return null;
  const x = (ms: number) => (ms / duration) * 100;
  const y = (s: number) => H - (s / 100) * (H - 8) - 4;
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.offset_ms)},${y(p.score)}`).join("");
  const area = `${line}L${x(pts[pts.length - 1].offset_ms)},${H}L${x(pts[0].offset_ms)},${H}Z`;
  const h = hover != null ? pts[hover] : null;

  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ms = ((event.clientX - rect.left) / rect.width) * duration;
    let best = 0;
    pts.forEach((p, i) => {
      if (Math.abs(p.offset_ms - ms) < Math.abs(pts[best].offset_ms - ms)) best = i;
    });
    setHover(best);
  };

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 100 ${H}`}
        preserveAspectRatio="none"
        className="block h-[120px] w-full"
        role="img"
        aria-label="Virality of each moment across the clip"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {[VERDICT_CUTOFFS.mixed, VERDICT_CUTOFFS.promising, VERDICT_CUTOFFS.strong].map((c) => (
          <line key={c} x1={0} x2={100} y1={y(c)} y2={y(c)} stroke="var(--mtv-divider)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        ))}
        <path d={area} fill="var(--mtv-gold)" fillOpacity={0.1} />
        <path d={line} fill="none" stroke="var(--mtv-gold)" strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {v.peak_offset_ms != null && (
          <line x1={x(v.peak_offset_ms)} x2={x(v.peak_offset_ms)} y1={0} y2={H} stroke="var(--mtv-text)" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.5} />
        )}
        {h && <line x1={x(h.offset_ms)} x2={x(h.offset_ms)} y1={0} y2={H} stroke="var(--mtv-text-2)" strokeWidth={1} vectorEffect="non-scaling-stroke" />}
      </svg>
      {h && (
        <div
          className="pointer-events-none absolute top-1 rounded-lg border border-[var(--mtv-divider)] bg-black/90 px-2 py-1 text-xs"
          style={{ left: `clamp(0px, calc(${x(h.offset_ms)}% - 40px), calc(100% - 90px))` }}
        >
          <span className="font-semibold">{Math.round(h.score)}</span>
          <span className="text-[var(--mtv-text-2)]"> at {formatTimestamp(h.offset_ms / 1000)}</span>
        </div>
      )}
      <div className="mt-1 flex justify-between text-[11px] text-[var(--mtv-text-2)]">
        <span>0:00</span>
        {v.peak_offset_ms != null && <span>Peak at {formatTimestamp(v.peak_offset_ms / 1000)}</span>}
        <span>{formatTimestamp(duration / 1000)}</span>
      </div>
    </div>
  );
}

export function ViralityReport({ v }: { v: ClipViralityOut }) {
  if (v.score == null || !v.verdict) return null;
  return (
    <div className="space-y-6 pt-1">
      <div className="space-y-3">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-1">
          <p className="text-5xl font-bold leading-none">
            {Math.round(v.score)}
            <span className="ml-1 text-base font-normal text-[var(--mtv-text-2)]">/100</span>
          </p>
          <VerdictBadge verdict={v.verdict} className="pb-1 text-sm" />
        </div>
        <ScoreMeter score={v.score} />
        <p className="text-[11px] text-[var(--mtv-text-2)]">
          weak · mixed {VERDICT_CUTOFFS.mixed} · promising {VERDICT_CUTOFFS.promising} · strong {VERDICT_CUTOFFS.strong}.
          Average of the clip&apos;s strongest moments, compared with the rest of this upload.
        </p>
      </div>

      <div className="space-y-2">
        <Heading>Moment by moment</Heading>
        <HypeCurve v={v} />
      </div>

      {v.components && (
        <div className="space-y-3">
          <Heading>What drives the score</Heading>
          <div className="space-y-2">
            {SIGNALS.map((s) => (
              <div key={s.key} className="grid grid-cols-[9.5rem_1fr_2.5rem] items-center gap-3 text-[13px]" title={s.hint}>
                <span className="truncate text-[var(--mtv-text-2)]">{s.label}</span>
                <div className="h-2.5 rounded-full bg-[var(--mtv-surface-high)]">
                  <div
                    className="h-full rounded-full bg-[var(--mtv-gold)]"
                    style={{ width: `${Math.max(1, Math.min(100, v.components![s.key]))}%` }}
                  />
                </div>
                <span className="text-right font-semibold tabular-nums">{Math.round(v.components![s.key])}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
