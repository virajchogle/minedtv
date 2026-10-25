"use client";

/**
 * MinecraftSunriseHero — a scroll-scrubbed sunrise with a cinematic wordmark
 * reveal.
 *
 * Architecture: a tall wrapper provides the scroll distance and a `sticky`
 * child pins the viewport-sized scene inside it. Scroll position is read with
 * `useScroll`, never intercepted. The page therefore scrolls normally in both
 * directions, keyboard paging works, touch momentum works, and nothing is ever
 * locked — there is no wheel handler and no `body` lock anywhere in here.
 *
 * What the sunrise actually is: layered colour, gradient lighting, a rising
 * sun glow and atmospheric haze composited over a still backdrop, plus a slow
 * push-in. It is a lighting treatment of a static scene, not a real
 * time-of-day simulation and not moving gameplay.
 *
 * Backdrop selection, in order of preference:
 *   1. `videoSrc` — scrubbed by scroll, giving a genuinely animated sunrise.
 *   2. `imageSrc` — a still landscape.
 *   3. A procedural voxel landscape, used when neither is usable.
 *
 * Only the SVG fallback currently provides true foreground overlap, because
 * its silhouette is real geometry. For a photographic backdrop, see the
 * `foregroundSrc` prop.
 */

import { useEffect, useRef, useState } from "react";
import {
  motion,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
  type MotionValue,
} from "framer-motion";
import { ChevronDown } from "lucide-react";

import { VoxelLandscapeBack, VoxelLandscapeFront } from "@/components/hero/voxel-landscape";

export interface MinecraftSunriseHeroProps {
  /** Still landscape backdrop. */
  imageSrc?: string;
  /**
   * Optional alpha-cutout PNG of just the near terrain, aligned to `imageSrc`.
   * When supplied it renders in front of the wordmark, reproducing the
   * skyline-overlaps-text depth of the reference. Without it a photographic
   * backdrop keeps the wordmark fully in front.
   */
  foregroundSrc?: string;
  /**
   * Optional sunrise clip scrubbed by scroll position. Muted and never
   * autoplayed; `imageSrc` acts as its poster.
   */
  videoSrc?: string;
  /** Scroll distance for the sequence, in viewport heights. */
  scrollLength?: number;
  eyebrow?: string;
  headline?: string;
  subhead?: string;
  wordmark?: string;
}

/** Sunrise key frames, cold pre-dawn through warm morning. */
const SKY_TOP = ["#05070f", "#0b1026", "#223160", "#5a6ea8", "#9db6dc"];
const SKY_MID = ["#0a0d1c", "#1d1b3a", "#5b3f6b", "#c0714f", "#f0a86a"];
const SKY_LOW = ["#101322", "#3a2340", "#99455a", "#f08a4b", "#ffd79a"];
const PROGRESS_STOPS = [0, 0.3, 0.55, 0.78, 1];

export function MinecraftSunriseHero({
  imageSrc = "/images/minecraft-hero.webp",
  foregroundSrc,
  videoSrc,
  scrollLength = 420,
  eyebrow = "MinedTV",
  headline = "Your moments. Rediscovered.",
  subhead = "Search every clip. Find every moment.",
  wordmark = "MinedTV",
}: MinecraftSunriseHeroProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();

  // The empty-placeholder case: an <img> that decodes to zero width is treated
  // as unusable so the procedural landscape takes over instead of rendering a
  // blank hero.
  const [imageUsable, setImageUsable] = useState(false);

  const { scrollYProgress } = useScroll({
    target: wrapperRef,
    offset: ["start start", "end end"],
  });

  // Smoothing the raw progress keeps trackpad jitter out of the lighting.
  // Softer than a snappy UI spring on purpose: the sunrise should trail the
  // scroll slightly so it reads as a scene settling into light, not a slider.
  const progress = useSpring(scrollYProgress, {
    stiffness: 140,
    damping: 32,
    restDelta: 0.0005,
  });

  const skyTop = useTransform(progress, PROGRESS_STOPS, SKY_TOP);
  const skyMid = useTransform(progress, PROGRESS_STOPS, SKY_MID);
  const skyLow = useTransform(progress, PROGRESS_STOPS, SKY_LOW);
  const skyGradient = useMotionGradient(skyTop, skyMid, skyLow);

  // Sun: climbs from below the ridge line and brightens as it clears it.
  const sunY = useTransform(progress, [0.1, 0.95], ["38%", "-14%"]);
  const sunOpacity = useTransform(progress, [0.08, 0.35, 1], [0, 0.85, 1]);
  const sunScale = useTransform(progress, [0.1, 1], [0.75, 1.35]);

  // Backdrop: slow push-in plus a small parallax rise.
  const plateScale = useTransform(progress, [0, 1], [1.14, 1.0]);
  const plateY = useTransform(progress, [0, 1], ["3%", "-3%"]);
  const plateFilter = useTransform(
    progress,
    [0, 0.45, 1],
    [
      "brightness(0.16) saturate(0.4) contrast(1.15)",
      "brightness(0.6) saturate(0.92) contrast(1.02)",
      "brightness(1.12) saturate(1.18) contrast(1)",
    ]
  );

  // Warm light wash over the terrain, strongest as the sun clears the ridge.
  const warmWash = useTransform(progress, [0.2, 0.6, 1], [0, 0.42, 0.26]);
  const haze = useTransform(progress, [0, 0.5, 1], [0.1, 0.46, 0.3]);
  // A near-black vignette at rest reads as pre-dawn; it opens up well past
  // the sunrise itself so full day looks genuinely bright, not just lifted.
  const vignette = useTransform(progress, [0, 0.5, 1], [0.94, 0.5, 0.18]);

  // Intro copy yields the frame before the wordmark arrives.
  const introOpacity = useTransform(progress, [0, 0.14, 0.3], [1, 1, 0]);
  const introY = useTransform(progress, [0, 0.3], ["0px", "-56px"]);
  const indicatorOpacity = useTransform(progress, [0, 0.1], [1, 0]);

  // The reveal, 0.60 → 0.85 as specified.
  const markOpacity = useTransform(progress, [0.58, 0.72, 0.86, 1], [0, 1, 1, 1]);
  const markScale = useTransform(progress, [0.58, 0.86], [1.22, 1]);
  const markTracking = useTransform(progress, [0.58, 0.86], ["0.42em", "0.02em"]);
  // Letter-spacing also applies after the final glyph, which drags the word
  // off-centre; cancel it with a matching negative margin.
  const markMargin = useTransform(progress, [0.58, 0.86], ["-0.42em", "-0.02em"]);
  const markBlur = useTransform(progress, [0.58, 0.8], [18, 0]);
  const markFilter = useTransform(markBlur, (value) => `blur(${value}px)`);
  const markY = useTransform(progress, [0.58, 0.86], ["26px", "0px"]);

  // Terrain tint tracks the same curve the sky does.
  const [scrollLight, setScrollLight] = useState(0);
  useEffect(
    () =>
      progress.on("change", (value) => {
        // Quantised so terrain recolouring repaints a handful of times rather
        // than on every scroll frame.
        setScrollLight(Math.round(Math.min(1, Math.max(0, value)) * 12) / 12);
      }),
    [progress]
  );
  // With motion suppressed the landscape simply sits in full morning light.
  const light = reduceMotion ? 1 : scrollLight;

  const useVideo = Boolean(videoSrc);

  if (reduceMotion) {
    return (
      <StaticHero
        imageSrc={imageUsable ? imageSrc : undefined}
        onImageReady={setImageUsable}
        probeSrc={imageSrc}
        eyebrow={eyebrow}
        headline={headline}
        subhead={subhead}
        wordmark={wordmark}
      />
    );
  }

  return (
    <div ref={wrapperRef} style={{ height: `${scrollLength}vh` }} className="relative">
      <div className="sticky top-0 h-[100dvh] w-full overflow-hidden bg-[#05070f]">
        {/* Probe: decides whether the supplied image is usable at all. */}
        <ImageProbe src={imageSrc} onResult={setImageUsable} />

        {/* ── sky ── */}
        <motion.div
          className="absolute inset-0"
          style={{
            background: skyGradient,
            willChange: "background",
          }}
        />

        {/* ── sun glow ── */}
        <motion.div
          className="pointer-events-none absolute left-1/2 h-[60vh] w-[60vh] -translate-x-1/2 rounded-full"
          style={{
            top: sunY,
            opacity: sunOpacity,
            scale: sunScale,
            background:
              "radial-gradient(circle, rgba(255,236,186,0.95) 0%, rgba(255,186,96,0.55) 28%, rgba(255,138,70,0.22) 52%, rgba(255,120,60,0) 72%)",
            filter: "blur(2px)",
            willChange: "transform, opacity",
          }}
        />

        {/* ── backdrop ── */}
        <motion.div
          className="absolute inset-0"
          style={{ scale: plateScale, y: plateY, willChange: "transform" }}
        >
          <motion.div className="h-full w-full" style={{ filter: plateFilter }}>
            {useVideo ? (
              <ScrubVideo src={videoSrc!} poster={imageUsable ? imageSrc : undefined} progress={progress} />
            ) : imageUsable ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={imageSrc}
                alt=""
                className="h-full w-full object-cover object-bottom"
                draggable={false}
              />
            ) : (
              <div className="absolute inset-x-0 bottom-0 top-[18%]">
                <VoxelLandscapeBack light={light} />
              </div>
            )}
          </motion.div>
        </motion.div>

        {/* ── warm light wash ── */}
        <motion.div
          className="pointer-events-none absolute inset-0 mix-blend-soft-light"
          style={{
            opacity: warmWash,
            background:
              "linear-gradient(180deg, rgba(255,214,150,0.9) 0%, rgba(255,160,90,0.55) 45%, rgba(255,120,70,0.1) 100%)",
          }}
        />

        {/* ── atmospheric haze along the horizon ── */}
        <motion.div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-[55%]"
          style={{
            opacity: haze,
            background:
              "linear-gradient(180deg, rgba(255,196,140,0) 0%, rgba(255,186,132,0.4) 42%, rgba(120,90,80,0.18) 100%)",
          }}
        />

        {/* ── intro copy ── */}
        <motion.div
          className="absolute inset-x-0 top-[26vh] z-20 flex flex-col items-center px-6 text-center"
          style={{ opacity: introOpacity, y: introY, willChange: "transform, opacity" }}
        >
          <motion.p
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.1 }}
            className="mb-5 text-[11px] font-semibold uppercase tracking-[0.42em] text-white/60"
          >
            {eyebrow}
          </motion.p>
          <motion.h1
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.85, delay: 0.22 }}
            className="max-w-3xl text-balance text-4xl font-semibold leading-[1.08] tracking-tight text-white drop-shadow-[0_2px_24px_rgba(0,0,0,0.75)] sm:text-6xl"
          >
            {headline}
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.85, delay: 0.38 }}
            className="mt-5 max-w-xl text-base text-white/70 drop-shadow-[0_1px_12px_rgba(0,0,0,0.8)] sm:text-lg"
          >
            {subhead}
          </motion.p>
        </motion.div>

        {/* ── wordmark: behind the near terrain, in front of everything else ── */}
        <motion.div
          className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center px-4"
          style={{ opacity: markOpacity, willChange: "opacity" }}
          aria-hidden
        >
          <motion.span
            className="select-none whitespace-nowrap text-[13vw] font-black leading-none text-white"
            style={{
              scale: markScale,
              letterSpacing: markTracking,
              marginRight: markMargin,
              filter: markFilter,
              y: markY,
              textShadow:
                "0 0 60px rgba(255,190,120,0.35), 0 8px 40px rgba(0,0,0,0.55)",
              willChange: "transform, filter",
            }}
          >
            {wordmark}
          </motion.span>
        </motion.div>

        {/* Accessible equivalent of the decorative wordmark. */}
        <h2 className="sr-only">{wordmark}</h2>

        {/* ── near terrain, drawn over the wordmark ── */}
        <motion.div
          className="pointer-events-none absolute inset-0 z-40"
          style={{ scale: plateScale, y: plateY, willChange: "transform" }}
        >
          {foregroundSrc ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={foregroundSrc}
              alt=""
              className="h-full w-full object-cover object-bottom"
              draggable={false}
            />
          ) : !imageUsable && !useVideo ? (
            <div className="absolute inset-x-0 bottom-0 top-[42%]">
              <VoxelLandscapeFront light={light} />
            </div>
          ) : null}
        </motion.div>

        {/* ── vignette + base fade into the next section ── */}
        <motion.div
          className="pointer-events-none absolute inset-0 z-50"
          style={{
            opacity: vignette,
            background:
              "radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 38%, rgba(0,0,0,0.72) 100%)",
          }}
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-50 h-32 bg-gradient-to-b from-transparent to-[#07090f]" />

        {/* ── scroll indicator ── */}
        <motion.div
          className="pointer-events-none absolute inset-x-0 bottom-8 z-50 flex flex-col items-center gap-2"
          style={{ opacity: indicatorOpacity }}
        >
          <span className="text-[10px] uppercase tracking-[0.32em] text-white/50">Scroll</span>
          <motion.span
            animate={{ y: [0, 7, 0] }}
            transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
          >
            <ChevronDown className="h-4 w-4 text-white/60" />
          </motion.span>
        </motion.div>
      </div>
    </div>
  );
}

/** Builds the animated three-stop sky gradient from three colour MotionValues. */
function useMotionGradient(
  top: MotionValue<string>,
  mid: MotionValue<string>,
  low: MotionValue<string>
) {
  return useTransform(
    [top, mid, low],
    ([a, b, c]: string[]) =>
      `linear-gradient(180deg, ${a} 0%, ${b} 52%, ${c} 100%)`
  );
}

/**
 * Loads the candidate image off-screen and reports whether it is actually
 * usable. A zero-byte placeholder fires `error`, and a decoded width of 0 is
 * treated the same way.
 */
function ImageProbe({ src, onResult }: { src: string; onResult: (ok: boolean) => void }) {
  useEffect(() => {
    let cancelled = false;
    const image = new window.Image();
    image.onload = () => {
      if (!cancelled) onResult(image.naturalWidth > 0 && image.naturalHeight > 0);
    };
    image.onerror = () => {
      if (!cancelled) onResult(false);
    };
    image.src = src;
    return () => {
      cancelled = true;
    };
  }, [src, onResult]);

  return null;
}

/**
 * Scroll-scrubbed video.
 *
 * Seeking is driven from an rAF loop rather than directly from the scroll
 * callback, and a new seek is only issued once the previous one has settled —
 * browsers drop `currentTime` writes that arrive while a seek is in flight,
 * which otherwise shows up as the video sticking at one frame.
 */
function ScrubVideo({
  src,
  poster,
  progress,
}: {
  src: string;
  poster?: string;
  progress: MotionValue<number>;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !ready) return;

    let frame = 0;
    let seeking = false;
    let lastTarget = -1;

    const markDone = () => {
      seeking = false;
    };
    video.addEventListener("seeked", markDone);
    video.addEventListener("error", markDone);

    const tick = () => {
      frame = requestAnimationFrame(tick);
      const duration = video.duration;
      if (!Number.isFinite(duration) || duration <= 0 || seeking) return;

      const target = Math.min(
        duration - 0.05,
        Math.max(0, progress.get() * duration)
      );
      // Sub-frame deltas are not worth a seek.
      if (Math.abs(target - lastTarget) < 0.03) return;

      lastTarget = target;
      seeking = true;
      try {
        video.currentTime = target;
      } catch {
        seeking = false;
      }
    };

    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      video.removeEventListener("seeked", markDone);
      video.removeEventListener("error", markDone);
    };
  }, [ready, progress]);

  return (
    <video
      ref={videoRef}
      src={src}
      poster={poster}
      muted
      playsInline
      preload="auto"
      // Metadata must land before any seek, or duration is NaN.
      onLoadedMetadata={() => setReady(true)}
      className="h-full w-full object-cover object-bottom"
    />
  );
}

/**
 * prefers-reduced-motion: the same scene at full morning, with the wordmark
 * already revealed. One screen, no scroll sequence, nothing animating.
 */
function StaticHero({
  imageSrc,
  probeSrc,
  onImageReady,
  eyebrow,
  headline,
  subhead,
  wordmark,
}: {
  imageSrc?: string;
  probeSrc: string;
  onImageReady: (ok: boolean) => void;
  eyebrow: string;
  headline: string;
  subhead: string;
  wordmark: string;
}) {
  return (
    <div className="relative h-[100dvh] w-full overflow-hidden bg-[#05070f]">
      <ImageProbe src={probeSrc} onResult={onImageReady} />
      <div
        className="absolute inset-0"
        style={{
          background: "linear-gradient(180deg, #9db6dc 0%, #f0a86a 52%, #ffd79a 100%)",
        }}
      />
      {imageSrc ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={imageSrc} alt="" className="h-full w-full object-cover object-bottom" />
      ) : (
        <>
          <div className="absolute inset-x-0 bottom-0 top-[18%]">
            <VoxelLandscapeBack light={1} />
          </div>
          <div className="absolute inset-x-0 bottom-0 top-[42%] z-30">
            <VoxelLandscapeFront light={1} />
          </div>
        </>
      )}
      <div className="absolute inset-0 z-20 flex items-center justify-center">
        <span className="select-none text-[13vw] font-black leading-none text-white drop-shadow-[0_8px_40px_rgba(0,0,0,0.55)]">
          {wordmark}
        </span>
      </div>
      <div className="absolute inset-x-0 top-[22vh] z-40 flex flex-col items-center px-6 text-center">
        <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.42em] text-white/70">
          {eyebrow}
        </p>
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-white drop-shadow-[0_2px_24px_rgba(0,0,0,0.75)] sm:text-6xl">
          {headline}
        </h1>
        <p className="mt-4 max-w-xl text-base text-white/80 sm:text-lg">{subhead}</p>
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-50 h-32 bg-gradient-to-b from-transparent to-[#07090f]" />
    </div>
  );
}
