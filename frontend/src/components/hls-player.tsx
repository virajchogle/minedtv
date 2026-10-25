"use client";

/**
 * Video element that can play the API's HLS manifests.
 *
 * Safari plays m3u8 natively; everywhere else needs Media Source Extensions,
 * which hls.js provides. hls.js is imported lazily so it stays out of the
 * initial bundle and never runs during server rendering.
 *
 * Seeking is deferred until the media knows its duration, otherwise
 * `currentTime` is silently dropped.
 */

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

export interface HlsPlayerHandle {
  /** Seek and attempt playback. Safe to call before the manifest has loaded. */
  seekTo: (seconds: number) => void;
  readonly element: HTMLVideoElement | null;
}

interface HlsPlayerProps {
  src: string;
  poster?: string | null;
  initialSeek?: number;
  className?: string;
  onError?: (message: string) => void;
}

export const HlsPlayer = forwardRef<HlsPlayerHandle, HlsPlayerProps>(function HlsPlayer(
  { src, poster, initialSeek = 0, className, onError },
  ref
) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);
  // Seek target parked until metadata arrives.
  const pending = useRef<number | null>(initialSeek > 0 ? initialSeek : null);

  useImperativeHandle(
    ref,
    () => ({
      seekTo(seconds: number) {
        const video = videoRef.current;
        if (!video || video.readyState < 1) {
          pending.current = seconds;
          return;
        }
        video.currentTime = seconds;
        void video.play().catch(() => {
          /* autoplay may be blocked; the controls still work */
        });
      },
      get element() {
        return videoRef.current;
      },
    }),
    []
  );

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src) return;

    setReady(false);

    let destroyed = false;
    let instance: { destroy: () => void } | null = null;

    void (async () => {
      const { default: Hls } = await import("hls.js");
      if (destroyed) return;

      // Prefer hls.js wherever Media Source Extensions exist. Recent Chrome answers "maybe"
      // to canPlayType("application/vnd.apple.mpegurl") yet can't play these streams
      // natively, so checking native support first left the player with no source.
      if (!Hls.isSupported()) {
        // iOS Safari has no MSE but plays HLS natively.
        if (video.canPlayType("application/vnd.apple.mpegurl")) {
          video.src = src;
        } else {
          onError?.("This browser cannot play HLS streams.");
        }
        return;
      }

      const hls = new Hls({ enableWorker: true, lowLatencyMode: false });
      instance = hls;
      hls.on(Hls.Events.ERROR, (_event, data) => {
        // Only fatal errors are worth surfacing; hls.js recovers from the rest.
        if (data.fatal) onError?.(`Playback failed: ${data.details}`);
      });
      hls.loadSource(src);
      hls.attachMedia(video);
    })();

    return () => {
      destroyed = true;
      instance?.destroy();
    };
  }, [src, onError]);

  const handleLoadedMetadata = () => {
    setReady(true);
    const video = videoRef.current;
    if (video && pending.current !== null) {
      video.currentTime = pending.current;
      pending.current = null;
    }
  };

  return (
    <video
      ref={videoRef}
      poster={poster ?? undefined}
      controls
      playsInline
      preload="metadata"
      onLoadedMetadata={handleLoadedMetadata}
      data-ready={ready}
      className={className}
    >
      Your browser cannot play this video.
    </video>
  );
});
