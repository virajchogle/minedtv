"use client";

import Link from "next/link";

import { ClipThumbnail } from "@/components/ui/clip-thumbnail";
import { Marquee } from "@/components/ui/marquee";
import { absoluteUrl, formatDuration, type Video } from "@/lib/api";

/**
 * "Every clip on the platform," animated. Two rows drifting opposite
 * directions, laid out with the same tilted perspective wrapper as the
 * 21st.dev 3D-marquee reference, swapped from testimonial cards to clip
 * thumbnails.
 *
 * `linkable` controls whether tiles route to `/video/[id]` — real videos do;
 * sample/placeholder clips (ids like "sample-1") have no such page, so the
 * caller passes `linkable={false}` for those and tiles render as plain
 * (non-navigating) cards instead of dead links.
 */
export function ClipMarquee({ videos, linkable = true }: { videos: Video[]; linkable?: boolean }) {
  const searchable = videos.filter((v) => v.searchable);
  if (searchable.length === 0) return null;

  // A handful of tiles repeats cleanly; many tiles would make the loop lag.
  const rowA = searchable.slice(0, 10);
  const rowB = [...searchable].reverse().slice(0, 10);

  return (
    <div className="relative h-[420px] w-full overflow-hidden [perspective:500px]">
      <div
        className="absolute inset-0 flex flex-col justify-center gap-6"
        style={{ transform: "rotateX(14deg) rotateZ(-4deg) scale(1.08)" }}
      >
        <MarqueeRow videos={rowA} linkable={linkable} />
        <MarqueeRow videos={rowB} linkable={linkable} reverse />
        <MarqueeRow videos={rowA} linkable={linkable} />
      </div>

      <div className="pointer-events-none absolute inset-y-0 left-0 w-1/4 bg-gradient-to-r from-[#07090f]" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-1/4 bg-gradient-to-l from-[#07090f]" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-1/5 bg-gradient-to-b from-[#07090f]" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1/5 bg-gradient-to-t from-[#07090f]" />
    </div>
  );
}

function MarqueeRow({
  videos,
  reverse,
  linkable,
}: {
  videos: Video[];
  reverse?: boolean;
  linkable: boolean;
}) {
  return (
    <Marquee pauseOnHover reverse={reverse} repeat={2} className="[--duration:46s]">
      {videos.map((video) => {
        const tileClassName =
          "block w-[200px] shrink-0 rounded-[14px] ring-1 ring-[var(--mtv-divider)] transition-transform hover:-translate-y-1 hover:ring-[var(--mtv-gold)]/50";
        const tile = (
          <>
            <ClipThumbnail
              src={absoluteUrl(video.thumbnail_url)}
              alt={video.title}
              duration={formatDuration(video.duration_seconds)}
              ageRestricted={video.age_restricted}
            />
            <p className="mt-1.5 truncate px-0.5 text-[12px] font-medium text-[var(--mtv-text)]">
              {video.title}
            </p>
          </>
        );
        return linkable ? (
          <Link key={video.video_id} href={`/video/${video.video_id}`} className={tileClassName}>
            {tile}
          </Link>
        ) : (
          <div key={video.video_id} className={tileClassName}>
            {tile}
          </div>
        );
      })}
    </Marquee>
  );
}
