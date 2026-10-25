"use client";

import { Play } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Gold/dark clip thumbnail per the MinedTv UI spec — 16:9, radius 14 (10
 * compact), centred play button, bottom-right duration badge. Used wherever
 * real clip data is rendered on /explore; no fabricated game chip, since the
 * backend doesn't tag clips with a game.
 */
export function ClipThumbnail({
  src,
  alt = "",
  duration,
  compact = false,
  className,
}: {
  src: string | null;
  alt?: string;
  duration?: string;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative aspect-video overflow-hidden bg-[var(--mtv-surface-high)]",
        compact ? "rounded-[10px]" : "rounded-[14px]",
        className
      )}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={alt} className="h-full w-full object-cover" draggable={false} />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center">
          <Play className="h-8 w-8 text-white/12" strokeWidth={1.5} />
        </div>
      )}

      <div className="pointer-events-none absolute inset-0 grid place-items-center">
        <span
          className={cn(
            "grid place-items-center rounded-full bg-black/45",
            compact ? "h-8 w-8" : "h-[52px] w-[52px]"
          )}
        >
          <Play className="h-5 w-5 fill-white text-white" />
        </span>
      </div>

      {duration && (
        <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[11px] font-semibold text-white">
          {duration}
        </span>
      )}
    </div>
  );
}
