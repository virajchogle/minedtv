"use client";

/**
 * Audience Flow: real engagement breakdown: each game you've clipped, flowing
 * into what happened with those period views (liked / commented / viewed only).
 * Every link's value is summed straight from ClipAnalytics.period_* for the
 * selected range, so nothing here is fabricated or illustrative.
 */

import { useMemo, useState } from "react";

import { EChartsBase, TOOLTIP_STYLE, type EChartsOption } from "@/components/ui/echarts-base";
import { GlowChart } from "@/components/ui/glow-chart";
import type { ClipAnalytics } from "@/lib/minedtv-types";

const OUTCOME_LIKED = "Liked";
const OUTCOME_COMMENTED = "Commented";
const OUTCOME_VIEWED_ONLY = "Viewed only";

const GAME_COLORS = ["#cbff3d", "#22d3ee", "#a78bfa", "#fb923c", "#60a5fa", "#f472b6"];
const OUTCOME_COLORS: Record<string, string> = {
  [OUTCOME_LIKED]: "#4ade80",
  [OUTCOME_COMMENTED]: "#fb923c",
  [OUTCOME_VIEWED_ONLY]: "#64748b",
};

function useCssVar(name: string, fallback: string): string {
  const [value] = useState(() => {
    if (typeof document === "undefined") return fallback;
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  });
  return value;
}

export function AudienceFlowSankey({ clips, compact = false }: { clips: ClipAnalytics[]; compact?: boolean }) {
  const divider = useCssVar("--mtv-divider", "rgba(255,255,255,0.12)");
  const text = useCssVar("--mtv-text", "#fff");

  const { nodes, links, totalViews } = useMemo(() => {
    const byGame = new Map<string, { views: number; likes: number; comments: number }>();
    for (const c of clips) {
      const key = c.clip.game ?? "Other";
      const agg = byGame.get(key) ?? { views: 0, likes: 0, comments: 0 };
      agg.views += c.period_views;
      agg.likes += c.period_likes;
      agg.comments += c.period_comments;
      byGame.set(key, agg);
    }

    const gameNames = [...byGame.entries()].filter(([, v]) => v.views > 0).sort((a, b) => b[1].views - a[1].views);

    const nodeNames = new Set<string>([OUTCOME_LIKED, OUTCOME_COMMENTED, OUTCOME_VIEWED_ONLY]);
    const linkList: { source: string; target: string; value: number }[] = [];
    let totalViews = 0;

    for (const [game, agg] of gameNames) {
      nodeNames.add(game);
      totalViews += agg.views;
      const liked = Math.min(agg.likes, agg.views);
      const commented = Math.min(agg.comments, Math.max(0, agg.views - liked));
      const viewedOnly = Math.max(0, agg.views - liked - commented);
      if (liked > 0) linkList.push({ source: game, target: OUTCOME_LIKED, value: liked });
      if (commented > 0) linkList.push({ source: game, target: OUTCOME_COMMENTED, value: commented });
      if (viewedOnly > 0) linkList.push({ source: game, target: OUTCOME_VIEWED_ONLY, value: viewedOnly });
    }

    return { nodes: [...nodeNames].map((name) => ({ name })), links: linkList, totalViews };
  }, [clips]);

  const option: EChartsOption = useMemo(
    () => ({
      tooltip: {
        trigger: "item",
        triggerOn: "mousemove",
        ...TOOLTIP_STYLE,
      },
      series: [
        {
          type: "sankey",
          data: nodes.map((node, index) => ({
            ...node,
            itemStyle: {
              color: OUTCOME_COLORS[node.name] ?? GAME_COLORS[index % GAME_COLORS.length],
              borderColor: divider,
            },
          })),
          links,
          emphasis: { focus: "adjacency" },
          lineStyle: { color: "gradient", opacity: 0.4, curveness: 0.5 },
          label: { color: text, fontSize: 13, fontWeight: 500 },
          nodeWidth: 14,
          nodeGap: 16,
          left: 8,
          right: 96,
          top: 12,
          bottom: 12,
          animationDuration: 900,
          animationEasing: "cubicOut",
        },
      ],
    }),
    [nodes, links, divider, text]
  );

  const outcomes = useMemo(() => {
    let liked = 0;
    let commented = 0;
    let viewedOnly = 0;
    for (const link of links) {
      if (link.target === OUTCOME_LIKED) liked += link.value;
      else if (link.target === OUTCOME_COMMENTED) commented += link.value;
      else viewedOnly += link.value;
    }
    return [
      { x: "Liked", y: liked },
      { x: "Commented", y: commented },
      { x: "Viewed only", y: viewedOnly },
    ];
  }, [links]);

  if (links.length === 0) {
    return (
      <section className="flex h-full items-center justify-center rounded-2xl border border-dashed border-[var(--mtv-divider)] p-6 text-center text-sm text-[var(--mtv-text-2)]">
        No views yet in this range. Audience Flow fills in once clips start getting watched.
      </section>
    );
  }

  if (compact) {
    return (
      <section className="flex h-full min-h-0 flex-col p-4">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--mtv-gold)]">Audience</p>
        <p className="mt-1 text-3xl font-semibold tracking-tight text-white">{totalViews.toLocaleString()}</p>
        <p className="text-xs text-white/50">Period views by what people did</p>
        <div className="mt-3 min-h-0 flex-1">
          <GlowChart
            type="bar"
            color="#cbff3d"
            data={outcomes}
            label="Period views by outcome"
            height={160}
            axis={false}
            grid={false}
            tooltip={false}
            animate
          />
        </div>
        <p className="mt-2 text-[11px] text-white/40">Click to open the flow</p>
      </section>
    );
  }

  return (
    <section className="space-y-3 rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-4 sm:p-6">
      <div>
        <h2 className="text-lg font-bold uppercase tracking-wider text-[var(--mtv-gold)]">Audience flow</h2>
        <p className="mt-1 text-sm text-[var(--mtv-text-2)]">
          {totalViews.toLocaleString()} period views by game, split by what viewers actually did.
        </p>
      </div>
      <EChartsBase option={option} height={Math.max(260, nodes.length * 28)} />
    </section>
  );
}
