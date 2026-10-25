"use client";

/**
 * Profile: the acting user's channel: stats across their clips, their
 * published clips (what everyone sees), and quick links into the private
 * buckets in My Library. Keeps the scroll-expansion hero.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Eye, Heart, Loader2 } from "lucide-react";

import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import { SiteNav } from "@/components/hero/site-nav";
import { ScrollExpandMedia } from "@/components/ui/scroll-expansion-hero";
import { VideoCard } from "@/components/video-card";
import { fetchMyVideos, type Video } from "@/lib/api";

export default function ProfilePage() {
  const me = useCurrentUser();
  const [clips, setClips] = useState<Video[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setClips(null);
    if (!me) return;
    fetchMyVideos("all", 100)
      .then((list) => {
        setClips(list);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [me]);

  const published = (clips ?? []).filter((c) => c.publish_state === "published");
  const stat = (label: string, value: number, href?: string) => {
    const body = (
      <div className="rounded-xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] px-4 py-3 text-center">
        <p className="text-xl font-bold">{value}</p>
        <p className="text-[11px] uppercase tracking-wider text-[var(--mtv-text-2)]">{label}</p>
      </div>
    );
    return href ? (
      <Link key={label} href={href} className="block transition-opacity hover:opacity-80">
        {body}
      </Link>
    ) : (
      <div key={label}>{body}</div>
    );
  };

  return (
    <div className="text-[var(--mtv-text)]">
      <SiteNav />
      <ScrollExpandMedia
        mediaType="image"
        mediaSrc={published[0]?.thumbnail_url ?? "/images/minecraft-hero.webp"}
        bgImageSrc="/images/minecraft-hero.webp"
        title={me ? `@${me.username}` : "MinedIt"}
        date={me ? `${published.length} published clips` : "Clip the plays that blow your mind"}
        scrollToExpand="Scroll to expand"
      >
        <div className="mx-auto max-w-5xl space-y-8 px-4 pb-16 sm:px-8">
          {!me ? (
            <ChooseUserNotice action="see your profile" />
          ) : error ? (
            <p className="text-sm text-[var(--mtv-red)]">{error}</p>
          ) : clips === null ? (
            <p className="flex items-center gap-2 text-sm text-[var(--mtv-text-2)]">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading profile…
            </p>
          ) : (
            <>
              <div className="flex items-center gap-4">
                {me.avatar_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={me.avatar_url} alt="" className="h-16 w-16 rounded-full border border-[var(--mtv-divider)]" />
                )}
                <div>
                  <h2 className="text-2xl font-bold">{me.username}</h2>
                  <p className="flex items-center gap-3 text-sm text-[var(--mtv-text-2)]">
                    <span className="inline-flex items-center gap-1">
                      <Eye className="h-3.5 w-3.5" />
                      {clips.reduce((n, c) => n + c.view_count, 0).toLocaleString()} views
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Heart className="h-3.5 w-3.5" />
                      {clips.reduce((n, c) => n + c.like_count, 0).toLocaleString()} likes
                    </span>
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {stat("Published", published.length)}
                {stat("My videos", clips.filter((c) => c.publish_state !== "published").length, "/library")}
                {stat("On YouTube", clips.filter((c) => c.youtube_url).length, "/library")}
                {stat("Games", new Set(clips.map((c) => c.game).filter(Boolean)).size)}
              </div>

              <section className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-bold">Published clips</h3>
                  <Link href="/library" className="text-sm text-[var(--mtv-gold)] underline underline-offset-2">
                    Manage all clips
                  </Link>
                </div>
                {published.length === 0 ? (
                  <p className="text-sm text-[var(--mtv-text-2)]">
                    Nothing published yet. Publish a clip from its page to show it here and in the feed.
                  </p>
                ) : (
                  <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
                    {published.map((clip) => (
                      <VideoCard key={clip.video_id} video={clip} />
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </ScrollExpandMedia>
    </div>
  );
}
