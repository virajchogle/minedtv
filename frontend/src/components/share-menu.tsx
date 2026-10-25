"use client";

/**
 * Share a clip: copy its link, use the device share sheet when the browser has one, post it to
 * YouTube (owner, published clips; jumps to the "Post to YouTube" panel), or open it on YouTube
 * once it's been posted.
 */

import { useEffect, useRef, useState } from "react";
import { Check, ExternalLink, Link2, Share2, Youtube } from "lucide-react";

import type { Video } from "@/lib/api";

export function ShareMenu({ video, isOwner }: { video: Video; isOwner: boolean }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const canPost = isOwner && video.publish_state === "published";
  const nativeShare = typeof navigator !== "undefined" && "share" in navigator;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !rootRef.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const url = () => `${window.location.origin}/video/${video.video_id}`;

  const copy = async () => {
    await navigator.clipboard?.writeText(url());
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const share = async () => {
    setOpen(false);
    await navigator.share({ title: video.title, url: url() }).catch(() => undefined);
  };

  const toYouTube = () => {
    setOpen(false);
    document.getElementById("post-to-youtube")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const item =
    "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--mtv-text)] hover:bg-[var(--mtv-surface-high)]";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--mtv-divider)] px-3 py-1.5 text-[13px] font-semibold transition-colors hover:bg-[var(--mtv-surface-high)]"
      >
        <Share2 className="h-3.5 w-3.5" /> Share
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 z-30 mt-2 w-56 rounded-xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-1.5 shadow-2xl"
        >
          <button type="button" role="menuitem" onClick={() => void copy()} className={item}>
            {copied ? <Check className="h-4 w-4 text-[var(--mtv-green)]" /> : <Link2 className="h-4 w-4" />}
            {copied ? "Link copied" : "Copy link"}
          </button>
          {nativeShare && (
            <button type="button" role="menuitem" onClick={() => void share()} className={item}>
              <Share2 className="h-4 w-4" /> Share…
            </button>
          )}
          {canPost && (
            <button type="button" role="menuitem" onClick={toYouTube} className={item}>
              <Youtube className="h-4 w-4 text-[var(--mtv-red)]" /> Post to YouTube
            </button>
          )}
          {video.youtube_url && (
            <a href={video.youtube_url} target="_blank" rel="noreferrer" role="menuitem" className={item}>
              <ExternalLink className="h-4 w-4" /> Watch on YouTube
            </a>
          )}
          {isOwner && !canPost && !video.youtube_url && (
            <p className="px-2.5 py-1.5 text-[11px] text-[var(--mtv-text-2)]">Publish this clip to post it to YouTube.</p>
          )}
        </div>
      )}
    </div>
  );
}
