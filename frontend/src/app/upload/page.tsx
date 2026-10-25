"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, Eye, Loader2, ShieldAlert, XCircle } from "lucide-react";

import { PublishBadge } from "@/components/clip-actions";
import { ChooseUserNotice, useCurrentUser } from "@/components/current-user";
import { FileUpload } from "@/components/file-upload";
import { SiteNav } from "@/components/hero/site-nav";
import { ScreenTitle } from "@/components/ui/screen-header";
import {
  STATUS_COPY,
  fetchClipsForSession,
  fetchVideo,
  publishClip,
  uploadVideo,
  type ProcessingStatus,
  type Video,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Phase = "idle" | "uploading" | "processing" | "complete" | "failed" | "blocked";

const STAGE_DETAIL: Partial<Record<ProcessingStatus, string>> = {
  pending: "Queued — the worker picks uploads up within about a minute.",
  extracting_frames: "Transcoding to 720p and cutting 2-second streaming segments.",
  analyzing: "Whisper is transcribing voice chat; highlights are being detected.",
  indexing: "Embedding one frame per second with CLIP and writing the search index.",
};

const DOT_TONE: Record<Phase, string> = {
  idle: "bg-[var(--mtv-text-2)]",
  uploading: "bg-[var(--mtv-gold)] animate-pulse",
  processing: "bg-[var(--mtv-gold)] animate-pulse",
  complete: "bg-[var(--mtv-green)]",
  failed: "bg-[var(--mtv-red)]",
  blocked: "bg-[var(--mtv-red)]",
};

const PHASE_LABEL: Record<Phase, string> = {
  idle: "Ready to upload",
  uploading: "Uploading",
  processing: "Processing",
  complete: "Indexed and searchable",
  failed: "Something went wrong",
  blocked: "Upload blocked",
};

function PrimaryButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const { className, ...rest } = props;
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-[52px] items-center justify-center gap-2 rounded-[14px] bg-[var(--mtv-gold)] px-5 text-[15px] font-bold text-[var(--mtv-on-gold)] transition-opacity hover:opacity-90 disabled:opacity-40",
        className
      )}
      {...rest}
    />
  );
}

function OutlineButton({
  href,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { href?: string }) {
  const { className, children, ...rest } = props;
  const cls = cn(
    "inline-flex h-[52px] items-center justify-center gap-2 rounded-[14px] border border-[var(--mtv-divider)] px-5 text-[15px] font-semibold text-[var(--mtv-text)] transition-colors hover:bg-[var(--mtv-surface-high)]",
    className
  );
  if (href) {
    return (
      <Link href={href} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button type="button" className={cls} {...rest}>
      {children}
    </button>
  );
}

function MtvCard({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] p-5",
        className
      )}
    >
      {children}
    </div>
  );
}

export default function UploadPage() {
  const router = useRouter();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [videoId, setVideoId] = useState<string | null>(null);
  const [status, setStatus] = useState<ProcessingStatus>("pending");
  const [error, setError] = useState<string | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const [title, setTitle] = useState("");
  const [game, setGame] = useState("");
  const [clips, setClips] = useState<Video[]>([]);
  const [acting, setActing] = useState<string | null>(null);
  const [ageRestricted, setAgeRestricted] = useState(false);
  const [moderationReason, setModerationReason] = useState<string | null>(null);
  const me = useCurrentUser();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  useEffect(() => stopPolling, []);

  const startPolling = (id: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const video = await fetchVideo(id);
        setStatus(video.processing_status);
        setAgeRestricted(video.age_restricted);
        setModerationReason(video.moderation_reason);
        if (video.searchable) {
          setPhase("complete");
          stopPolling();
          // The pipeline made one or more draft clips for this upload.
          fetchClipsForSession(id).then(setClips).catch(() => setClips([]));
        } else if (video.processing_status === "blocked") {
          setPhase("blocked");
          setError(video.moderation_reason ?? "This video violates our community guidelines.");
          stopPolling();
        } else if (video.processing_status === "failed") {
          setPhase("failed");
          setError(
            video.processing_error ??
              "Processing failed. The file may be corrupt or in an unsupported format."
          );
          stopPolling();
        }
      } catch {
        // Transient network errors are expected while the backend is busy.
      }
    }, 3000);
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setPhase("uploading");
    setProgress(0);
    setError(null);
    try {
      const result = await uploadVideo(selectedFile, setProgress, { title, game });
      setVideoId(result.video_id);
      setPhase("processing");
      startPolling(result.video_id);
    } catch (caught) {
      setPhase("failed");
      setError(caught instanceof Error ? caught.message : "Upload failed.");
    }
  };

  const reset = () => {
    stopPolling();
    setSelectedFile(null);
    setPhase("idle");
    setProgress(0);
    setVideoId(null);
    setStatus("pending");
    setError(null);
    setClips([]);
    setTitle("");
    setGame("");
    setAgeRestricted(false);
    setModerationReason(null);
    setResetKey((key) => key + 1);
  };

  const updateClip = async (clip: Video) => {
    setActing(`${clip.video_id}:publish`);
    try {
      const updated = await publishClip(clip.video_id);
      setClips((list) => list.map((c) => (c.video_id === updated.video_id ? updated : c)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the clip");
    } finally {
      setActing(null);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--mtv-bg)] px-4 pb-16 pt-28 text-[var(--mtv-text)] sm:px-8 sm:pt-32">
      <SiteNav />
      <div className="mx-auto max-w-2xl space-y-6">
        <ScreenTitle>Upload</ScreenTitle>

        {/* ── status card — always visible, mirrors the spec's Clipper status card ── */}
        <MtvCard className="flex items-center gap-3">
          <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", DOT_TONE[phase])} />
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-semibold">{PHASE_LABEL[phase]}</p>
            {phase === "idle" && (
              <p className="text-[13px] text-[var(--mtv-text-2)]">
                MP4, MOV, MKV or WebM, up to 90 minutes and 4 GB. Indexing runs in the background.
              </p>
            )}
            {phase === "processing" && (
              <p className="text-[13px] text-[var(--mtv-text-2)]">
                {STAGE_DETAIL[status] ?? "Working…"}
              </p>
            )}
          </div>
        </MtvCard>

        {phase === "idle" && !me && <ChooseUserNotice action="upload clips" />}

        {phase === "idle" && me && (
          <div className="space-y-4">
            <FileUpload key={resetKey} onFileSelect={setSelectedFile} />
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-[13px] text-[var(--mtv-text-2)]">
                Title
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={selectedFile?.name.replace(/\.[^.]+$/, "") ?? "Ranked on Bind"}
                  className="block w-full rounded-xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] px-3 py-2.5 text-[15px] text-[var(--mtv-text)]"
                />
              </label>
              <label className="space-y-1 text-[13px] text-[var(--mtv-text-2)]">
                Game
                <input
                  value={game}
                  onChange={(e) => setGame(e.target.value)}
                  placeholder="Valorant, CS2, Fortnite…"
                  list="minedtv-games"
                  className="block w-full rounded-xl border border-[var(--mtv-divider)] bg-[var(--mtv-surface)] px-3 py-2.5 text-[15px] text-[var(--mtv-text)]"
                />
                <datalist id="minedtv-games">
                  {["Valorant", "CS2", "Fortnite", "Apex Legends", "Minecraft", "Rocket League", "Overwatch 2", "Call of Duty", "GTA V", "Rainbow Six Siege", "Marvel Rivals", "Roblox"].map((g) => (
                    <option key={g} value={g} />
                  ))}
                </datalist>
              </label>
            </div>
            <p className="text-xs text-[var(--mtv-text-2)]">
              Uploading as <span className="font-semibold text-[var(--mtv-text)]">@{me.username}</span>. New clips
              land in My videos (private) first. Publish one to put it on MinedTV; that also runs the virality check.
            </p>
            <div className="flex justify-end gap-3">
              <OutlineButton href="/library">Cancel</OutlineButton>
              <PrimaryButton onClick={handleUpload} disabled={!selectedFile}>
                Upload and index
              </PrimaryButton>
            </div>
          </div>
        )}

        {phase === "uploading" && (
          <MtvCard className="space-y-4">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-[var(--mtv-gold)]" />
              <span className="truncate font-medium">Uploading {selectedFile?.name}…</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--mtv-surface-high)]">
              <div
                className="h-2 rounded-full bg-[var(--mtv-gold)] transition-all duration-200"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-sm text-[var(--mtv-text-2)]">
              {progress}% — keep this tab open until the upload finishes.
            </p>
          </MtvCard>
        )}

        {phase === "processing" && (
          <MtvCard className="space-y-3">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-[var(--mtv-gold)]" />
              <span className="font-medium">{STATUS_COPY[status].label}</span>
            </div>
            <p className="text-sm text-[var(--mtv-text-2)]">{STAGE_DETAIL[status] ?? "Working…"}</p>
            <p className="font-mono text-xs text-[var(--mtv-text-2)]/70">{videoId}</p>
          </MtvCard>
        )}

        {phase === "complete" && videoId && (
          <MtvCard className="space-y-4">
            <div className="flex items-center gap-3 text-[var(--mtv-green)]">
              <CheckCircle2 className="h-6 w-6 shrink-0" />
              <span className="text-lg font-semibold">Indexed and searchable</span>
            </div>
            {status === "visual_only" && (
              <p className="text-sm text-amber-300">
                Gemini analysis was unavailable, so this video is indexed by appearance only.
                Transcript search will work after a re-index.
              </p>
            )}
            {ageRestricted && (
              <div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <p className="font-semibold">Marked 18+</p>
                  <p className="text-amber-200/80">
                    {moderationReason ?? "The transcript contains language that isn't suitable for all audiences."}
                  </p>
                </div>
              </div>
            )}
            {clips.length > 0 && (
              <div className="space-y-2">
                <p className="text-sm text-[var(--mtv-text-2)]">
                  {clips.length === 1 ? "Your clip is" : `${clips.length} clips are`} ready, in My videos. Only you can see
                  them until you publish.
                </p>
                {clips.map((clip) => (
                  <div
                    key={clip.video_id}
                    className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--mtv-divider)] p-3"
                  >
                    <span className="min-w-0 flex-1 truncate text-sm font-semibold">{clip.title}</span>
                    {clip.publish_state && <PublishBadge state={clip.publish_state} />}
                    {clip.publish_state !== "published" && (
                      <button
                        type="button"
                        onClick={() => void updateClip(clip)}
                        disabled={acting !== null}
                        className="inline-flex items-center gap-1 rounded-lg bg-[var(--mtv-gold)] px-2.5 py-1 text-xs font-bold text-[var(--mtv-on-gold)] disabled:opacity-40"
                      >
                        {acting === `${clip.video_id}:publish` ? <Loader2 className="h-3 w-3 animate-spin" /> : <Eye className="h-3 w-3" />}
                        Publish
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => router.push(`/video/${clip.video_id}`)}
                      className="rounded-lg border border-[var(--mtv-divider)] px-2.5 py-1 text-xs font-semibold"
                    >
                      Open
                    </button>
                  </div>
                ))}
                {error && <p className="text-xs text-[var(--mtv-red)]">{error}</p>}
              </div>
            )}
            <div className="flex gap-3 pt-1">
              <PrimaryButton onClick={() => router.push(`/video/${clips[0]?.video_id ?? videoId}`)}>
                Open and search it
              </PrimaryButton>
              <OutlineButton onClick={reset}>Upload another</OutlineButton>
            </div>
          </MtvCard>
        )}

        {phase === "failed" && (
          <MtvCard className="space-y-4">
            <div className="flex items-center gap-3 text-[var(--mtv-red)]">
              <XCircle className="h-6 w-6 shrink-0" />
              <span className="text-lg font-semibold">Something went wrong</span>
            </div>
            {error && <p className="text-sm text-[var(--mtv-red)]/90">{error}</p>}
            <OutlineButton onClick={reset}>Try again</OutlineButton>
          </MtvCard>
        )}

        {phase === "blocked" && (
          <MtvCard className="space-y-4">
            <div className="flex items-center gap-3 text-[var(--mtv-red)]">
              <ShieldAlert className="h-6 w-6 shrink-0" />
              <span className="text-lg font-semibold">This video can&apos;t be posted</span>
            </div>
            <p className="text-sm text-[var(--mtv-red)]/90">
              {moderationReason ?? "The transcript violates our community guidelines."}
            </p>
            <p className="text-xs text-[var(--mtv-text-2)]">
              Nothing from this upload is public or searchable. Remove the flagged content and
              try again with a different clip.
            </p>
            <OutlineButton onClick={reset}>Try a different clip</OutlineButton>
          </MtvCard>
        )}
      </div>
    </div>
  );
}
