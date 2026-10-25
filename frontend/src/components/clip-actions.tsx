"use client";

/**
 * Everything you can do with a clip beyond watching it:
 *  - publish state (owner): draft → ready to post to YouTube → published
 *  - like (anyone acting as a user)
 *  - MP4 export for TikTok/Reels
 *  - AI creator pack (titles, caption, hashtags, YouTube metadata)
 *  - virality check (owner, unpublished clips only)
 *
 * The last three are background jobs on the backend: start with POST, then
 * poll GET until `ready`. Existing results are loaded on mount.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  Copy,
  Download,
  Eye,
  EyeOff,
  Heart,
  Loader2,
  Rocket,
  Sparkles,
  TrendingUp,
  Youtube,
} from "lucide-react";

import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import {
  getCreatorPack,
  getExport,
  getVirality,
  markClipReady,
  publishClip,
  setLiked,
  startCreatorPack,
  startExport,
  startVirality,
  unpublishClip,
  type PublishState,
  type Video,
  type ViralityOptions,
} from "@/lib/api";
import type {
  ClipCreatorPackOut,
  ClipViralityOut,
  CreatorPlatform,
  ExportOut,
  JobStatus,
} from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

const POLL_MS = 5000;

// ── shared bits ──────────────────────────────────────────────────────────────

const STATE_COPY: Record<PublishState, { label: string; tone: string; hint: string }> = {
  draft: {
    label: "Draft",
    tone: "border-white/25 bg-white/10 text-white/80",
    hint: "Only you can see this clip.",
  },
  ready: {
    label: "Ready to post",
    tone: "border-[var(--mtv-gold)]/40 bg-[var(--mtv-gold)]/15 text-[var(--mtv-gold)]",
    hint: "Queued to post to YouTube. Still private until published.",
  },
  published: {
    label: "Published",
    tone: "border-[var(--mtv-green)]/40 bg-[var(--mtv-green)]/15 text-[var(--mtv-green)]",
    hint: "Visible in the feed, search and your profile.",
  },
};

export function PublishBadge({ state, className }: { state: PublishState; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold",
        STATE_COPY[state].tone,
        className
      )}
    >
      {STATE_COPY[state].label}
    </span>
  );
}

function Panel({
  icon: Icon,
  title,
  children,
  aside,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <section className="space-y-3 rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Icon className="h-4 w-4 text-[var(--mtv-gold)]" />
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function ActionButton({
  busy,
  children,
  variant = "outline",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; variant?: "gold" | "outline" }) {
  return (
    <button
      type="button"
      {...props}
      disabled={busy || props.disabled}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-semibold transition-opacity disabled:opacity-40",
        variant === "gold"
          ? "bg-[var(--mtv-gold)] text-[var(--mtv-on-gold)] hover:opacity-90"
          : "border border-[var(--mtv-divider)] hover:bg-[var(--mtv-surface-high)]",
        props.className
      )}
    >
      {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

function ErrorLine({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="flex items-start gap-1.5 text-xs text-[var(--mtv-red)]">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      {message}
    </p>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="shrink-0 rounded p-1 text-[var(--mtv-text-2)] hover:bg-[var(--mtv-surface-high)] hover:text-[var(--mtv-text)]"
      aria-label="Copy"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

/**
 * A backend job (export / creator pack / virality): loads the current state,
 * starts it on demand and polls while it's processing.
 */
function useJob<T extends { status: JobStatus; error: string | null }>(
  get: () => Promise<T>,
  start: () => Promise<T>,
  deps: unknown[]
) {
  const [state, setState] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const getRef = useRef(get);
  useEffect(() => {
    getRef.current = get;
  });

  // Load whatever exists for these inputs (a finished result, or a job in progress).
  useEffect(() => {
    let cancelled = false;
    getRef.current().then(
      (s) => !cancelled && (setState(s), setError(null)),
      () => !cancelled && setState(null) // not started yet, or not allowed; "start" reports real errors
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // Poll while the backend says it's working.
  const processing = state?.status === "processing";
  useEffect(() => {
    if (!processing) return;
    const timer = setTimeout(() => {
      getRef.current().then(setState, (e: unknown) =>
        setError(e instanceof Error ? e.message : "Could not check progress")
      );
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [processing, state]);

  const run = async () => {
    setStarting(true);
    setError(null);
    try {
      setState(await start());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setStarting(false);
    }
  };

  const jobError = error ?? (state?.status === "failed" ? state.error ?? "The job failed" : null);
  return { state, run, starting, error: jobError, busy: starting || processing };
}

// ── sections ─────────────────────────────────────────────────────────────────

function PublishSection({ video, onChange }: { video: Video; onChange: (v: Video) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const state = video.publish_state ?? "published";

  const act = async (name: string, fn: (id: string) => Promise<Video>) => {
    setBusy(name);
    setError(null);
    try {
      onChange(await fn(video.video_id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the clip");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Panel icon={Rocket} title="Publishing" aside={<PublishBadge state={state} />}>
      <p className="text-xs text-[var(--mtv-text-2)]">{STATE_COPY[state].hint}</p>
      <div className="flex flex-wrap gap-2">
        {state !== "published" && (
          <ActionButton variant="gold" busy={busy === "publish"} onClick={() => act("publish", publishClip)}>
            <Eye className="h-3.5 w-3.5" /> Publish
          </ActionButton>
        )}
        {state === "draft" && (
          <ActionButton busy={busy === "ready"} onClick={() => act("ready", markClipReady)}>
            <Youtube className="h-3.5 w-3.5" /> Mark ready to post
          </ActionButton>
        )}
        {state !== "draft" && (
          <ActionButton busy={busy === "draft"} onClick={() => act("draft", unpublishClip)}>
            <EyeOff className="h-3.5 w-3.5" /> {state === "published" ? "Unpublish" : "Back to draft"}
          </ActionButton>
        )}
      </div>
      <ErrorLine message={error} />
    </Panel>
  );
}

function LikeButton({ video, onChange }: { video: Video; onChange: (v: Video) => void }) {
  const me = useCurrentUser();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      const counts = await setLiked(video.video_id, !video.liked_by_me);
      onChange({
        ...video,
        like_count: counts.like_count,
        view_count: counts.view_count,
        liked_by_me: Boolean(counts.liked_by_me),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update like");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={() => void toggle()}
        disabled={!me || busy}
        title={me ? undefined : "Choose a user to like clips"}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[13px] font-semibold transition-colors disabled:opacity-50",
          video.liked_by_me
            ? "border-[var(--mtv-red)]/50 bg-[var(--mtv-red)]/15 text-[var(--mtv-red)]"
            : "border-[var(--mtv-divider)] hover:bg-[var(--mtv-surface-high)]"
        )}
      >
        <Heart className={cn("h-3.5 w-3.5", video.liked_by_me && "fill-current")} />
        {video.like_count.toLocaleString()}
      </button>
      <span className="inline-flex items-center gap-1 text-xs text-[var(--mtv-text-2)]">
        <Eye className="h-3.5 w-3.5" /> {video.view_count.toLocaleString()} views
      </span>
      <ErrorLine message={error} />
    </div>
  );
}

function ExportSection({ video }: { video: Video }) {
  const job = useJob<ExportOut>(
    () => getExport(video.video_id),
    () => startExport(video.video_id),
    [video.video_id, video.start_ms, video.end_ms]
  );
  return (
    <Panel icon={Download} title="MP4 for TikTok / Reels">
      <p className="text-xs text-[var(--mtv-text-2)]">
        Renders exactly this clip as an MP4 file. Usually ready in about a minute.
      </p>
      {job.state?.status === "ready" && job.state.url ? (
        <a
          href={job.state.url}
          download
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--mtv-gold)] px-3 py-1.5 text-[13px] font-semibold text-[var(--mtv-on-gold)]"
        >
          <Download className="h-3.5 w-3.5" /> Download MP4
        </a>
      ) : (
        <ActionButton variant="gold" busy={job.busy} onClick={() => void job.run()}>
          {job.busy ? "Rendering…" : "Export MP4"}
        </ActionButton>
      )}
      <ErrorLine message={job.error} />
    </Panel>
  );
}

function CopyRow({ label, text }: { label: string; text: string }) {
  if (!text) return null;
  return (
    <div className="space-y-0.5">
      <p className="text-[11px] uppercase tracking-wider text-[var(--mtv-text-2)]">{label}</p>
      <div className="flex items-start gap-2 rounded-lg bg-[var(--mtv-surface-high)] px-2.5 py-1.5 text-[13px]">
        <p className="flex-1 whitespace-pre-wrap">{text}</p>
        <CopyButton text={text} />
      </div>
    </div>
  );
}

function CreatorPackSection({ video }: { video: Video }) {
  const job = useJob<ClipCreatorPackOut>(
    () => getCreatorPack(video.video_id),
    () => startCreatorPack(video.video_id),
    [video.video_id, video.start_ms, video.end_ms]
  );
  const pack = job.state?.status === "ready" ? job.state.pack : null;
  return (
    <Panel
      icon={Sparkles}
      title="AI creator pack"
      aside={job.state?.model && <span className="text-[11px] text-[var(--mtv-text-2)]">{job.state.model}</span>}
    >
      {!pack && (
        <>
          <p className="text-xs text-[var(--mtv-text-2)]">
            Gemini watches the clip and writes titles, a caption, hashtags and ready-to-paste YouTube
            metadata. Takes a minute or two.
          </p>
          <ActionButton variant="gold" busy={job.busy} onClick={() => void job.run()}>
            {job.busy ? "Writing…" : "Generate"}
          </ActionButton>
        </>
      )}
      {pack && (
        <div className="space-y-3">
          <div className="space-y-1">
            <p className="text-[11px] uppercase tracking-wider text-[var(--mtv-text-2)]">Title ideas</p>
            {pack.title_options.map((t) => (
              <div key={t} className="flex items-center gap-2 text-[13px]">
                <span className="flex-1">{t}</span>
                <CopyButton text={t} />
              </div>
            ))}
          </div>
          <CopyRow label="Caption" text={pack.caption} />
          <CopyRow label="Hashtags" text={pack.hashtags.map((h) => `#${h.replace(/^#/, "")}`).join(" ")} />
          <CopyRow label="YouTube title" text={pack.youtube.title} />
          <CopyRow label="YouTube description" text={pack.youtube.description} />
          <CopyRow label="YouTube tags" text={pack.youtube.tags.join(", ")} />
          {pack.key_moments.length > 0 && (
            <div className="space-y-1">
              <p className="text-[11px] uppercase tracking-wider text-[var(--mtv-text-2)]">Key moments</p>
              {pack.key_moments.map((m) => (
                <p key={`${m.timestamp}-${m.label}`} className="text-[13px]">
                  <span className="font-mono text-[var(--mtv-gold)]">{m.timestamp}</span> {m.label}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
      <ErrorLine message={job.error} />
    </Panel>
  );
}

const PLATFORMS: CreatorPlatform[] = ["youtube", "tiktok", "instagram", "reddit", "general"];

const VERDICT_TONE: Record<string, string> = {
  strong: "text-[var(--mtv-green)]",
  promising: "text-[var(--mtv-gold)]",
  mixed: "text-white/80",
  weak: "text-[var(--mtv-red)]",
};

function ViralitySection({ video }: { video: Video }) {
  const [options, setOptions] = useState<ViralityOptions>({ platform: "youtube", target_audience: "", persona_count: 9 });
  const [submitted, setSubmitted] = useState<ViralityOptions>(options);
  const job = useJob<ClipViralityOut>(
    () => getVirality(video.video_id, submitted),
    () => startVirality(video.video_id, submitted),
    [video.video_id, video.start_ms, video.end_ms, submitted.platform, submitted.target_audience, submitted.persona_count]
  );
  const result = job.state?.status === "ready" ? job.state.result : null;

  // Changing the options switches to their own result; "Run check" then starts it.
  const startAfterSwitch = useRef(false);
  const runJob = job.run;
  useEffect(() => {
    if (startAfterSwitch.current) {
      startAfterSwitch.current = false;
      void runJob();
    }
  }, [submitted, runJob]);

  const onRun = () => {
    const next = { ...options, target_audience: options.target_audience?.trim() || null };
    if (JSON.stringify(next) === JSON.stringify(submitted)) void job.run();
    else {
      startAfterSwitch.current = true;
      setSubmitted(next);
    }
  };

  return (
    <Panel icon={TrendingUp} title="Virality check" aside={<span className="text-[11px] text-[var(--mtv-text-2)]">drafts only</span>}>
      <p className="text-xs text-[var(--mtv-text-2)]">
        A synthetic audience panel reacts to this clip before you publish it. It&apos;s a creative testing aid,
        not a forecast. Takes a few minutes.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="space-y-1 text-[11px] text-[var(--mtv-text-2)]">
          Platform
          <select
            value={options.platform}
            onChange={(e) => setOptions({ ...options, platform: e.target.value as CreatorPlatform })}
            className="block rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface-high)] px-2 py-1.5 text-[13px] text-[var(--mtv-text)]"
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-[12rem] flex-1 space-y-1 text-[11px] text-[var(--mtv-text-2)]">
          Target audience (optional)
          <input
            value={options.target_audience ?? ""}
            onChange={(e) => setOptions({ ...options, target_audience: e.target.value })}
            placeholder="e.g. competitive Valorant players"
            className="block w-full rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface-high)] px-2 py-1.5 text-[13px] text-[var(--mtv-text)]"
          />
        </label>
        <label className="space-y-1 text-[11px] text-[var(--mtv-text-2)]">
          Personas
          <input
            type="number"
            min={3}
            max={15}
            value={options.persona_count ?? 9}
            onChange={(e) => setOptions({ ...options, persona_count: Number(e.target.value) || 9 })}
            className="block w-16 rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface-high)] px-2 py-1.5 text-[13px] text-[var(--mtv-text)]"
          />
        </label>
        <ActionButton variant="gold" busy={job.busy} onClick={onRun}>
          {job.busy ? "Simulating…" : "Run check"}
        </ActionButton>
      </div>

      {result && (
        <div className="space-y-3 pt-1">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="text-3xl font-bold">{Math.round(result.virality_score)}</span>
            <span className={cn("text-sm font-semibold capitalize", VERDICT_TONE[result.verdict])}>{result.verdict}</span>
            <span className="text-xs text-[var(--mtv-text-2)]">
              {result.inferred_niche} · reaches {result.cascade_depth.replace("_", " ")}
            </span>
          </div>
          <p className="text-[13px]">{result.cascade_summary}</p>
          <div className="grid grid-cols-3 gap-2 text-center text-[11px] text-[var(--mtv-text-2)] sm:grid-cols-6">
            {(
              [
                ["Watch", result.metrics.simulated_watch_rate],
                ["Complete", result.metrics.simulated_completion_rate],
                ["Like", result.metrics.simulated_like_rate],
                ["Comment", result.metrics.simulated_comment_rate],
                ["Save", result.metrics.simulated_save_rate],
                ["Share", result.metrics.simulated_share_rate],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="rounded-lg bg-[var(--mtv-surface-high)] py-1.5">
                <p className="text-sm font-semibold text-[var(--mtv-text)]">{Math.round(value)}%</p>
                {label}
              </div>
            ))}
          </div>
          {(
            [
              ["What works", result.consensus_strengths],
              ["Risks", result.consensus_risks],
              ["Try changing", result.recommended_changes],
            ] as const
          ).map(([label, items]) =>
            items.length > 0 ? (
              <div key={label} className="space-y-0.5">
                <p className="text-[11px] uppercase tracking-wider text-[var(--mtv-text-2)]">{label}</p>
                <ul className="list-disc space-y-0.5 pl-5 text-[13px]">
                  {items.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null
          )}
          <details className="text-[13px]">
            <summary className="cursor-pointer text-xs text-[var(--mtv-text-2)]">
              {result.persona_reviews.length} persona reactions
            </summary>
            <div className="mt-2 space-y-2">
              {result.persona_reviews.map((p) => (
                <div key={p.name} className="rounded-lg bg-[var(--mtv-surface-high)] p-2">
                  <p className="font-semibold">
                    {p.name} <span className="font-normal text-[var(--mtv-text-2)]">· {p.layer} · hook {p.hook_score}</span>
                  </p>
                  <p className="text-xs text-[var(--mtv-text-2)]">{p.profile}</p>
                </div>
              ))}
            </div>
          </details>
          <p className="text-[11px] text-[var(--mtv-text-2)]">{result.disclaimer}</p>
        </div>
      )}
      <ErrorLine message={job.error} />
    </Panel>
  );
}

// ── the panel ────────────────────────────────────────────────────────────────

export function ClipActions({ video, onChange }: { video: Video; onChange: (v: Video) => void }) {
  const me = useCurrentUser();
  if (video.kind !== "clip") return null;
  const isOwner = Boolean(me && video.owner_id === me.id);
  const unpublished = video.publish_state !== "published";

  return (
    <div className="space-y-4">
      <LikeButton video={video} onChange={onChange} />
      {!me && <ChooseUserNotice action="like, publish and run AI tools on clips" />}
      {isOwner && <PublishSection video={video} onChange={onChange} />}
      <div className="grid gap-4 lg:grid-cols-2">
        <ExportSection video={video} />
        <CreatorPackSection video={video} />
      </div>
      {isOwner && unpublished && <ViralitySection video={video} />}
      {isOwner && !unpublished && (
        <p className="text-xs text-[var(--mtv-text-2)]">
          Virality checks run on unpublished clips. Unpublish this clip to test it with the audience panel.
        </p>
      )}
    </div>
  );
}
