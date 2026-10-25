"use client";

/**
 * Creator dashboard: four tiles on one screen. Click a tile to open the
 * full module. Every number is real: views are counted per day on the server,
 * and likes, comments and follows by when they happened. Days are UTC.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, Loader2, Youtube } from "lucide-react";

import { AudienceFlowSankey } from "@/components/audience-flow-sankey";
import { PublishBadge } from "@/components/clip-actions";
import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import { DailyEngagementChart } from "@/components/daily-engagement-chart";
import { HoverBeam } from "@/components/dashboard-tile";
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
type Panel = "income" | "engagement" | "forecast" | "audience";

const RANGES = [7, 30, 90] as const;

const dayLabel = (iso: string, withYear = false) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
    ...(withYear ? { year: "numeric" } : {}),
  });

const PANEL_LABEL: Record<Panel, string> = {
  income: "Expected income",
  engagement: "Daily",
  forecast: "Forecast",
  audience: "Audience",
};

export default function DashboardPage() {
  const me = useCurrentUser();
  const [days, setDays] = useState<number>(30);
  const [metric, setMetric] = useState<Metric>("views");
  const [data, setData] = useState<AnalyticsOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Panel | null>(null);
  const meId = me?.id ?? null;

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

  const loading = Boolean(meId) && !error && data?.days !== days;

  const checking = data?.clips.some((c) => c.virality?.status === "processing") ?? false;
  useEffect(() => {
    if (!checking) return;
    const timer = setInterval(() => void load(), 15_000);
    return () => clearInterval(timer);
  }, [checking, load]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="flex h-[100dvh] flex-col overflow-hidden bg-[var(--mtv-bg)] px-3 pb-3 pt-20 text-[var(--mtv-text)] sm:px-5 [--neon-accent:203_255_61]">
      <SiteNav />
      <div className="mx-auto flex min-h-0 w-full max-w-7xl flex-1 flex-col gap-3">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-3">
          {open ? (
            <button
              type="button"
              onClick={() => setOpen(null)}
              className="inline-flex items-center gap-2 text-lg font-bold tracking-tight hover:text-[var(--mtv-gold)]"
            >
              <ArrowLeft className="h-5 w-5" />
              {PANEL_LABEL[open]}
            </button>
          ) : (
            <ScreenTitle className="[&>h1]:text-2xl [&>h1]:sm:text-3xl">Dashboard</ScreenTitle>
          )}
          <div className="flex items-center gap-3">
            <PillRow>
              {RANGES.map((d) => (
                <Pill key={d} selected={days === d} onClick={() => setDays(d)}>
                  Last {d} days
                </Pill>
              ))}
            </PillRow>
            {loading && <Loader2 className="h-4 w-4 animate-spin text-[var(--mtv-text-2)]" aria-label="Loading" />}
          </div>
        </header>

        {!me ? (
          <ChooseUserNotice action="see your dashboard" />
        ) : (
          <>
            {error && (
              <p className="flex items-start gap-2 rounded-lg border border-[var(--mtv-red)]/40 bg-[var(--mtv-red)]/10 p-3 text-sm text-[var(--mtv-red)]">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                {error}
              </p>
            )}

            {data && (
              <div className={cn("flex min-h-0 flex-1 flex-col", loading && "opacity-60")}>
                {open === null ? (
                  <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-auto md:grid-cols-2 md:grid-rows-2 md:overflow-hidden">
                    <HoverBeam as="button" onClick={() => setOpen("income")}>
                      <IncomeForecastChart clips={data.clips} daily={data.daily} compact />
                    </HoverBeam>
                    <HoverBeam as="button" onClick={() => setOpen("engagement")}>
                      <DailyEngagementChart data={data} highlight={metric} compact />
                    </HoverBeam>
                    <HoverBeam as="button" onClick={() => setOpen("forecast")}>
                      <ForecastModule clips={data.clips} compact />
                    </HoverBeam>
                    <HoverBeam as="button" onClick={() => setOpen("audience")}>
                      <AudienceFlowSankey clips={data.clips} compact />
                    </HoverBeam>
                  </div>
                ) : (
                  <div className="min-h-0 flex-1 overflow-auto">
                    {open === "income" && <IncomeForecastChart clips={data.clips} daily={data.daily} />}
                    {open === "engagement" && (
                      <DailyEngagementChart data={data} highlight={metric} onHighlight={setMetric} />
                    )}
                    {open === "forecast" && (
                      <div className="space-y-6">
                        <ForecastModule clips={data.clips} />
                        <ClipsTable clips={data.clips} days={data.days} />
                      </div>
                    )}
                    {open === "audience" && <AudienceFlowSankey clips={data.clips} />}
                    <p className="mt-4 text-xs text-[var(--mtv-text-2)]">
                      All time: {data.lifetime.views.toLocaleString()} views · {data.lifetime.likes.toLocaleString()} likes ·{" "}
                      {data.lifetime.comments.toLocaleString()} comments · {data.follower_count.toLocaleString()} followers.{" "}
                      {data.tracking_since
                        ? `Daily views are tracked since ${dayLabel(data.tracking_since, true)}; earlier views only count in all-time totals.`
                        : "Daily views start counting from the next view; earlier views only count in all-time totals."}
                    </p>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
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
