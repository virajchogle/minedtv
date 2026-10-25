"use client";

/**
 * Expected Income — one continuous series: solid where it's built from real
 * tracked views, dashed where it's projected from each clip's virality score.
 * The two halves share one cumulative total so the dashed line picks up
 * exactly where the solid one stops.
 */

import { useMemo, useState } from "react";
import { Sparkles } from "lucide-react";

import { Pill, PillRow } from "@/components/ui/pill";
import { EChartsBase, TOOLTIP_STYLE, type EChartsOption } from "@/components/ui/echarts-base";
import { clipViralityScore } from "@/lib/api";
import { SCENARIOS, TIKTOK_RPM, forecast, type Scenario } from "@/lib/forecast";
import type { AnalyticsDay, ClipAnalytics } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

const PROJECTION_DAYS = 60;
const CHECKPOINTS = [15, 30, 60] as const;

function daysSince(iso: string, now: number): number {
  return Math.max(0, Math.floor((now - new Date(iso).getTime()) / 86_400_000));
}

const usd = (n: number) =>
  `$${n.toLocaleString(undefined, { maximumFractionDigits: n < 10 ? 2 : 0 })}`;

function useCssVar(name: string, fallback: string): string {
  const [value] = useState(() => {
    if (typeof document === "undefined") return fallback;
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  });
  return value;
}

export function IncomeForecastChart({ clips, daily }: { clips: ClipAnalytics[]; daily: AnalyticsDay[] }) {
  const [rpm, setRpm] = useState(TIKTOK_RPM);
  const [scenario, setScenario] = useState<Scenario>("expected");
  const [now] = useState(() => Date.now());
  const gold = useCssVar("--mtv-gold", "#cbff3d");
  const divider = useCssVar("--mtv-divider", "rgba(255,255,255,0.12)");
  const text2 = useCssVar("--mtv-text-2", "rgba(255,255,255,0.6)");

  const actual = useMemo(() => {
    const points: { label: string; value: number }[] = [];
    let cum = 0;
    for (const day of daily) {
      cum += (day.views / 1000) * rpm;
      points.push({ label: day.day, value: cum });
    }
    return points;
  }, [daily, rpm]);

  const todayCumulative = actual.at(-1)?.value ?? 0;

  const projectedDaily = useMemo(() => {
    const totals = new Array(PROJECTION_DAYS).fill(0);
    for (const clip of clips) {
      const result = forecast({
        existingViews: clip.clip.view_count,
        viralityScore: clipViralityScore(clip),
        daysSincePublish: daysSince(clip.clip.published_at ?? clip.clip.created_at, now),
        rpm,
        scenario,
      });
      for (let day = 0; day < PROJECTION_DAYS; day++) totals[day] += result.days[day].earnings;
    }
    return totals;
  }, [clips, rpm, scenario, now]);

  const projected = useMemo(() => {
    const points: { label: string; value: number }[] = [];
    let cum = todayCumulative;
    for (let i = 0; i < projectedDaily.length; i++) {
      cum += projectedDaily[i];
      points.push({ label: `+${i + 1}d`, value: cum });
    }
    return points;
  }, [projectedDaily, todayCumulative]);

  const option: EChartsOption = useMemo(() => {
    const labels = [...actual.map((p) => p.label), ...projected.map((p) => p.label)];
    const actualSeries = [...actual.map((p) => p.value), ...projected.map(() => null)];
    const projectedSeries = [
      ...actual.slice(0, -1).map(() => null),
      actual.at(-1)?.value ?? null,
      ...projected.map((p) => p.value),
    ];
    return {
      grid: { left: 56, right: 16, top: 28, bottom: 28 },
      tooltip: {
        trigger: "axis",
        ...TOOLTIP_STYLE,
        formatter: (params) => {
          const rows = (Array.isArray(params) ? params : [params]) as unknown as {
            value: number | null;
            axisValue: string;
          }[];
          const first = rows.find((row) => row.value != null);
          if (!first || first.value == null) return "";
          const projectedPoint = String(first.axisValue).startsWith("+");
          return [
            `<div style="font-weight:600;margin-bottom:4px">${usd(first.value)}</div>`,
            `<span style="color:${text2}">${projectedPoint ? `projected ${first.axisValue}` : first.axisValue}</span>`,
          ].join("");
        },
      },
      xAxis: {
        type: "category",
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: divider } },
        axisTick: { show: false },
        axisLabel: {
          color: text2,
          fontSize: 12,
          interval: Math.max(0, Math.ceil(labels.length / 8) - 1),
          formatter: (value: string) => (value.startsWith("+") ? value : value.slice(5)),
        },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: divider, type: "dashed" } },
        axisLabel: { color: text2, fontSize: 12, formatter: (v: number) => usd(v) },
      },
      series: [
        {
          name: "Tracked",
          type: "line",
          data: actualSeries,
          smooth: 0.35,
          symbol: "none",
          connectNulls: false,
          lineStyle: {
            width: 2.5,
            color: gold,
            shadowBlur: 16,
            shadowColor: gold,
          },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: `${gold}55` },
                { offset: 1, color: `${gold}00` },
              ],
            },
          },
        },
        {
          name: "Projected",
          type: "line",
          data: projectedSeries,
          smooth: 0.35,
          symbol: "none",
          connectNulls: false,
          lineStyle: {
            width: 2.5,
            type: "dashed",
            color: gold,
            shadowBlur: 10,
            shadowColor: `${gold}88`,
          },
          markLine: {
            silent: true,
            symbol: "none",
            label: { color: text2, fontSize: 11, formatter: "Today" },
            lineStyle: { color: text2, type: "dashed", width: 1 },
            data: [{ xAxis: actual.length ? actual.length - 1 : 0 }],
          },
          markPoint: {
            symbol: "circle",
            symbolSize: 10,
            itemStyle: { color: gold, borderColor: "#0a0a0a", borderWidth: 2 },
            data: CHECKPOINTS.map((cp) => ({
              name: `${cp}d`,
              coord: [actual.length + cp - 1, projected[cp - 1]?.value ?? 0],
            })),
          },
        },
      ],
    };
  }, [actual, projected, gold, divider, text2]);

  return (
    <section className="flex h-full flex-col space-y-4 rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[var(--mtv-gold)]">
            <Sparkles className="h-5 w-5" />
            <h2 className="text-lg font-bold uppercase tracking-wider">Expected income</h2>
          </div>
          <p className="mt-1 text-sm text-[var(--mtv-text-2)]">
            Solid: estimated from real tracked views. Dashed: projected from each clip&apos;s own virality score.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <PillRow>
            {SCENARIOS.map((s) => (
              <Pill key={s.id} selected={scenario === s.id} onClick={() => setScenario(s.id)}>
                {s.label}
              </Pill>
            ))}
          </PillRow>
          <div className="flex items-center gap-1 text-sm">
            $
            <input
              type="number"
              min={0}
              step={0.01}
              value={rpm}
              onChange={(e) => setRpm(Math.max(0, Number(e.target.value) || 0))}
              className="w-16 rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface-high)] px-2 py-1.5 text-sm"
            />
            <span className="text-[var(--mtv-text-2)]">RPM</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {CHECKPOINTS.map((cp, index) => {
          const point = projected[cp - 1];
          const prior = index === 0 ? todayCumulative : (projected[CHECKPOINTS[index - 1] - 1]?.value ?? todayCumulative);
          const delta = point ? point.value - prior : 0;
          return (
            <div key={cp} className="flex flex-col gap-0.5 rounded-xl bg-[var(--mtv-surface-high)] p-3">
              <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--mtv-text-2)]">
                <span className="size-2 shrink-0 rounded-[3px] bg-[var(--mtv-gold)]" />
                In {cp} days
              </span>
              <span className="text-2xl font-semibold tracking-tight tabular-nums text-[var(--mtv-gold)]">
                {point ? usd(point.value) : "—"}
              </span>
              <span className="text-[11px] text-[var(--mtv-text-2)]">
                <span className={cn("font-medium", delta >= 0 ? "text-[var(--mtv-green)]" : "text-[var(--mtv-red)]")}>
                  {delta >= 0 ? "+" : ""}
                  {usd(delta)}
                </span>{" "}
                from prior checkpoint
              </span>
            </div>
          );
        })}
      </div>

      <EChartsBase option={option} height={280} className="min-h-[240px] w-full" />

      <p className="text-xs leading-relaxed text-[var(--mtv-text-2)]">
        Illustrative. Earnings default to an assumed TikTok RPM ($0.04 / 1k views), not Twitch or Medal rates.
        The solid portion applies that RPM to real tracked views; the dashed portion also predicts future views.
        Not a published payout table and not a guarantee of income.
      </p>
    </section>
  );
}
