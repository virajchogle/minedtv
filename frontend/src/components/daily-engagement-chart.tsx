"use client";

/**
 * Daily engagement — shipments-style dual/triple series: views, likes and
 * comments on one axis. Built from the same AnalyticsDay rows the rest of
 * the dashboard uses. Nothing here is invented.
 */

import { useMemo, useState } from "react";
import { Table2 } from "lucide-react";

import { EChartsBase, TOOLTIP_STYLE, type EChartsOption } from "@/components/ui/echarts-base";
import type { AnalyticsDay, AnalyticsOut, AnalyticsTotals } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

type Metric = keyof AnalyticsTotals;

const METRICS: { id: Metric; label: string; color: string }[] = [
  { id: "views", label: "Views", color: "#cbff3d" },
  { id: "likes", label: "Likes", color: "#22d3ee" },
  { id: "comments", label: "Comments", color: "#f472b6" },
];

const compact = (n: number) =>
  new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);

const dayLabel = (iso: string, withYear = false) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
    ...(withYear ? { year: "numeric" } : {}),
  });

function useCssVar(name: string, fallback: string): string {
  const [value] = useState(() => {
    if (typeof document === "undefined") return fallback;
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  });
  return value;
}

export function DailyEngagementChart({
  data,
  highlight,
}: {
  data: AnalyticsOut;
  highlight: Metric;
}) {
  const [asTable, setAsTable] = useState(false);
  const divider = useCssVar("--mtv-divider", "rgba(255,255,255,0.12)");
  const text2 = useCssVar("--mtv-text-2", "rgba(255,255,255,0.6)");

  const option: EChartsOption = useMemo(
    () => ({
      grid: { left: 48, right: 12, top: 16, bottom: 28 },
      legend: { show: false },
      tooltip: {
        trigger: "axis",
        ...TOOLTIP_STYLE,
      },
      xAxis: {
        type: "category",
        data: data.daily.map((d) => d.day),
        boundaryGap: false,
        axisLine: { lineStyle: { color: divider } },
        axisTick: { show: false },
        axisLabel: {
          color: text2,
          fontSize: 12,
          interval: Math.max(0, Math.ceil(data.daily.length / 7) - 1),
          formatter: (value: string) => dayLabel(value),
        },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: divider, type: "dashed" } },
        axisLabel: { color: text2, fontSize: 12, formatter: (v: number) => compact(v) },
      },
      series: METRICS.map((metric) => ({
        name: metric.label,
        type: "line" as const,
        data: data.daily.map((d) => d[metric.id]),
        smooth: false,
        symbol: metric.id === highlight ? "circle" : "none",
        symbolSize: 6,
        showSymbol: false,
        lineStyle: {
          width: metric.id === highlight ? 2.5 : 1.5,
          type: metric.id === "views" ? ("solid" as const) : ("dashed" as const),
          color: metric.color,
          shadowBlur: metric.id === highlight ? 14 : 0,
          shadowColor: metric.color,
        },
      })),
    }),
    [data.daily, divider, text2, highlight]
  );

  const total = data.period[highlight];
  const previous = data.previous_period[highlight];
  const change = total - previous;
  const changePct = previous > 0 ? (change / previous) * 100 : null;
  const highlightMeta = METRICS.find((m) => m.id === highlight) ?? METRICS[0];

  return (
    <section className="flex h-full flex-col rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-4 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold uppercase tracking-wider text-[var(--mtv-gold)]">
            {highlightMeta.label} per day
          </h2>
          <p className="mt-1 text-sm text-[var(--mtv-text-2)]">
            All your clips · {dayLabel(data.start)} – {dayLabel(data.end, true)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAsTable((v) => !v)}
          aria-pressed={asTable}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--mtv-divider)] px-2.5 py-1 text-xs hover:bg-[var(--mtv-surface-high)]"
        >
          <Table2 className="h-3.5 w-3.5" />
          {asTable ? "Show chart" : "Show table"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tracking-tight tabular-nums">{total.toLocaleString()}</span>
          {changePct != null && (
            <span className={cn("text-sm font-medium", change >= 0 ? "text-[var(--mtv-green)]" : "text-[var(--mtv-red)]")}>
              {change >= 0 ? "+" : ""}
              {changePct.toFixed(1)}%
            </span>
          )}
          <span className="text-xs text-[var(--mtv-text-2)]">vs previous {data.days} days</span>
        </div>
        <div className="flex items-center gap-4">
          {METRICS.map((metric) => (
            <span key={metric.id} className="flex items-center gap-1.5 text-xs text-[var(--mtv-text-2)]">
              <span
                className="size-2.5 shrink-0 rounded-full border-2"
                style={{ borderColor: metric.color, background: metric.id === "views" ? metric.color : "transparent" }}
              />
              {metric.label}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-3 min-h-0 flex-1">
        {asTable ? <DayTable daily={data.daily} /> : <EChartsBase option={option} height={260} />}
      </div>
    </section>
  );
}

function DayTable({ daily }: { daily: AnalyticsDay[] }) {
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-left text-sm tabular-nums">
        <thead className="sticky top-0 bg-[var(--mtv-surface)] text-xs text-[var(--mtv-text-2)]">
          <tr>
            <th className="py-1.5 font-normal">Day</th>
            {METRICS.map((m) => (
              <th key={m.id} className="py-1.5 text-right font-normal">
                {m.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...daily].reverse().map((d) => (
            <tr key={d.day} className="border-t border-[var(--mtv-divider)]">
              <td className="py-1.5">{dayLabel(d.day, true)}</td>
              {METRICS.map((m) => (
                <td key={m.id} className="py-1.5 text-right">
                  {d[m.id].toLocaleString()}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
