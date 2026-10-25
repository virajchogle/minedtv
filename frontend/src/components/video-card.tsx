"use client";

import Link from "next/link";
import { AlertTriangle, Eye, Heart, Loader2, Play } from "lucide-react";

import { PublishBadge } from "@/components/clip-actions";

import {
  STATUS_COPY,
  absoluteUrl,
  formatDuration,
  formatUploadDate,
  type Video,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const TONE_CLASSES = {
  ok: "bg-[var(--mtv-green)]/15 text-[var(--mtv-green)] border-[var(--mtv-green)]/40",
  partial: "bg-[var(--mtv-gold)]/15 text-[var(--mtv-gold)] border-[var(--mtv-gold)]/40",
  working: "bg-white/10 text-white/80 border-white/25",
  error: "bg-[var(--mtv-red)]/15 text-[var(--mtv-red)] border-[var(--mtv-red)]/40",
} as const;

export function VideoCard({ video }: { video: Video }) {
  const status = STATUS_COPY[video.processing_status];
  const thumbnail = absoluteUrl(video.thumbnail_url);
  const isWorking = status.tone === "working";

  const card = (
    <div
      className={cn(
        "group overflow-hidden rounded-2xl border bg-[var(--mtv-surface)] transition-colors",
        video.searchable
          ? "border-[var(--mtv-divider)] hover:border-[var(--mtv-gold)]/50"
          : "border-[var(--mtv-divider)]/60"
      )}
    >
      <div className="relative flex aspect-video items-center justify-center overflow-hidden bg-[var(--mtv-surface-high)]">
        {thumbnail ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumbnail}
            alt=""
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
          />
        ) : isWorking ? (
          <Loader2 className="h-8 w-8 animate-spin text-[var(--mtv-text-2)]/60" />
        ) : video.processing_status === "failed" ? (
          <AlertTriangle className="h-8 w-8 text-[var(--mtv-red)]/70" />
        ) : (
          <Play className="h-10 w-10 text-[var(--mtv-text-2)]/50" />
        )}

        {video.searchable && (
          <span className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/40">
            <Eye className="h-9 w-9 text-white opacity-0 transition-opacity group-hover:opacity-100" />
          </span>
        )}

        <span className="absolute bottom-2 right-2 rounded bg-black/75 px-1.5 py-0.5 font-mono text-[11px] text-white">
          {formatDuration(video.duration_seconds)}
        </span>

        {video.searchable && video.publish_state ? (
          video.publish_state !== "published" && (
            <PublishBadge state={video.publish_state} className="absolute left-2 top-2" />
          )
        ) : (
          <span
            className={cn(
              "absolute left-2 top-2 rounded-full border px-2 py-0.5 text-[11px] font-medium",
              TONE_CLASSES[status.tone]
            )}
          >
            {status.label}
          </span>
        )}
      </div>

      <div className="space-y-1 p-4">
        <h3 className="line-clamp-1 font-semibold leading-tight text-[var(--mtv-text)]">
          {video.title}
        </h3>
        <p className="text-xs text-[var(--mtv-text-2)]">
          {[video.uploader && `@${video.uploader}`, video.game, formatUploadDate(video.upload_date)]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {video.searchable && (
          <p className="flex items-center gap-3 text-xs text-[var(--mtv-text-2)]">
            <span className="inline-flex items-center gap-1">
              <Eye className="h-3 w-3" /> {video.view_count.toLocaleString()}
            </span>
            <span className="inline-flex items-center gap-1">
              <Heart className={cn("h-3 w-3", video.liked_by_me && "fill-current text-[var(--mtv-red)]")} />{" "}
              {video.like_count.toLocaleString()}
            </span>
          </p>
        )}
        {video.summary && (
          <p className="line-clamp-2 pt-1 text-xs text-[var(--mtv-text-2)]/80">{video.summary}</p>
        )}
        {video.processing_status === "visual_only" && (
          <p className="pt-1 text-xs text-[var(--mtv-gold)]/90">
            Searchable by appearance only — no transcript was indexed.
          </p>
        )}
        {video.processing_status === "failed" && video.processing_error && (
          <p className="line-clamp-2 pt-1 text-xs text-[var(--mtv-red)]/90">
            {video.processing_error}
          </p>
        )}
      </div>
    </div>
  );

  if (!video.searchable) {
    return <div aria-disabled>{card}</div>;
  }

  return (
    <Link
      href={`/video/${video.video_id}`}
      className="block rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--mtv-gold)]"
      aria-label={`Open ${video.title} and search inside it`}
    >
      {card}
    </Link>
  );
}
