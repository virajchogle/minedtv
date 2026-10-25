"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { API_BASE_URL, fetchSearchConfig, type SearchConfig } from "@/lib/api";

interface EvalRow {
  id: number;
  timestamp: string;
  query: string;
  scope: "gallery" | "video";
  scope_video_id: string | null;
  result_count: number;
  strong_count: number;
  moderate_count: number;
  weak_count: number;
  no_match_count: number;
  avg_evidence: number;
  max_evidence: number;
  videos_represented: number;
  signals_used: string[];
  latency_ms: number;
}

function relativeTime(iso: string): string {
  const date = new Date(iso.endsWith("Z") ? iso : `${iso}Z`);
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return `${Math.max(seconds, 0)}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function EvalPage() {
  const [rows, setRows] = useState<EvalRow[]>([]);
  const [config, setConfig] = useState<SearchConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/search/history`);
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const body = (await response.json()) as { evals: EvalRow[] };
      setRows(body.evals);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load history");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    fetchSearchConfig().then(setConfig).catch(() => setConfig(null));
    const timer = setInterval(() => void load(), 30_000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Retrieval telemetry</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Recent searches with the signals that ran and the buckets they produced. Refreshes
          every 30 seconds.
        </p>
      </header>

      {config && (
        <div className="grid gap-4 rounded-xl border bg-card p-4 text-xs sm:grid-cols-2">
          <div className="space-y-1">
            <p className="font-semibold uppercase tracking-wide text-muted-foreground">
              Bucket thresholds
            </p>
            <p className="font-mono">
              strong ≥ {config.buckets.strong} · moderate ≥ {config.buckets.moderate} · weak ≥{" "}
              {config.buckets.weak}
            </p>
            <p className="text-muted-foreground">
              Thresholds are heuristic cut points on the blended evidence score, not calibrated
              probabilities.
            </p>
          </div>
          <div className="space-y-1">
            <p className="font-semibold uppercase tracking-wide text-muted-foreground">Models</p>
            <ul className="space-y-0.5 font-mono">
              {Object.entries(config.models).map(([role, model]) => (
                <li key={role}>
                  {role}: {model}
                </li>
              ))}
            </ul>
            {!config.gemini_enabled && (
              <p className="text-amber-300">
                Gemini is not configured — retrieval is running CLIP-only.
              </p>
            )}
          </div>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      )}

      {error && <p className="text-sm text-destructive">Failed to load: {error}</p>}

      {!loading && !error && rows.length === 0 && (
        <div className="rounded-xl border border-dashed p-12 text-center text-sm text-muted-foreground">
          No searches recorded yet. Run one from the gallery.
        </div>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/30 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-4 py-3">When</th>
                <th className="px-4 py-3">Query</th>
                <th className="px-4 py-3">Scope</th>
                <th className="px-4 py-3 text-right">Results</th>
                <th className="px-4 py-3">Buckets</th>
                <th className="px-4 py-3 text-right">Avg evidence</th>
                <th className="px-4 py-3">Signals</th>
                <th className="px-4 py-3 text-right">Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((row) => (
                <tr key={row.id} className="transition-colors hover:bg-muted/20">
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted-foreground">
                    {relativeTime(row.timestamp)}
                  </td>
                  <td className="max-w-[200px] px-4 py-3">
                    <span className="line-clamp-1">{row.query}</span>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {row.scope === "video" ? "single video" : `gallery (${row.videos_represented})`}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">
                    {row.result_count}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {row.strong_count}S / {row.moderate_count}M / {row.weak_count}W /{" "}
                    {row.no_match_count}N
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">
                    {row.avg_evidence.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {row.signals_used.join(", ") || "none"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-muted-foreground">
                    {row.latency_ms}ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
