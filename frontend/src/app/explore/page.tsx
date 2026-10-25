"use client";

/**
 * Explore — dark/gold screen per the MinedTv UI spec.
 *
 * Two data sources, deliberately kept apart:
 *  - The search bar is always real: it calls the same `searchVideos`/
 *    `fetchVideos` pipeline as every other page, so results, counts and
 *    errors reflect whatever is actually in the connected backend (or a
 *    clear "can't reach it" message if there isn't one right now).
 *  - Everything below it — topic pills, the grid, the clip marquee — uses
 *    SAMPLE_CLIPS, hardcoded placeholder data, so the page's layout and the
 *    scroll-marquee animation are visible without a backend connection.
 *    Every one of those sections is labelled "Sample preview" so nothing
 *    here is mistaken for real uploaded content.
 *
 * The spec's "Popular Games" row assumes clips are tagged with a game, which
 * this backend's Video model doesn't have (no `game` field — only free-form
 * `topics`), so that row is replaced with "Browse by topic" instead of
 * fabricating game tiles with invented clip counts.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Search as SearchIcon, Upload } from "lucide-react";

import { ClipMarquee } from "@/components/explore/clip-marquee";
import { SiteNav } from "@/components/hero/site-nav";
import { SearchPanel } from "@/components/search-panel";
import { ClipThumbnail } from "@/components/ui/clip-thumbnail";
import { Pill, PillRow } from "@/components/ui/pill";
import { ScreenTitle, SectionHeader } from "@/components/ui/screen-header";
import { ScrollExpandMedia } from "@/components/ui/scroll-expansion-hero";
import { fetchVideos, formatDuration, type SearchResult } from "@/lib/api";
import { SAMPLE_CLIPS } from "@/lib/sample-clips";

const EXPLORE_HERO_VIDEO = "/videos/explore-hero.mp4";
const EXPLORE_HERO_POSTER = "/images/minecraft-hero.webp";

const SAMPLE_TOPICS = (() => {
  const counts = new Map<string, number>();
  for (const clip of SAMPLE_CLIPS) {
    for (const t of clip.topics) counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
})();

export default function ExplorePage() {
  const router = useRouter();
  // Only used to tell the search bar whether the backend has anything
  // indexed — never used to render the grid/marquee below.
  const [searchableCount, setSearchableCount] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const videos = await fetchVideos();
      setSearchableCount(videos.filter((v) => v.searchable).length);
    } catch {
      setSearchableCount(0);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const [topic, setTopic] = useState<string | null>(null);
  const filtered = topic ? SAMPLE_CLIPS.filter((v) => v.topics.includes(topic)) : SAMPLE_CLIPS;

  const openResult = (result: SearchResult) => {
    router.push(`/video/${result.video_id}?t=${Math.floor(result.seek_seconds)}`);
  };

  return (
    <div className="min-h-screen bg-[var(--mtv-bg)] text-[var(--mtv-text)]">
      <SiteNav />

      <ScrollExpandMedia
        mediaType="video"
        mediaSrc={EXPLORE_HERO_VIDEO}
        posterSrc={EXPLORE_HERO_POSTER}
        bgImageSrc={EXPLORE_HERO_POSTER}
        title="Explore Clips"
        date="Every moment, searchable"
        scrollToExpand="Scroll to expand"
      >
      <div className="mx-auto max-w-6xl space-y-10 px-4 pb-16 sm:px-8">
        <ScreenTitle
          action={
            <Link
              href="/upload"
              className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--mtv-gold)] px-3.5 py-2 text-[13px] font-bold text-[var(--mtv-on-gold)]"
            >
              <Upload className="h-3.5 w-3.5" />
              Upload
            </Link>
          }
        >
          Explore
        </ScreenTitle>

        {/* ── real backend search — not sample data ── */}
        <div className="rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-4 sm:p-6">
          <div className="mb-4 flex items-center gap-2 text-[13px] font-semibold text-[var(--mtv-gold)]">
            <SearchIcon className="h-4 w-4" />
            Search every clip, every moment
          </div>
          <SearchPanel
            scope="gallery"
            placeholder="Search clips, moments, topics…"
            scopeLabel={
              <span>
                {searchableCount === null
                  ? "Checking your library…"
                  : searchableCount > 0
                    ? `${searchableCount} clip${searchableCount === 1 ? "" : "s"} indexed`
                    : "Connect the backend to search your real clips"}
              </span>
            }
            onOpenResult={openResult}
            disabled={!searchableCount}
            disabledMessage="Connect the MineDTV backend and index a clip to search for real."
          />
        </div>

        {/* ── everything from here down is placeholder layout, not real data ── */}
        <div className="rounded-xl border border-dashed border-[var(--mtv-divider)] px-4 py-2 text-center text-[11px] uppercase tracking-[0.2em] text-[var(--mtv-text-2)]">
          Sample preview — layout &amp; animation only, not your real library
        </div>

        <section className="space-y-3">
          <SectionHeader title="Browse by topic" />
          <PillRow>
            <Pill selected={topic === null} onClick={() => setTopic(null)}>
              All
            </Pill>
            {SAMPLE_TOPICS.map(([t, count]) => (
              <Pill key={t} selected={topic === t} onClick={() => setTopic(t)}>
                {t} · {count}
              </Pill>
            ))}
          </PillRow>
        </section>

        <section className="space-y-3">
          <SectionHeader title={topic ? `"${topic}" clips` : "Library"} />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {filtered.map((video) => (
              <div key={video.video_id}>
                <ClipThumbnail
                  compact
                  src={null}
                  alt={video.title}
                  duration={formatDuration(video.duration_seconds)}
                />
                <p className="mt-1.5 line-clamp-2 text-[13px] font-semibold">{video.title}</p>
                <p className="text-[11px] text-[var(--mtv-text-2)]">
                  {video.segment_count} moments indexed
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="space-y-3">
          <SectionHeader title="Every clip on the platform" />
          <ClipMarquee videos={SAMPLE_CLIPS} linkable={false} />
        </section>
      </div>
      </ScrollExpandMedia>
    </div>
  );
}
