"use client";

/**
 * Explore: every published clip on the platform.
 *
 * The search bar searches all published clips. Below it: browse by game, the
 * clip grid and the marquee, all from
 * the live feed. Drafts never appear here; they live in My Library.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, Search as SearchIcon, Upload } from "lucide-react";

import { ClipMarquee } from "@/components/explore/clip-marquee";
import { SiteNav } from "@/components/hero/site-nav";
import { SearchPanel } from "@/components/search-panel";
import { ClipThumbnail } from "@/components/ui/clip-thumbnail";
import { Pill, PillRow } from "@/components/ui/pill";
import { ScreenTitle, SectionHeader } from "@/components/ui/screen-header";
import { ScrollExpandMedia } from "@/components/ui/scroll-expansion-hero";
import { absoluteUrl, fetchVideos, formatDuration, type SearchResult, type Video } from "@/lib/api";
import { usePageTitle } from "@/lib/use-page-title";

const EXPLORE_HERO_VIDEO = "/videos/1.mp4";
const EXPLORE_HERO_POSTER = "/images/explore-hero.jpg";

export default function ExplorePage() {
  usePageTitle("Explore");
  const router = useRouter();
  const [videos, setVideos] = useState<Video[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [game, setGame] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setVideos(await fetchVideos(100));
      setError(null);
    } catch (caught) {
      setVideos([]);
      setError(caught instanceof Error ? caught.message : "Could not load clips");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const searchable = useMemo(() => (videos ?? []).filter((v) => v.searchable), [videos]);
  const games = useMemo(() => {
    const counts = new Map<string, number>();
    for (const v of searchable) if (v.game) counts.set(v.game, (counts.get(v.game) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [searchable]);
  const filtered = game ? searchable.filter((v) => v.game === game) : searchable;

  const openResult = (result: SearchResult) => {
    router.push(`/video/${result.video_id}?t=${Math.floor(result.seek_seconds)}`);
  };

  return (
    <div className="min-h-screen text-[var(--mtv-text)]">
      <SiteNav />

      <main id="main-content">
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
            level="h2"
            action={
              <Link
                href="/upload"
                className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--mtv-gold)] px-3.5 py-2 text-[13px] font-bold text-[var(--mtv-on-gold)]"
              >
                <Upload className="h-3.5 w-3.5" />
                Upload
              </Link>
            }
            accent="clips."
          >
            Explore
          </ScreenTitle>

          <div className="rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-4 sm:p-6">
            <div className="mb-4 flex items-center gap-2 text-[13px] font-semibold text-[var(--mtv-gold)]">
              <SearchIcon className="h-4 w-4" />
              Search every clip, every moment
            </div>
            <SearchPanel
              scope="gallery"
              placeholder="Search clips, moments, what was said…"
              scopeLabel={
                <span>
                  {videos === null
                    ? "Loading clips…"
                    : `${searchable.length} published clip${searchable.length === 1 ? "" : "s"}`}
                </span>
              }
              onOpenResult={openResult}
              disabled={searchable.length === 0}
              disabledMessage={videos === null ? "Loading clips…" : "No published clips yet."}
            />
          </div>

          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-lg border border-[var(--mtv-red)]/40 bg-[var(--mtv-red)]/10 p-3 text-sm text-[var(--mtv-red)]">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>{error}</p>
            </div>
          )}

          {games.length > 0 && (
            <section className="space-y-3">
              <SectionHeader title="Browse by game" />
              <PillRow>
                <Pill selected={game === null} onClick={() => setGame(null)}>
                  All · {searchable.length}
                </Pill>
                {games.map(([g, count]) => (
                  <Pill key={g} selected={game === g} onClick={() => setGame(g)}>
                    {g} · {count}
                  </Pill>
                ))}
              </PillRow>
            </section>
          )}

          <section className="space-y-3">
            <SectionHeader title={game ? `${game} clips` : "Latest clips"} />
            {filtered.length === 0 && videos !== null ? (
              <p className="text-sm text-[var(--mtv-text-2)]">No published clips yet.</p>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {filtered.map((video) => (
                  <Link key={video.video_id} href={`/video/${video.video_id}`} className="group">
                    <ClipThumbnail
                      compact
                      src={absoluteUrl(video.thumbnail_url)}
                      // Decorative: the title right below is already in this same
                      // link's text, so a real alt here would just repeat it.
                      alt=""
                      duration={formatDuration(video.duration_seconds)}
                      ageRestricted={video.age_restricted}
                    />
                    <p className="mt-1.5 line-clamp-2 text-[13px] font-semibold group-hover:text-[var(--mtv-gold)]">
                      {video.title}
                    </p>
                    <p className="text-[11px] text-[var(--mtv-text-2)]">
                      {[video.uploader && `@${video.uploader}`, video.game].filter(Boolean).join(" · ")}
                      {" · "}
                      {video.view_count.toLocaleString()} views
                    </p>
                  </Link>
                ))}
              </div>
            )}
          </section>

          {searchable.length > 0 && (
            <section className="space-y-3">
              <SectionHeader title="Every clip on the platform" />
              <ClipMarquee videos={searchable} />
            </section>
          )}
        </div>
      </ScrollExpandMedia>
      </main>
    </div>
  );
}
