"use client";

/**
 * MinedTV Forecast — the dashboard's featured module. Projects a selected
 * clip's future attention and earnings from its REAL view count and REAL
 * virality score (see lib/forecast.ts for the math and what's illustrative
 * vs. real). Every control actually recomputes the chart: video, RPM,
 * horizon, scenario and chart mode are all live inputs to the same shared
 * daily series, never independent hardcoded states.
 */

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { Info, TrendingUp } from "lucide-react";

import { ScoreRange, VerdictBadge } from "@/components/virality-report";
import { Pill, PillRow } from "@/components/ui/pill";
import { EChartsBase, TOOLTIP_STYLE, type EChartsOption } from "@/components/ui/echarts-base";
import {
  HORIZONS,
  RPM_PRESETS,
  SCENARIOS,
  TIKTOK_RPM,
  forecast,
  summarize,
  type ForecastDay,
  type ForecastInput,
  type Scenario,
} from "@/lib/forecast";
import { clipViralityScore, formatDuration, verdictFor } from "@/lib/api";
import type { ClipAnalytics } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

/** Reads a CSS custom property's resolved color, client-side only — ECharts
 * draws to canvas and can't follow a live `var(--x)` reference the way SVG/CSS can. */
function useCssVar(name: string, fallback: string): string {
  const [value] = useState(() => {
    if (typeof document === "undefined") return fallback;
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  });
  return value;
}

type ChartMode = "cumulative_earnings" | "daily_earnings" | "views";

const CHART_MODES: { id: ChartMode; label: string }[] = [
  { id: "cumulative_earnings", label: "Cumulative earnings" },
  { id: "daily_earnings", label: "Daily earnings" },
  { id: "views", label: "Predicted views" },
];

const usd = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: n < 10 ? 2 : 0 })}`;
const compactNum = (n: number) => new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);

export function ForecastModule({ clips }: { clips: ClipAnalytics[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rpm, setRpm] = useState(TIKTOK_RPM);
  const [horizon, setHorizon] = useState<(typeof HORIZONS)[number]>(90);
  const [scenario, setScenario] = useState<Scenario>("expected");
  const [mode, setMode] = useState<ChartMode>("cumulative_earnings");
  const [now] = useState(() => Date.now());

  const selected = useMemo(
    () => clips.find((c) => c.clip.id === selectedId) ?? clips[0] ?? null,
    [clips, selectedId]
  );

  if (clips.length === 0) {
    return (
      <section className="rounded-2xl border border-dashed border-[var(--mtv-divider)] p-6 text-center text-sm text-[var(--mtv-text-2)]">
        Upload and publish a clip to see MinedTV Forecast.
      </section>
    );
  }
  if (!selected) return null;

  // Date.now() only runs in this lazy initializer (once, on mount) so the
  // component body stays pure for the React Compiler — a mount-time
  // snapshot is fine here, this doesn't need to tick live.
  const daysSincePublish = Math.max(
    0,
    Math.floor((now - new Date(selected.clip.published_at ?? selected.clip.created_at).getTime()) / 86_400_000)
  );
  const score = clipViralityScore(selected);

  const result = forecast({
    existingViews: selected.clip.view_count,
    viralityScore: score,
    daysSincePublish,
    rpm,
    scenario,
  });
  const summary = summarize(result, horizon);

  return (
    <section className="space-y-5 rounded-2xl border border-[var(--mtv-gold)]/25 bg-[var(--mtv-surface)] p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[var(--mtv-gold)]">
            <TrendingUp className="h-5 w-5" />
            <h2 className="text-lg font-bold uppercase tracking-wider">MinedTV Forecast</h2>
          </div>
          <p className="mt-1 text-sm text-[var(--mtv-text-2)]">
            Predict how a clip&apos;s attention and earning potential may evolve.
          </p>
        </div>
      </div>

      {/* ── video picker ── */}
      <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {clips.map((c) => (
          <button
            key={c.clip.id}
            type="button"
            onClick={() => setSelectedId(c.clip.id)}
            className={cn(
              "flex shrink-0 items-center gap-2 rounded-xl border px-2.5 py-1.5 text-left transition-colors",
              c.clip.id === selected.clip.id
                ? "border-[var(--mtv-gold)]/60 bg-[var(--mtv-gold)]/10"
                : "border-[var(--mtv-divider)] hover:bg-[var(--mtv-surface-high)]"
            )}
          >
            {c.clip.thumbnail_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={c.clip.thumbnail_url} alt="" className="h-9 w-14 shrink-0 rounded-md object-cover" />
            ) : (
              <span className="h-9 w-14 shrink-0 rounded-md bg-[var(--mtv-surface-high)]" />
            )}
            <span className="min-w-0 max-w-[10rem]">
              <span className="block truncate text-[12px] font-semibold">{c.clip.title ?? c.clip.game ?? "Untitled"}</span>
              <span className="text-[10px] text-[var(--mtv-text-2)]">{c.clip.view_count.toLocaleString()} views</span>
            </span>
          </button>
        ))}
      </div>

      {/* ── selected clip summary ── */}
      <div className="grid gap-3 rounded-xl bg-[var(--mtv-surface-high)] p-3 sm:grid-cols-[auto_1fr_auto]">
        <Link href={`/video/${selected.clip.id}`} className="shrink-0">
          {selected.clip.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={selected.clip.thumbnail_url} alt="" className="h-16 w-28 rounded-lg object-cover" />
          ) : (
            <span className="block h-16 w-28 rounded-lg bg-[var(--mtv-surface)]" />
          )}
        </Link>
        <div className="min-w-0 space-y-1">
          <p className="truncate text-sm font-semibold">{selected.clip.title ?? selected.clip.game ?? "Untitled clip"}</p>
          <p className="text-xs text-[var(--mtv-text-2)]">
            {formatDuration((selected.clip.end_ms - selected.clip.start_ms) / 1000)} ·{" "}
            {selected.clip.view_count.toLocaleString()} views · {selected.clip.like_count.toLocaleString()} likes ·{" "}
            {selected.clip.publish_state === "published" ? "Published" : "Not published"}
          </p>
          {score != null ? (
            <div className="max-w-xs">
              <VerdictBadge verdict={verdictFor(score)} score={score} className="mb-1" />
              <ScoreRange scores={selected.virality?.score_samples?.length ? selected.virality.score_samples : [score]} compact />
            </div>
          ) : (
            <p className="flex items-center gap-1 text-[11px] text-[var(--mtv-text-2)]">
              <Info className="h-3 w-3" /> Not yet scored — using a neutral estimate for this forecast.
            </p>
          )}
        </div>
      </div>

      {/* ── controls ── */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--mtv-text-2)]">Scenario</p>
          <PillRow>
            {SCENARIOS.map((s) => (
              <Pill key={s.id} selected={scenario === s.id} onClick={() => setScenario(s.id)}>
                {s.label}
              </Pill>
            ))}
          </PillRow>
        </div>
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--mtv-text-2)]">Assumed RPM</p>
          <div className="flex items-center gap-2">
            <select
              value={RPM_PRESETS.find((p) => p.rpm === rpm)?.id ?? "custom"}
              onChange={(e) => {
                const preset = RPM_PRESETS.find((p) => p.id === e.target.value);
                if (preset) setRpm(preset.rpm);
              }}
              className="rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] px-2 py-1.5 text-[13px]"
            >
              {RPM_PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
              <option value="custom">Custom</option>
            </select>
            <div className="flex items-center gap-1 text-[13px]">
              $
              <input
                type="number"
                min={0}
                step={0.01}
                value={rpm}
                onChange={(e) => setRpm(Math.max(0, Number(e.target.value) || 0))}
                className="w-16 rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] px-2 py-1.5 text-[13px]"
              />
              <span className="text-[var(--mtv-text-2)]">/1,000 views</span>
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-1.5">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--mtv-text-2)]">Forecast horizon</p>
        <PillRow>
          {HORIZONS.map((h) => (
            <Pill key={h} selected={horizon === h} onClick={() => setHorizon(h)}>
              {h}d
            </Pill>
          ))}
        </PillRow>
      </div>

      {/* ── headline stats ── */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label={`Earnings at ${horizon}d`} value={usd(summary.totalEarnings)} />
        <Stat label={`Views at ${horizon}d`} value={compactNum(summary.totalViews)} />
        <Stat label="Peak attention day" value={`Day ${Math.round(summary.peakDay)}`} />
        <Stat label="First 30-day earnings" value={usd(summary.earnings30d)} />
        <Stat label="Share earned in 30d" value={`${Math.round(summary.earningsShareFirst30d * 100)}%`} />
      </div>

      {/* ── chart mode toggle + chart ── */}
      <div className="space-y-3">
        <PillRow>
          {CHART_MODES.map((m) => (
            <Pill key={m.id} selected={mode === m.id} onClick={() => setMode(m.id)}>
              {m.label}
            </Pill>
          ))}
        </PillRow>
        <ForecastRangeChart
          existingViews={selected.clip.view_count}
          viralityScore={score}
          daysSincePublish={daysSincePublish}
          rpm={rpm}
          mode={mode}
          highlightHorizon={horizon}
        />
      </div>

      <p className="text-[11px] leading-relaxed text-[var(--mtv-text-2)]">
        Illustrative projection, not a guarantee of income. Predicted views scale with this clip&apos;s real virality
        score and recent view run-rate using one documented formula (see the forecast module source) — it has not
        been fitted to real outcomes. Earnings use an assumed TikTok RPM ($0.04 / 1k views) unless you change it —
        not a published Creativity Program rate, and not a Twitch or Medal figure.
        Cumulative figures only ever increase; daily figures can rise and fall.
      </p>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-[var(--mtv-surface-high)] p-3">
      <p className="text-[11px] uppercase tracking-wide text-[var(--mtv-text-2)]">{label}</p>
      <p className="mt-0.5 text-xl font-bold tabular-nums">{value}</p>
    </div>
  );
}

function valueOf(d: ForecastDay, mode: ChartMode): number {
  if (mode === "cumulative_earnings") return d.cumulativeEarnings;
  if (mode === "daily_earnings") return d.earnings;
  return d.views;
}

/**
 * Box-and-whisker, one box per forecast horizon: the whisker spans
 * conservative -> breakout at that horizon, the box line marks "expected" —
 * three real runs of the same forecast() engine (lib/forecast.ts), not a
 * single scenario's line. Replaces a third line chart with a shape that
 * actually shows the range of outcomes, per horizon, at a glance.
 */
function ForecastRangeChart({
  existingViews,
  viralityScore,
  daysSincePublish,
  rpm,
  mode,
  highlightHorizon,
}: {
  existingViews: number;
  viralityScore: number | null;
  daysSincePublish: number;
  rpm: number;
  mode: ChartMode;
  highlightHorizon: number;
}) {
  const gold = useCssVar("--mtv-gold", "#cbff3d");
  const divider = useCssVar("--mtv-divider", "rgba(255,255,255,0.12)");
  const text2 = useCssVar("--mtv-text-2", "rgba(255,255,255,0.6)");

  const boxData = useMemo(() => {
    const base: Omit<ForecastInput, "scenario"> = { existingViews, viralityScore, daysSincePublish, rpm };
    const byScenario = SCENARIOS.reduce((acc, s) => {
      acc[s.id] = forecast({ ...base, scenario: s.id });
      return acc;
    }, {} as Record<Scenario, ReturnType<typeof forecast>>);

    return HORIZONS.map((h) => {
      const vals = SCENARIOS.map((s) => valueOf(byScenario[s.id].days[h - 1], mode)).sort((a, b) => a - b);
      const [min, median, max] = vals;
      return { horizon: h, box: [min, min, median, max, max] };
    });
  }, [existingViews, viralityScore, daysSincePublish, rpm, mode]);

  const fmt = useCallback((n: number) => (mode === "views" ? compactNum(n) : usd(n)), [mode]);

  const option: EChartsOption = useMemo(
    () => ({
      grid: { left: 64, right: 20, top: 24, bottom: 36 },
      tooltip: {
        trigger: "item",
        ...TOOLTIP_STYLE,
        formatter: (params) => {
          const p = params as { name?: string; data?: number[] };
          const [min, , median, , max] = p.data ?? [0, 0, 0, 0, 0];
          return [
            `<div style="font-weight:600;margin-bottom:4px">At ${p.name}</div>`,
            `Breakout: ${fmt(max)}`,
            `Expected: ${fmt(median)}`,
            `Conservative: ${fmt(min)}`,
          ].join("<br/>");
        },
      },
      xAxis: {
        type: "category",
        data: boxData.map((b) => `${b.horizon}d`),
        axisLine: { lineStyle: { color: divider } },
        axisTick: { show: false },
        axisLabel: { color: text2, fontSize: 13 },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: divider, type: "dashed" } },
        axisLabel: { color: text2, fontSize: 12, formatter: (v: number) => fmt(v) },
      },
      series: [
        {
          type: "boxplot",
          data: boxData.map((b) => ({
            value: b.box,
            itemStyle: {
              color: b.horizon === highlightHorizon ? `${gold}33` : "rgba(255,255,255,0.04)",
              borderColor: gold,
              borderWidth: b.horizon === highlightHorizon ? 2.5 : 1.5,
            },
          })),
          boxWidth: ["35%", "55%"],
          animationDuration: 700,
          animationEasing: "cubicOut",
        },
      ],
    }),
    [boxData, divider, text2, gold, highlightHorizon, fmt]
  );

  return (
    <div>
      <EChartsBase option={option} height={260} />
      <p className="mt-1 text-[11px] text-[var(--mtv-text-2)]">
        Each box spans conservative -&gt; breakout at that horizon; the line through it marks the expected scenario.
        Highlighted box = your selected horizon.
      </p>
    </div>
  );
}
