"use client";

/**
 * Profile — scroped to the scroll-expansion hero requested for this pass.
 * The full Android-parity profile screen (stats card, clip grid, in-clip
 * search) is out of scope here; this is the hero shell plus a short About
 * block, ready for the real profile content to land on top of it later.
 *
 * mediaSrc is a placeholder (the same hero still used on the homepage) until
 * a real profile reel/video is supplied — swap mediaType to "video" and
 * mediaSrc to that file once it exists; everything else is unchanged.
 */

import { SiteNav } from "@/components/hero/site-nav";
import { ScrollExpandMedia } from "@/components/ui/scroll-expansion-hero";

export default function ProfilePage() {
  return (
    <div className="bg-[var(--mtv-bg)] text-[var(--mtv-text)]">
      <SiteNav />
      <ScrollExpandMedia
        mediaType="image"
        mediaSrc="/images/minecraft-hero.webp"
        bgImageSrc="/images/minecraft-hero.webp"
        title="MinedTV"
        date="Clip the plays that blow your mind"
        scrollToExpand="Scroll to expand"
      >
        <div className="space-y-4 text-center">
          <h3 className="text-2xl font-bold">Every clip, searchable.</h3>
          <p className="text-[15px] leading-relaxed text-[var(--mtv-text-2)]">
            This is a placeholder reel for the profile hero — swap it for a real
            highlight video whenever one is ready. The expand-on-scroll mechanic
            underneath it already works with either an image or a video.
          </p>
        </div>
      </ScrollExpandMedia>
    </div>
  );
}
