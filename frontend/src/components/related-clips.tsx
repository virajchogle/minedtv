"use client";

/** "More {game} clips": other published clips of the same game, under a clip. */

import { useEffect, useState } from "react";
import { Gamepad2 } from "lucide-react";

import { VideoCard } from "@/components/video-card";
import { fetchRelated, type Video } from "@/lib/api";

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
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Gamepad2 className="h-4 w-4 text-[var(--mtv-gold)]" />
        More {game} clips
      </h2>
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {clips.map((clip) => (
          <VideoCard key={clip.video_id} video={clip} />
        ))}
      </div>
    </section>
  );
}
