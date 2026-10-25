"use client";

/**
 * Everything you can do with a clip beyond watching it:
 *  - publish state (owner): private (My videos) → published on MinedTV, which
 *    also starts the virality check and the AI creator pack
 *  - post to YouTube (owner, published clips)
 *  - like (anyone acting as a user)
 *  - owner only: MP4 export for TikTok/Reels, the AI creator pack (titles,
 *    caption, hashtags, YouTube metadata) and the virality check
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
  ExternalLink,
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
  disconnectYouTube,
  getCreatorPack,
  getYouTubeConnectUrl,
  getYouTubeStatus,
  getYouTubeUploads,
  getExport,
  getVirality,
  postToYouTube,
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
  YouTubePrivacy,
  YouTubeStatusOut,
  YouTubeUploadOut,
} from "@/lib/minedtv-types";
import { cn } from "@/lib/utils";

const POLL_MS = 5000;

// ── shared bits ──────────────────────────────────────────────────────────────

const STATE_COPY: Record<PublishState, { label: string; tone: string; hint: string }> = {
  draft: {
    label: "Private",
    tone: "border-white/25 bg-white/10 text-white/80",
    hint: "In My videos: only you can see it. Publishing puts it on MinedTV and runs the virality check.",
  },
  // Legacy state from before publish-then-post; shown exactly like a private clip.
  ready: {
    label: "Private",
    tone: "border-white/25 bg-white/10 text-white/80",
    hint: "In My videos: only you can see it. Publishing puts it on MinedTV and runs the virality check.",
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
      const updated = await fn(video.video_id);
      // Publish responses are list-shaped; keep the detail page's counts.
      onChange({ ...updated, frame_count: video.frame_count, segment_count: video.segment_count });
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
        {state === "published" && (
          <ActionButton busy={busy === "draft"} onClick={() => act("draft", unpublishClip)}>
            <EyeOff className="h-3.5 w-3.5" /> Unpublish
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
        title={me ? undefined : "Sign in to like clips"}
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
    [video.video_id, video.start_ms, video.end_ms, video.publish_state]
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
    [video.video_id, video.start_ms, video.end_ms, video.publish_state, submitted.platform, submitted.target_audience, submitted.persona_count]
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
    <Panel icon={TrendingUp} title="Virality check" aside={<span className="text-[11px] text-[var(--mtv-text-2)]">runs on publish</span>}>
      <p className="text-xs text-[var(--mtv-text-2)]">
        A synthetic audience panel reacts to this clip. Publishing runs it for YouTube automatically; run it here
        for other platforms or audiences. It&apos;s a creative testing aid, not a forecast. Takes a few minutes.
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


const PRIVACY: { value: YouTubePrivacy; label: string }[] = [
  { value: "private", label: "Private" },
  { value: "unlisted", label: "Unlisted" },
  { value: "public", label: "Public" },
];

const UPLOAD_COPY: Record<YouTubeUploadOut["status"], string> = {
  queued: "Queued…",
  uploading: "Uploading to YouTube…",
  published: "Posted",
  failed: "Failed",
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Starts (or finds) the AI creator pack and waits for it, so the post gets its title and tags. */
async function ensureCreatorPack(clipId: string, onWaiting: () => void): Promise<void> {
  let pack = await getCreatorPack(clipId).catch(() => null);
  if (pack?.status === "ready") return;
  if (pack?.status !== "processing") pack = await startCreatorPack(clipId);
  onWaiting();
  const deadline = Date.now() + 4 * 60_000;
  while (pack?.status === "processing" && Date.now() < deadline) {
    await sleep(POLL_MS);
    pack = await getCreatorPack(clipId);
  }
  // A failed or slow pack isn't fatal: the post falls back to the clip's own title.
}

function YouTubeSection({ video }: { video: Video }) {
  const [status, setStatus] = useState<YouTubeStatusOut | null>(null);
  const [uploads, setUploads] = useState<YouTubeUploadOut[]>([]);
  const [privacy, setPrivacy] = useState<YouTubePrivacy>("private");
  const [phase, setPhase] = useState<"idle" | "connecting" | "writing" | "posting">("idle");
  const [error, setError] = useState<string | null>(null);
  const clipId = video.video_id;

  useEffect(() => {
    let cancelled = false;
    getYouTubeStatus().then((s) => !cancelled && setStatus(s), (e: Error) => !cancelled && setError(e.message));
    getYouTubeUploads(clipId).then((u) => !cancelled && setUploads(u), () => undefined);
    return () => {
      cancelled = true;
    };
  }, [clipId]);

  const latest = uploads[0] ?? null;
  const inFlight = latest?.status === "queued" || latest?.status === "uploading";
  useEffect(() => {
    if (!inFlight) return;
    const timer = setTimeout(() => {
      getYouTubeUploads(clipId).then(setUploads, () => undefined);
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [inFlight, uploads, clipId]);

  const connect = async () => {
    setPhase("connecting");
    setError(null);
    try {
      window.location.href = await getYouTubeConnectUrl();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the YouTube connection");
      setPhase("idle");
    }
  };

  const post = async () => {
    setError(null);
    try {
      await ensureCreatorPack(clipId, () => setPhase("writing"));
      setPhase("posting");
      const upload = await postToYouTube(clipId, { privacy });
      setUploads((list) => [upload, ...list.filter((u) => u.id !== upload.id)]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not post to YouTube");
    } finally {
      setPhase("idle");
    }
  };

  const disconnect = async () => {
    setError(null);
    try {
      await disconnectYouTube();
      setStatus((s) => s && { ...s, connected: false, channel_id: null, channel_title: null });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not disconnect");
    }
  };

  const postable = video.publish_state === "published";

  return (
    <Panel
      icon={Youtube}
      title="Post to YouTube"
      aside={
        status?.connected && (
          <button type="button" onClick={() => void disconnect()} className="text-[11px] text-[var(--mtv-text-2)] underline-offset-2 hover:underline">
            Disconnect {status.channel_title ?? "channel"}
          </button>
        )
      }
    >
      {!status && !error && <Loader2 className="h-4 w-4 animate-spin text-[var(--mtv-text-2)]" />}
      {status && !status.configured && (
        <p className="text-xs text-[var(--mtv-text-2)]">YouTube posting isn&apos;t set up on this server.</p>
      )}
      {status?.configured && !status.connected && (
        <>
          <p className="text-xs text-[var(--mtv-text-2)]">
            Connect your channel once; clips then upload straight from MinedTV.
          </p>
          <ActionButton variant="gold" busy={phase === "connecting"} onClick={() => void connect()}>
            <Youtube className="h-3.5 w-3.5" /> Connect YouTube
          </ActionButton>
        </>
      )}
      {status?.connected && (
        <>
          <p className="text-xs text-[var(--mtv-text-2)]">
            {postable
              ? "Uploads this clip with the title, description and tags from its AI creator pack (written first if it doesn't exist yet)."
              : "Publish it on MinedTV first."}{" "}
            Until Google approves the app, YouTube keeps uploads private.
          </p>
          {postable && (
            <div className="flex flex-wrap items-end gap-2">
              <label className="space-y-1 text-[11px] text-[var(--mtv-text-2)]">
                Visibility
                <select
                  value={privacy}
                  onChange={(e) => setPrivacy(e.target.value as YouTubePrivacy)}
                  className="block rounded-lg border border-[var(--mtv-divider)] bg-[var(--mtv-surface-high)] px-2 py-1.5 text-[13px] text-[var(--mtv-text)]"
                >
                  {PRIVACY.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
              <ActionButton variant="gold" busy={phase !== "idle" || inFlight} onClick={() => void post()}>
                <Youtube className="h-3.5 w-3.5" />
                {phase === "writing"
                  ? "Writing title and tags…"
                  : phase === "posting"
                    ? "Starting upload…"
                    : latest?.status === "published"
                      ? "Post again"
                      : "Post to YouTube"}
              </ActionButton>
            </div>
          )}
        </>
      )}
      {latest && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-[var(--mtv-surface-high)] px-2.5 py-1.5 text-[13px]">
          {inFlight && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          <span className={cn("font-semibold", latest.status === "published" && "text-[var(--mtv-green)]", latest.status === "failed" && "text-[var(--mtv-red)]")}>
            {UPLOAD_COPY[latest.status]}
          </span>
          <span className="min-w-0 flex-1 truncate text-[var(--mtv-text-2)]">
            “{latest.title}” · {latest.privacy}
          </span>
          {latest.url && (
            <a href={latest.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[var(--mtv-gold)] underline-offset-2 hover:underline">
              Open on YouTube <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      )}
      {latest?.status === "failed" && <ErrorLine message={latest.error} />}
      <ErrorLine message={error} />
    </Panel>
  );
}

// ── the panel ────────────────────────────────────────────────────────────────

export function ClipActions({ video, onChange }: { video: Video; onChange: (v: Video) => void }) {
  const me = useCurrentUser();
  if (video.kind !== "clip") return null;
  const isOwner = Boolean(me && video.owner_id === me.id);

  return (
    <div className="space-y-4">
      <LikeButton video={video} onChange={onChange} />
      {!me && <ChooseUserNotice action="like clips, or use the AI tools on your own" />}
      {isOwner && <PublishSection video={video} onChange={onChange} />}
      {isOwner && video.publish_state === "published" && <YouTubeSection video={video} />}
      {isOwner && (
        <div className="grid gap-4 lg:grid-cols-2">
          <ExportSection video={video} />
          <CreatorPackSection video={video} />
        </div>
      )}
      {isOwner && <ViralitySection video={video} />}
    </div>
  );
}
