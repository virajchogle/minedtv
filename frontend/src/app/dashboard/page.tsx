"use client";

/**
 * Creator dashboard: how your clips are doing over a period, and how each one scores with
 * the frame virality scorer. Every number is real: views are counted per day on the server, and
 * likes, comments and follows by when they happened. Days are UTC.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Loader2, Minus, Table2, Youtube } from "lucide-react";

import { PublishBadge } from "@/components/clip-actions";
import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import { SiteNav } from "@/components/hero/site-nav";
import { Pill, PillRow } from "@/components/ui/pill";
import { ScreenTitle } from "@/components/ui/screen-header";
import { ScoreMeter, VerdictBadge } from "@/components/virality-report";
import { fetchAnalytics } from "@/lib/api";
import type { AnalyticsDay, AnalyticsOut, AnalyticsTotals, ClipAnalytics } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

type Metric = keyof AnalyticsTotals;

const METRICS: { id: Metric; label: string }[] = [
  { id: "views", label: "Views" },
  { id: "likes", label: "Likes" },
  { id: "comments", label: "Comments" },
  { id: "new_followers", label: "New followers" },
];

const RANGES = [7, 30, 90] as const;

const compact = (n: number) => new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);

const dayLabel = (iso: string, withYear = false) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
    ...(withYear ? { year: "numeric" } : {}),
  });

export default function DashboardPage() {
  const me = useCurrentUser();
  const [days, setDays] = useState<number>(30);
  const [metric, setMetric] = useState<Metric>("views");
  const [data, setData] = useState<AnalyticsOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const meId = me?.id ?? null;

  // Fetch when the user or the range changes; results for a stale request are dropped.
  const load = useCallback(() => {
    if (!meId) return () => {};
    let cancelled = false;
    fetchAnalytics(days).then(
      (d) => !cancelled && (setData(d), setError(null)),
      (e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Could not load analytics")
    );
    return () => {
      cancelled = true;
    };
  }, [meId, days]);

  useEffect(() => load(), [load]);

  // Showing the previous range's numbers (dimmed) until the new ones arrive.
  const loading = Boolean(meId) && !error && data?.days !== days;

  // Keep polling while an upload is still being scored.
  const checking = data?.clips.some((c) => c.virality.status === "processing") ?? false;
  useEffect(() => {
    if (!checking) return;
    const timer = setInterval(() => void load(), 15_000);
    return () => clearInterval(timer);
  }, [checking, load]);

  return (
    <div className="min-h-screen bg-[var(--mtv-bg)] px-4 pb-16 pt-28 text-[var(--mtv-text)] sm:px-8 sm:pt-32">
      <SiteNav />
      <div className="mx-auto max-w-5xl space-y-8">
        <ScreenTitle eyebrow="Dashboard" accent="doing.">
          How you&apos;re
        </ScreenTitle>

        {!me ? (
          <ChooseUserNotice action="see your dashboard" />
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <PillRow>
                {RANGES.map((d) => (
                  <Pill key={d} selected={days === d} onClick={() => setDays(d)}>
                    Last {d} days
                  </Pill>
                ))}
              </PillRow>
              {loading && <Loader2 className="h-4 w-4 animate-spin text-[var(--mtv-text-2)]" aria-label="Loading" />}
            </div>

            {error && (
              <p className="flex items-start gap-2 rounded-lg border border-[var(--mtv-red)]/40 bg-[var(--mtv-red)]/10 p-3 text-sm text-[var(--mtv-red)]">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                {error}
              </p>
            )}

            {data && (
              // Refetches keep the last render, dimmed, instead of flashing a skeleton.
              <div className={cn("space-y-8 transition-opacity", loading && "opacity-60")}>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  {METRICS.map((m) => (
                    <StatTile
                      key={m.id}
                      label={m.label}
                      value={data.period[m.id]}
                      previous={data.previous_period[m.id]}
                      days={data.days}
                      selected={metric === m.id}
                      onClick={() => setMetric(m.id)}
                    />
                  ))}
                </div>

                <ChartCard data={data} metric={metric} />

                <ClipsTable clips={data.clips} days={data.days} />

                <p className="text-xs text-[var(--mtv-text-2)]">
                  All time: {data.lifetime.views.toLocaleString()} views · {data.lifetime.likes.toLocaleString()} likes ·{" "}
                  {data.lifetime.comments.toLocaleString()} comments · {data.follower_count.toLocaleString()} followers.{" "}
                  {data.tracking_since
                    ? `Daily views are tracked since ${dayLabel(data.tracking_since, true)}; earlier views only count in all-time totals.`
                    : "Daily views start counting from the next view; earlier views only count in all-time totals."}
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function StatTile({
  label,
  value,
  previous,
  days,
  selected,
  onClick,
}: {
  label: string;
  value: number;
  previous: number;
  days: number;
  selected: boolean;
  onClick: () => void;
}) {
  const change = value - previous;
  const Icon = change > 0 ? ArrowUpRight : change < 0 ? ArrowDownRight : Minus;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={cn(
        "space-y-1 rounded-2xl border bg-[var(--mtv-surface)] p-4 text-left transition-colors",
        selected ? "border-[var(--mtv-gold)]/60" : "border-[var(--mtv-divider)] hover:border-[var(--mtv-text-2)]/50"
      )}
    >
      <p className="text-xs text-[var(--mtv-text-2)]">{label}</p>
      <p className="text-2xl font-semibold">{value.toLocaleString()}</p>
      <p
        className={cn(
          "inline-flex items-center gap-1 text-[11px]",
          change > 0 ? "text-[var(--mtv-green)]" : change < 0 ? "text-[var(--mtv-red)]" : "text-[var(--mtv-text-2)]"
        )}
      >
        <Icon className="h-3 w-3" aria-hidden />
        {change === 0 ? "No change" : `${change > 0 ? "+" : ""}${change.toLocaleString()}`}
        <span className="text-[var(--mtv-text-2)]">vs previous {days} days</span>
      </p>
    </button>
  );
}

function ChartCard({ data, metric }: { data: AnalyticsOut; metric: Metric }) {
  const [asTable, setAsTable] = useState(false);
  const label = METRICS.find((m) => m.id === metric)?.label ?? metric;
  return (
    <section className="space-y-3 rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{label} per day</h2>
          <p className="text-xs text-[var(--mtv-text-2)]">
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
      {asTable ? <DayTable daily={data.daily} /> : <AreaChart daily={data.daily} metric={metric} label={label} />}
    </section>
  );
}

const CHART_H = 220;
const PAD = { top: 12, right: 12, bottom: 24, left: 40 };

/** Nice round tick values from 0 to at least `max`. */
function ticks(max: number): number[] {
  if (max <= 0) return [0, 1];
  const rough = max / 3;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * pow).find((s) => s >= rough) ?? pow * 10;
  const out: number[] = [];
  for (let v = 0; v <= max + step * 0.001; v += step) out.push(v);
  if (out[out.length - 1] < max) out.push(out[out.length - 1] + step);
  return out;
}

function AreaChart({ daily, metric, label }: { daily: AnalyticsDay[]; metric: Metric; label: string }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const values = daily.map((d) => d[metric]);
  const yTicks = useMemo(() => ticks(Math.max(...values, 0)), [values]);
  const yMax = yTicks[yTicks.length - 1];
  const innerW = width - PAD.left - PAD.right;
  const innerH = CHART_H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (daily.length <= 1 ? innerW / 2 : (i / (daily.length - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - (v / yMax) * innerH;

  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join("");
  const area = `${line}L${x(values.length - 1)},${y(0)}L${x(0)},${y(0)}Z`;
  const xTickEvery = Math.max(1, Math.ceil(daily.length / 6));

  const onMove = (event: React.PointerEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const rel = (event.clientX - rect.left) / rect.width;
    setHover(Math.round(rel * (daily.length - 1)));
  };

  const h = hover != null ? daily[hover] : null;

  return (
    <div ref={boxRef} className="relative">
      <svg width={width} height={CHART_H} className="block" role="img" aria-label={`${label} per day`}>
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--mtv-divider)" strokeWidth={1} />
            <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--mtv-text-2)" className="tabular-nums">
              {compact(t)}
            </text>
          </g>
        ))}
        {daily.map((d, i) =>
          i % xTickEvery === 0 || i === daily.length - 1 ? (
            <text key={d.day} x={x(i)} y={CHART_H - 6} textAnchor="middle" fontSize={11} fill="var(--mtv-text-2)">
              {dayLabel(d.day)}
            </text>
          ) : null
        )}
        <path d={area} fill="var(--mtv-gold)" fillOpacity={0.1} />
        <path d={line} fill="none" stroke="var(--mtv-gold)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {hover != null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} stroke="var(--mtv-text-2)" strokeWidth={1} />
            <circle cx={x(hover)} cy={y(values[hover])} r={4} fill="var(--mtv-gold)" stroke="var(--mtv-surface)" strokeWidth={2} />
          </g>
        )}
        <rect
          x={PAD.left}
          y={PAD.top}
          width={innerW}
          height={innerH}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        />
      </svg>
      {h && hover != null && (
        <div
          className="pointer-events-none absolute top-2 z-10 rounded-lg border border-[var(--mtv-divider)] bg-black/90 px-2.5 py-1.5 text-xs shadow-xl"
          style={{ left: Math.min(Math.max(x(hover) - 60, 0), width - 130) }}
        >
          <p className="text-sm font-semibold">{h[metric].toLocaleString()}</p>
          <p className="text-[var(--mtv-text-2)]">
            {label.toLowerCase()} · {dayLabel(h.day, true)}
          </p>
        </div>
      )}
    </div>
  );
}

function DayTable({ daily }: { daily: AnalyticsDay[] }) {
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-left text-[13px] tabular-nums">
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

type Sort = "newest" | "views" | "score";

const scoreOf = (c: ClipAnalytics) => c.virality.score ?? -1;

function ClipsTable({ clips, days }: { clips: ClipAnalytics[]; days: number }) {
  const [sort, setSort] = useState<Sort>("newest");
  const rows = useMemo(() => {
    const list = [...clips];
    if (sort === "views") list.sort((a, b) => b.period_views - a.period_views);
    if (sort === "score") list.sort((a, b) => scoreOf(b) - scoreOf(a));
    return list;
  }, [clips, sort]);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">Your clips</h2>
        <label className="flex items-center gap-2 text-xs text-[var(--mtv-text-2)]">
          Sort by
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as Sort)}
            className="rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface-high)] px-2 py-1 text-[13px] text-[var(--mtv-text)]"
          >
            <option value="newest">Newest</option>
            <option value="views">Views ({days} days)</option>
            <option value="score">Virality score</option>
          </select>
        </label>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-xl border border-dashed border-[var(--mtv-divider)] p-6 text-center text-sm text-[var(--mtv-text-2)]">
          No clips yet. <Link href="/upload" className="text-[var(--mtv-gold)] underline underline-offset-2">Upload one</Link>.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-[var(--mtv-divider)]">
          <table className="w-full min-w-[640px] table-fixed text-left text-[13px]">
            <thead className="bg-[var(--mtv-surface)] text-xs text-[var(--mtv-text-2)]">
              <tr>
                <th className="px-4 py-2 font-normal">Clip</th>
                <th className="w-20 px-3 py-2 text-right font-normal">Views</th>
                <th className="w-20 px-3 py-2 text-right font-normal">Likes</th>
                <th className="w-24 px-3 py-2 text-right font-normal">Comments</th>
                <th className="w-56 px-4 py-2 font-normal">Virality</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <ClipRow key={row.clip.id} row={row} />
              ))}
            </tbody>
          </table>
          <p className="border-t border-[var(--mtv-divider)] bg-[var(--mtv-surface)] px-4 py-2 text-[11px] text-[var(--mtv-text-2)]">
            Views, likes and comments are for the last {days} days. Virality scores every moment of an upload
            when it&apos;s processed; a clip&apos;s score is its strongest moments, compared with the rest of its upload.
          </p>
        </div>
      )}
    </section>
  );
}

function ClipRow({ row }: { row: ClipAnalytics }) {
  const { clip, virality } = row;
  return (
    <tr className="border-t border-[var(--mtv-divider)] align-middle">
      <td className="px-4 py-2.5">
        <Link href={`/video/${clip.id}`} className="flex min-w-0 items-center gap-3 hover:opacity-90">
          {clip.thumbnail_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={clip.thumbnail_url} alt="" className="h-10 w-16 shrink-0 rounded-md object-cover" />
          ) : (
            <span className="h-10 w-16 shrink-0 rounded-md bg-[var(--mtv-surface-high)]" />
          )}
          <span className="min-w-0">
            <span className="block truncate font-semibold">{clip.title ?? clip.game ?? "Untitled clip"}</span>
            <span className="mt-0.5 flex items-center gap-2">
              <PublishBadge state={clip.publish_state ?? "published"} />
              {clip.youtube_url && (
                <span className="inline-flex items-center gap-1 text-[11px] text-[var(--mtv-text-2)]">
                  <Youtube className="h-3 w-3" aria-hidden /> On YouTube
                </span>
              )}
            </span>
          </span>
        </Link>
      </td>
      <td className="px-3 py-2.5 text-right tabular-nums">{row.period_views.toLocaleString()}</td>
      <td className="px-3 py-2.5 text-right tabular-nums">{row.period_likes.toLocaleString()}</td>
      <td className="px-3 py-2.5 text-right tabular-nums">{row.period_comments.toLocaleString()}</td>
      <td className="px-4 py-2.5">
        {virality.score != null && virality.verdict ? (
          <div className="space-y-1">
            <VerdictBadge verdict={virality.verdict} score={virality.score} />
            <ScoreMeter score={virality.score} compact />
          </div>
        ) : virality.status === "processing" ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-[var(--mtv-text-2)]">
            <Loader2 className="h-3 w-3 animate-spin" /> Checking…
          </span>
        ) : virality.status === "failed" ? (
          <span className="text-xs text-[var(--mtv-red)]">Check failed</span>
        ) : (
          <span className="text-xs text-[var(--mtv-text-2)]">Not scored yet</span>
        )}
      </td>
    </tr>
  );
}
