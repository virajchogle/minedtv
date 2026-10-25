"use client";

/**
 * Expected Income — one continuous series: solid where it's built from real
 * tracked views, dashed-looking muted series where it's projected from each
 * clip's virality score. The two halves share one cumulative total so the
 * projected line picks up exactly where the tracked one stops.
 */

import { useMemo, useState } from "react";

import { HoverBeam } from "@/components/dashboard-tile";
import { GlowChart } from "@/components/ui/glow-chart";
import { NeonFrame } from "@/components/ui/neon-frame";
import { Pill, PillRow } from "@/components/ui/pill";
import { clipViralityScore } from "@/lib/api";
import { SCENARIOS, TIKTOK_RPM, forecast, type Scenario } from "@/lib/forecast";
import type { AnalyticsDay, ClipAnalytics } from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

const PROJECTION_DAYS = 60;
const CHECKPOINTS = [15, 30, 60] as const;

function daysSince(iso: string, now: number): number {
  return Math.max(0, Math.floor((now - new Date(iso).getTime()) / 86_400_000));
}

function utcDay(iso: string, plusDays = 0): Date {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + plusDays);
  return d;
}

const usd = (n: number) =>
  `$${n.toLocaleString(undefined, { maximumFractionDigits: n < 10 ? 2 : 0 })}`;

export function IncomeForecastChart({
  clips,
  daily,
  compact = false,
}: {
  clips: ClipAnalytics[];
  daily: AnalyticsDay[];
  compact?: boolean;
}) {
  const [rpm, setRpm] = useState(TIKTOK_RPM);
  const [scenario, setScenario] = useState<Scenario>("expected");
  const [now] = useState(() => Date.now());

  const actual = useMemo(() => {
    const points: { x: Date; y: number }[] = [];
    let cum = 0;
    for (const day of daily) {
      cum += (day.views / 1000) * rpm;
      points.push({ x: utcDay(day.day), y: cum });
    }
    return points;
  }, [daily, rpm]);

  const todayCumulative = actual.at(-1)?.y ?? 0;
  const origin = useMemo(() => {
    if (actual.at(-1)?.x) return actual.at(-1)!.x;
    const n = new Date(now);
    return new Date(Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate()));
  }, [actual, now]);

  const projected = useMemo(() => {
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
    const points: { x: Date; y: number }[] = [];
    let cum = todayCumulative;
    for (let i = 0; i < totals.length; i++) {
      cum += totals[i];
      const x = new Date(origin);
      x.setUTCDate(origin.getUTCDate() + i + 1);
      points.push({ x, y: cum });
    }
    return points;
  }, [clips, rpm, scenario, now, todayCumulative, origin]);

  const series = useMemo(() => {
    const lastActual = actual.at(-1);
    return [
      {
        name: "Tracked",
        data: [
          ...actual,
          ...projected.map((p) => ({ x: p.x, y: null as number | null })),
        ],
      },
      {
        name: "Projected",
        type: "line" as const,
        muted: true,
        data: [
          ...actual.slice(0, -1).map((p) => ({ x: p.x, y: null as number | null })),
          ...(lastActual ? [{ x: lastActual.x, y: lastActual.y }] : []),
          ...projected,
        ],
      },
    ];
  }, [actual, projected]);

  const at60 = projected[59]?.y ?? todayCumulative;
  const yFormat = (value: number, context: "axis" | "tooltip") =>
    context === "axis" && value >= 10 ? usd(value) : usd(value);

  const chart = (
    <GlowChart
      type="line"
      color="#cbff3d"
      data={series}
      label="Expected income from tracked and projected views"
      height={compact ? 148 : 240}
      axis={!compact}
      grid={!compact}
      tooltip={!compact}
      legend={!compact}
      yFormat={yFormat}
      animate
    />
  );

  if (compact) {
    return (
      <NeonFrame as="section" label="Expected income" tabs={{ topRight: usd(at60) }} color="#cbff3d" className="h-full min-h-0 rounded-2xl border-white/10 p-4">
        <p className="text-xs text-white/50">Illustrative at 60 days</p>
        <p className="mt-1 text-3xl font-semibold tracking-tight text-white">{usd(at60)}</p>
        <div className="mt-3 min-h-0 flex-1">{chart}</div>
        <p className="mt-2 text-[11px] text-white/40">Click to open · TikTok assumed RPM</p>
      </NeonFrame>
    );
  }

  return (
    <NeonFrame as="section" label="Expected income" tabs={{ topRight: usd(at60) }} color="#cbff3d" className="flex h-full flex-col p-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="text-sm text-white/55">
          Tracked uses real views. Projected continues from each clip&apos;s virality score.
        </p>
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

      <div className="mt-4 grid grid-cols-3 gap-3">
        {CHECKPOINTS.map((cp, index) => {
          const point = projected[cp - 1];
          const prior = index === 0 ? todayCumulative : (projected[CHECKPOINTS[index - 1] - 1]?.y ?? todayCumulative);
          const delta = point ? point.y - prior : 0;
          return (
            <HoverBeam key={cp} className="rounded-xl border-white/10 bg-[var(--mtv-surface-high)] p-3">
              <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-white/50">
                In {cp} days
              </span>
              <span className="mt-1 block text-2xl font-semibold tracking-tight tabular-nums text-[var(--mtv-gold)]">
                {point ? usd(point.y) : "—"}
              </span>
              <span className="text-[11px] text-white/45">
                <span className={cn("font-medium", delta >= 0 ? "text-[var(--mtv-green)]" : "text-[var(--mtv-red)]")}>
                  {delta >= 0 ? "+" : ""}
                  {usd(delta)}
                </span>{" "}
                from prior checkpoint
              </span>
            </HoverBeam>
          );
        })}
      </div>

      <div className="mt-4 min-h-0 flex-1">{chart}</div>

      <p className="mt-3 text-xs leading-relaxed text-white/45">
        Illustrative. Earnings default to an assumed TikTok RPM ($0.04 / 1k views).
        Not a published payout table and not a guarantee of income.
      </p>
    </NeonFrame>
  );
}
