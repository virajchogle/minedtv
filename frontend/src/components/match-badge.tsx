"use client";

import { cn } from "@/lib/utils";
import type { MatchBucket } from "@/lib/api";

const STYLES: Record<MatchBucket, { label: string; className: string }> = {
  strong: {
    label: "Strong match",
    className: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  },
  moderate: {
    label: "Moderate match",
    className: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  },
  weak: {
    label: "Weak match",
    className: "bg-orange-500/15 text-orange-300 border-orange-500/40",
  },
  no_reliable_match: {
    label: "No reliable match",
    className: "bg-zinc-500/15 text-zinc-400 border-zinc-500/40",
  },
};

export function MatchBadge({
  bucket,
  className,
}: {
  bucket: MatchBucket;
  className?: string;
}) {
  const style = STYLES[bucket];
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium",
        style.className,
        className
      )}
    >
      {style.label}
    </span>
  );
}

export const bucketLabel = (bucket: MatchBucket) => STYLES[bucket].label;
