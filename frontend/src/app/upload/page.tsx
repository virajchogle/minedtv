"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";

import { FileUpload } from "@/components/file-upload";
import { SiteNav } from "@/components/hero/site-nav";
import { ScreenTitle } from "@/components/ui/screen-header";
import { STATUS_COPY, fetchVideo, uploadVideo, type ProcessingStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

type Phase = "idle" | "uploading" | "processing" | "complete" | "failed";

const STAGE_DETAIL: Partial<Record<ProcessingStatus, string>> = {
  pending: "Queued for processing.",
  extracting_frames: "Sampling frames with ffmpeg — scene changes plus one frame per second.",
  analyzing: "Gemini is transcribing the audio and describing each scene.",
  indexing: "Embedding the segments and writing them to the search index.",
};

const DOT_TONE: Record<Phase, string> = {
  idle: "bg-[var(--mtv-text-2)]",
  uploading: "bg-[var(--mtv-gold)] animate-pulse",
  processing: "bg-[var(--mtv-gold)] animate-pulse",
  complete: "bg-[var(--mtv-green)]",
  failed: "bg-[var(--mtv-red)]",
};

const PHASE_LABEL: Record<Phase, string> = {
  idle: "Ready to upload",
  uploading: "Uploading",
  processing: "Processing",
  complete: "Indexed and searchable",
  failed: "Something went wrong",
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
        if (video.searchable) {
          setPhase("complete");
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
      const result = await uploadVideo(selectedFile, setProgress);
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
    setResetKey((key) => key + 1);
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
                MP4 files up to 90 minutes. Indexing runs in the background.
              </p>
            )}
            {phase === "processing" && (
              <p className="text-[13px] text-[var(--mtv-text-2)]">
                {STAGE_DETAIL[status] ?? "Working…"}
              </p>
            )}
          </div>
        </MtvCard>

        {phase === "idle" && (
          <div className="space-y-4">
            <FileUpload key={resetKey} onFileSelect={setSelectedFile} />
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
            <div className="flex gap-3 pt-1">
              <PrimaryButton onClick={() => router.push(`/video/${videoId}`)}>
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
      </div>
    </div>
  );
}
