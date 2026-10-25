"use client";

/** "More {game}": other published clips of the same game, as a compact list beside a clip. */

import { useEffect, useState } from "react";
import Link from "next/link";

import { fetchRelated, formatDuration, type Video } from "@/lib/api";

export function RelatedClips({ game, excludeId }: { game: string; excludeId: string }) {
  const [clips, setClips] = useState<Video[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRelated(game, excludeId).then(
      (list) => !cancelled && setClips(list),
      () => !cancelled && setClips([])
    );
    return () => {
      cancelled = true;
    };
  }, [game, excludeId]);

  if (!clips || clips.length === 0) return null;
  return (
    <section className="space-y-4">
      <h2 className="font-mono text-[11px] uppercase tracking-[0.2em] text-[var(--mtv-text-2)]">More {game}</h2>
      <ul className="space-y-3">
        {clips.map((clip) => (
          <li key={clip.video_id}>
            <Link href={`/video/${clip.video_id}`} className="group flex gap-3">
              <span className="relative block aspect-video w-36 shrink-0 overflow-hidden rounded-lg bg-[var(--mtv-surface-high)]">
                {clip.thumbnail_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={clip.thumbnail_url}
                    alt=""
                    className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                  />
                )}
                <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1 font-mono text-[10px] text-white">
                  {formatDuration(clip.duration_seconds)}
                </span>
              </span>
              <span className="min-w-0 space-y-1">
                <span className="line-clamp-2 text-[13px] font-semibold leading-snug group-hover:text-[var(--mtv-gold)]">
                  {clip.title}
                </span>
                <span className="block truncate text-xs text-white/50">
                  @{clip.uploader} · {clip.view_count.toLocaleString()} views
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
