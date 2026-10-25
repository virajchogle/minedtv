"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown, Loader2, LogIn, LogOut, Moon, RefreshCw, Sun, Trash2 } from "lucide-react";

import { PublishBadge } from "@/components/clip-actions";
import { useAccount, useCurrentUser, useLoginHref } from "@/components/current-user";
import { SiteNav } from "@/components/hero/site-nav";
import { ScreenTitle } from "@/components/ui/screen-header";
import {
  BAND_MODERATE,
  BAND_STRONG,
  BAND_WEAK,
  STATUS_COPY,
  deleteVideo,
  fetchMyVideos,
  fetchServerConfig,
  formatDuration,
  reindexVideo,
  signOut,
  type Video,
} from "@/lib/api";
import type { ServerConfigOut } from "@/lib/minedtv-types";
import { usePageTitle } from "@/lib/use-page-title";

export default function SettingsPage() {
  usePageTitle("Settings");
  const account = useAccount();
  const me = useCurrentUser();
  const loginHref = useLoginHref();
  const [isDark, setIsDark] = useState(true);
  const [videos, setVideos] = useState<Video[]>([]);
  const [config, setConfig] = useState<ServerConfigOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  useEffect(() => {
    // Only your own clips: delete and re-index are owner actions.
    fetchMyVideos("all", 100)
      .then(setVideos)
      .catch((caught: Error) => setError(caught.message))
      .finally(() => setLoading(false));
    fetchServerConfig().then(setConfig).catch(() => setConfig(null));
  }, []);

  const toggleTheme = () => {
    const next = !isDark;
    document.documentElement.classList.toggle("dark", next);
    localStorage.setItem("minedtv-theme", next ? "dark" : "light");
    setIsDark(next);
  };

  const handleDelete = async (video: Video) => {
    if (
      !window.confirm(
        `Delete the clip “${video.title}”? The original upload stays in your library's search index; only this clip goes.`
      )
    ) {
      return;
    }
    setBusyId(video.video_id);
    setError(null);
    try {
      await deleteVideo(video.video_id);
      setVideos((previous) => previous.filter((v) => v.video_id !== video.video_id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Delete failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleReindex = async (video: Video) => {
    setBusyId(video.video_id);
    setError(null);
    try {
      // Reprocessing works on the whole upload (session), not a single clip.
      await reindexVideo(video.session_id ?? video.video_id);
      setVideos(await fetchMyVideos("all", 100));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Re-index failed");
    } finally {
      setBusyId(null);
    }
  };

  const outline =
    "inline-flex items-center gap-1.5 rounded-lg border border-[var(--mtv-divider)] px-3 py-1.5 text-[13px] font-semibold transition-colors hover:bg-[var(--mtv-surface-high)] disabled:opacity-40";

  return (
    <div className="min-h-screen px-4 pb-20 pt-28 text-[var(--mtv-text)] sm:px-8 sm:pt-32">
      <SiteNav />
      <main id="main-content" className="mx-auto max-w-3xl space-y-12">
        <ScreenTitle eyebrow="Settings">Settings</ScreenTitle>

        <Section title="Account">
          {account ? (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="font-semibold">@{account.username}</p>
                <p className="text-sm text-white/55">
                  {account.email}
                  {me && me.id !== account.id && <> · acting as @{me.username}</>}
                </p>
              </div>
              <button type="button" onClick={() => void signOut()} className={outline}>
                <LogOut className="h-3.5 w-3.5" /> Log out
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-sm text-white/55">
                {me ? <>Not signed in · using @{me.username}</> : "Not signed in."}
              </p>
              <Link href={loginHref} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--mtv-gold)] px-3 py-1.5 text-[13px] font-semibold text-[var(--mtv-on-gold)]">
                <LogIn className="h-3.5 w-3.5" /> Sign in
              </Link>
            </div>
          )}
        </Section>

        <Section title="Appearance">
          <div className="flex items-center justify-between gap-4">
            <p className="flex items-center gap-2 text-sm">
              {isDark ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
              {isDark ? "Dark" : "Light"}
            </p>
            <button type="button" onClick={toggleTheme} className={outline}>
              {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
              Switch to {isDark ? "light" : "dark"}
            </button>
          </div>
        </Section>

        <Section title="Your clips">
          <p className="text-sm text-white/55">Re-index an upload after a model change, or delete a clip.</p>
          {error && <p role="alert" className="text-sm text-[var(--mtv-red)]">{error}</p>}
          {loading && <p className="text-sm text-white/55">Loading…</p>}
          {!loading && videos.length === 0 && <p className="text-sm text-white/55">No clips yet.</p>}
          <ul className="divide-y divide-[var(--mtv-divider)]">
            {videos.map((video) => (
              <li key={video.video_id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <span className="truncate">{video.title}</span>
                    {video.publish_state && <PublishBadge state={video.publish_state} />}
                  </p>
                  <p className="text-xs text-white/50">
                    {STATUS_COPY[video.processing_status].label} · {formatDuration(video.duration_seconds)}
                    {video.game && <> · {video.game}</>}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button type="button" onClick={() => handleReindex(video)} disabled={busyId !== null} className={outline}>
                    {busyId === video.video_id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                    Re-index
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(video)}
                    disabled={busyId !== null}
                    className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-semibold text-[var(--mtv-red)] hover:bg-[var(--mtv-red)]/10 disabled:opacity-40"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </Section>

        <details className="group border-t border-[var(--mtv-divider)] pt-6">
          <summary className="flex cursor-pointer list-none items-center gap-2 font-mono text-[11px] uppercase tracking-[0.2em] text-[var(--mtv-text-2)]">
            For developers
            <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-4 space-y-4 text-xs text-white/60">
            {!config && <p>Backend unreachable.</p>}
            {config && (
              <>
                <DevRow label="Models">
                  <ul className="space-y-0.5 font-mono">
                    <li>visual + text embeddings: {config.models.embedder}</li>
                    <li>speech to text: {config.models.transcriber}</li>
                    <li>highlight detector: {config.models.highlights}</li>
                    <li>
                      AI creator pack:{" "}
                      {config.models.creator
                        ? [config.models.creator, ...config.models.creator_fallbacks].join(" → ")
                        : "off (no Gemini key)"}
                    </li>
                    <li>creator persona tools: {config.models.personas ?? "off"}</li>
                  </ul>
                </DevRow>
                <DevRow label="Search thresholds">
                  <p className="font-mono">
                    {Object.entries(config.search)
                      .map(([name, value]) => `${name} ${value}`)
                      .join(" · ")}
                  </p>
                </DevRow>
                <DevRow label="Match labels">
                  <p className="font-mono">
                    strong ≥ {BAND_STRONG} · moderate ≥ {BAND_MODERATE} · weak ≥ {BAND_WEAK}
                  </p>
                </DevRow>
                <DevRow label="Features and limits">
                  <p className="font-mono">
                    Gemini {config.features.gemini ? "on" : "off"} · YouTube posting {config.features.youtube ? "on" : "off"} ·
                    accounts {config.features.accounts ? "on" : "off"} · uploads up to {config.limits.max_video_minutes} min /{" "}
                    {(config.limits.max_upload_mb / 1024).toFixed(0)} GB
                  </p>
                </DevRow>
              </>
            )}
          </div>
        </details>
      </main>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4 border-t border-[var(--mtv-divider)] pt-6">
      <h2 className="font-mono text-[11px] uppercase tracking-[0.2em] text-[var(--mtv-text-2)]">{title}</h2>
      {children}
    </section>
  );
}

function DevRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 font-semibold uppercase tracking-wide text-white/40">{label}</p>
      {children}
    </div>
  );
}
