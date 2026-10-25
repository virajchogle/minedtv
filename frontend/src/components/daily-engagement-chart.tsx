"use client";

/**
 * Daily engagement — views, likes and comments on one GlowChart.
 * Built from the same AnalyticsDay rows the rest of the dashboard uses.
 */

import { useMemo, useState } from "react";
import { Table2 } from "lucide-react";

import { HoverBeam } from "@/components/dashboard-tile";
import { GlowChart, Sparkline } from "@/components/ui/glow-chart";
import { NeonFrame } from "@/components/ui/neon-frame";
import type { AnalyticsDay, AnalyticsOut, AnalyticsTotals } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

type Metric = keyof AnalyticsTotals;

const METRICS: { id: Metric; label: string; color: string }[] = [
  { id: "views", label: "Views", color: "#eab308" },
  { id: "likes", label: "Likes", color: "#22d3ee" },
  { id: "comments", label: "Comments", color: "#f472b6" },
];

const dayLabel = (iso: string, withYear = false) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
    ...(withYear ? { year: "numeric" } : {}),
  });

export function DailyEngagementChart({
  data,
  highlight,
  onHighlight,
  compact = false,
}: {
  data: AnalyticsOut;
  highlight: Metric;
  onHighlight?: (metric: Metric) => void;
  compact?: boolean;
}) {
  const [asTable, setAsTable] = useState(false);

  const series = useMemo(
    () =>
      METRICS.map((metric) => ({
        name: metric.label,
        color: metric.color,
        muted: metric.id !== highlight && highlight !== "new_followers",
        data: data.daily.map((d) => ({
          x: new Date(`${d.day}T00:00:00Z`),
          y: d[metric.id],
        })),
      })),
    [data.daily, highlight]
  );

  const total = data.period[highlight === "new_followers" ? "views" : highlight];
  const previous = data.previous_period[highlight === "new_followers" ? "views" : highlight];
  const change = total - previous;
  const changePct = previous > 0 ? (change / previous) * 100 : null;
  const highlightMeta = METRICS.find((m) => m.id === highlight) ?? METRICS[0];

  const chart = asTable ? (
    <DayTable daily={data.daily} />
  ) : (
    <GlowChart
      type="line"
      color="#eab308"
      data={series}
      label={`${highlightMeta.label} per day`}
      height={compact ? 132 : 232}
      axis={!compact}
      grid={!compact}
      tooltip={!compact}
      legend={!compact}
      animate
    />
  );

  const tiles = (
    <dl className={cn("grid gap-2", compact ? "grid-cols-3" : "grid-cols-2 sm:grid-cols-4")}>
      {(compact ? METRICS : [...METRICS, { id: "new_followers" as Metric, label: "Followers", color: "#a78bfa" }]).map(
        (tile) => {
          const value = data.period[tile.id];
          const prior = data.previous_period[tile.id];
          const delta = prior > 0 ? ((value - prior) / prior) * 100 : null;
          const trend = data.daily.slice(-10).map((d) => d[tile.id]);
          const selected = highlight === tile.id;
          return (
            <HoverBeam
              key={tile.id}
              as={onHighlight ? "button" : "div"}
              onClick={onHighlight ? () => onHighlight(tile.id) : undefined}
              className={cn("rounded-xl p-2.5", selected ? "border-[var(--mtv-gold)]/50" : "border-white/10")}
            >
              <dt className="flex items-center justify-between gap-2 text-[11px] text-white/50">
                {tile.label}
                {delta != null && (
                  <span className={cn("tabular-nums", delta >= 0 ? "text-[var(--mtv-green)]" : "text-[var(--mtv-red)]")}>
                    {delta >= 0 ? "+" : ""}
                    {delta.toFixed(1)}%
                  </span>
                )}
              </dt>
              <dd className="mt-1 flex items-end justify-between gap-2">
                <span className="text-lg font-semibold tabular-nums text-white/90">{value.toLocaleString()}</span>
                {trend.some((n) => n > 0) && (
                  <Sparkline data={trend} width={64} height={22} color={tile.color} label={`${tile.label}, recent days`} />
                )}
              </dd>
            </HoverBeam>
          );
        }
      )}
    </dl>
  );

  if (compact) {
    return (
      <NeonFrame
        as="section"
        label="Daily"
        tabs={{ topRight: `${data.days}d` }}
        color="#eab308"
        className="flex h-full min-h-0 flex-col rounded-2xl border-white/10 p-4"
      >
        <div className="flex items-baseline gap-2">
          <p className="text-3xl font-semibold tracking-tight text-white">{data.period.views.toLocaleString()}</p>
          {changePct != null && (
            <span className={cn("text-sm font-medium", change >= 0 ? "text-[var(--mtv-green)]" : "text-[var(--mtv-red)]")}>
              {change >= 0 ? "+" : ""}
              {changePct.toFixed(1)}%
            </span>
          )}
        </div>
        <p className="text-xs text-white/50">Views this period</p>
        <div className="mt-2 min-h-0 flex-1">{chart}</div>
        <div className="mt-2">{tiles}</div>
      </NeonFrame>
    );
  }

  return (
    <NeonFrame
      as="section"
      label={`${highlightMeta.label} per day`}
      tabs={{ topRight: `${dayLabel(data.start)} – ${dayLabel(data.end)}` }}
      color="#eab308"
      className="flex h-full flex-col p-4 sm:p-6"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-semibold tracking-tight tabular-nums">{total.toLocaleString()}</span>
          {changePct != null && (
            <span className={cn("text-sm font-medium", change >= 0 ? "text-[var(--mtv-green)]" : "text-[var(--mtv-red)]")}>
              {change >= 0 ? "+" : ""}
              {changePct.toFixed(1)}%
            </span>
          )}
          <span className="text-xs text-white/50">vs previous {data.days} days</span>
        </div>
        <button
          type="button"
          onClick={() => setAsTable((v) => !v)}
          aria-pressed={asTable}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1 text-xs hover:bg-white/5"
        >
          <Table2 className="h-3.5 w-3.5" />
          {asTable ? "Show chart" : "Show table"}
        </button>
      </div>

      <div className="mt-3">{tiles}</div>
      <div className="mt-3 min-h-0 flex-1">{chart}</div>
    </NeonFrame>
  );
}

function DayTable({ daily }: { daily: AnalyticsDay[] }) {
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-left text-sm tabular-nums">
        <thead className="sticky top-0 bg-[#0a0b11] text-xs text-white/50">
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
            <tr key={d.day} className="border-t border-white/10">
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
