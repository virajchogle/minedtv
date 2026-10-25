"use client";

/**
 * Creator dashboard: how your clips are doing over a period, and how each one scores with
 * the virality panel. Every number is real: views are counted per day on the server, and
 * likes, comments and follows by when they happened. Days are UTC.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { motion, useSpring, useTransform } from "framer-motion";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Loader2, Minus, Youtube } from "lucide-react";

import { AudienceFlowSankey } from "@/components/audience-flow-sankey";
import { PublishBadge } from "@/components/clip-actions";
import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import { DailyEngagementChart } from "@/components/daily-engagement-chart";
import { ForecastModule } from "@/components/forecast-module";
import { SiteNav } from "@/components/hero/site-nav";
import { IncomeForecastChart } from "@/components/income-forecast-chart";
import { Pill, PillRow } from "@/components/ui/pill";
import { ScreenTitle } from "@/components/ui/screen-header";
import { ScoreRange, VerdictBadge } from "@/components/virality-report";
import { clipViralityScore, fetchAnalytics, median, verdictFor } from "@/lib/api";
import type { AnalyticsOut, AnalyticsTotals, ClipAnalytics } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

type Metric = keyof AnalyticsTotals;

const METRICS: { id: Metric; label: string }[] = [
  { id: "views", label: "Views" },
  { id: "likes", label: "Likes" },
  { id: "comments", label: "Comments" },
  { id: "new_followers", label: "New followers" },
];

const RANGES = [7, 30, 90] as const;

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

  // Keep polling while a virality check is still running somewhere.
  const checking = data?.clips.some((c) => c.virality?.status === "processing") ?? false;
  useEffect(() => {
    if (!checking) return;
    const timer = setInterval(() => void load(), 15_000);
    return () => clearInterval(timer);
  }, [checking, load]);

  return (
    <div className="min-h-screen bg-[var(--mtv-bg)] px-4 pb-16 pt-28 text-[var(--mtv-text)] sm:px-8 sm:pt-32">
      <SiteNav />
      <div className="mx-auto max-w-7xl space-y-8">
        <ScreenTitle>Dashboard</ScreenTitle>

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

                <div className="grid gap-6 xl:grid-cols-2">
                  <IncomeForecastChart clips={data.clips} daily={data.daily} />
                  <DailyEngagementChart data={data} highlight={metric} />
                </div>

                <ForecastModule clips={data.clips} />

                <AudienceFlowSankey clips={data.clips} />

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

function AnimatedNumber({ value }: { value: number }) {
  const spring = useSpring(0, { stiffness: 90, damping: 20 });
  const display = useTransform(spring, (v) => Math.round(v).toLocaleString());
  useEffect(() => void spring.set(value), [value, spring]);
  return <motion.span>{display}</motion.span>;
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
    <motion.button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      whileHover={{ y: -3 }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      className={cn(
        "space-y-1 rounded-2xl border bg-[var(--mtv-surface)] p-4 text-left transition-[border-color,box-shadow]",
        selected
          ? "border-[var(--mtv-gold)]/60 shadow-[0_0_24px_-6px_var(--mtv-gold)]"
          : "border-[var(--mtv-divider)] hover:border-[var(--mtv-gold)]/40 hover:shadow-[0_0_20px_-8px_var(--mtv-gold)]"
      )}
    >
      <p className="text-sm text-[var(--mtv-text-2)]">{label}</p>
      <p className="text-3xl font-semibold tabular-nums">
        <AnimatedNumber value={value} />
      </p>
      <p
        className={cn(
          "inline-flex items-center gap-1 text-[12px]",
          change > 0 ? "text-[var(--mtv-green)]" : change < 0 ? "text-[var(--mtv-red)]" : "text-[var(--mtv-text-2)]"
        )}
      >
        <Icon className="h-3 w-3" aria-hidden />
        {change === 0 ? "No change" : `${change > 0 ? "+" : ""}${change.toLocaleString()}`}
        <span className="text-[var(--mtv-text-2)]">vs previous {days} days</span>
      </p>
    </motion.button>
  );
}

type Sort = "newest" | "views" | "score";

const scoreOf = (c: ClipAnalytics) => clipViralityScore(c) ?? -1;

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
        <h2 className="text-lg font-bold">Your clips</h2>
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
          <table className="w-full min-w-[640px] text-left text-[13px]">
            <thead className="bg-[var(--mtv-surface)] text-xs text-[var(--mtv-text-2)]">
              <tr>
                <th className="px-4 py-2 font-normal">Clip</th>
                <th className="px-3 py-2 text-right font-normal">Views</th>
                <th className="px-3 py-2 text-right font-normal">Likes</th>
                <th className="px-3 py-2 text-right font-normal">Comments</th>
                <th className="w-56 px-4 py-2 font-normal">YouTube virality</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <ClipRow key={row.clip.id} row={row} />
              ))}
            </tbody>
          </table>
          <p className="border-t border-[var(--mtv-divider)] bg-[var(--mtv-surface)] px-4 py-2 text-[11px] text-[var(--mtv-text-2)]">
            Views, likes and comments are for the last {days} days. Virality runs when you publish a clip; the dot is the
            median of the audience panels and the band their range.
          </p>
        </div>
      )}
    </section>
  );
}

function ClipRow({ row }: { row: ClipAnalytics }) {
  const { clip, virality } = row;
  const scores = virality?.score_samples?.length
    ? virality.score_samples
    : virality?.score != null
      ? [virality.score]
      : [];
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
        {scores.length > 0 ? (
          <div className="space-y-1">
            <VerdictBadge verdict={verdictFor(median(scores))} score={median(scores)} />
            <ScoreRange scores={scores} compact />
          </div>
        ) : virality.status === "processing" ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-[var(--mtv-text-2)]">
            <Loader2 className="h-3 w-3 animate-spin" /> Checking…
          </span>
        ) : virality.status === "failed" ? (
          <span className="text-xs text-[var(--mtv-red)]">Check failed</span>
        ) : (
          <span className="text-xs text-[var(--mtv-text-2)]">{clip.publish_state === "published" ? "Not checked" : "Runs on publish"}</span>
        )}
      </td>
    </tr>
  );
}
