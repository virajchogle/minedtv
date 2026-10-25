"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { neonVars, toNeonRgb, type NeonColor } from "@/lib/neon";

// The beam is a chain of short segments that travel the element's own outline with offset-path, each a
// fixed share of a lap behind the one ahead. So it keeps one speed and one length on every edge, even on
// a wide pill, and bends around corners instead of sticking out of them. The border ring masks it.
// Browsers without offset-path rect() fall back to a conic gradient swept by an @property angle.
const SEGMENTS = 12;

const css = `
@property --nk-beam-angle { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
@keyframes nk-beam { to { --nk-beam-angle: 360deg; } }
@keyframes nk-beam-run { from { offset-distance: 0%; } to { offset-distance: 100%; } }
.nk-beam {
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box exclude, linear-gradient(#000 0 0);
}
.nk-beam-head {
  position: absolute;
  left: 0;
  top: 0;
  /* Each segment overlaps the next by a pixel so the joins don't show. */
  width: calc(var(--nk-beam-length, 120px) / ${SEGMENTS} + 1px);
  /* Thin enough that it never reaches the opposite edge of a short element. */
  height: 20px;
  offset-path: rect(0 auto auto 0 round var(--nk-beam-radius, 0px));
  offset-anchor: 100% 50%;
  offset-rotate: auto;
  animation: nk-beam-run var(--nk-beam-duration) linear var(--nk-beam-delay, 0s) infinite;
}
.nk-beam[data-reverse] .nk-beam-head { animation-direction: reverse; offset-rotate: auto 180deg; }
@supports not (offset-path: rect(0 auto auto 0)) {
  .nk-beam-head { display: none; }
  .nk-beam {
    background: conic-gradient(
      from var(--nk-beam-angle),
      transparent 0deg,
      transparent calc(360deg - var(--nk-beam-size)),
      rgb(var(--nk-beam-to) / 0.35) calc(360deg - var(--nk-beam-size) * 0.55),
      rgb(var(--neon)) calc(360deg - var(--nk-beam-size) * 0.08),
      color-mix(in srgb, rgb(var(--neon)) 35%, white) 359deg,
      transparent 360deg
    );
    animation: nk-beam var(--nk-beam-duration) linear infinite;
  }
}
@media (prefers-reduced-motion: reduce) {
  .nk-beam { animation: none; --nk-beam-angle: 135deg; }
  /* Held a third of the way round, so the still beam lies along an edge instead of in a corner. Set
     without animation so it survives global resets that shorten every animation to nothing. */
  .nk-beam-head { animation: none; offset-distance: calc(30% - var(--nk-beam-lag, 0%)); }
  .nk-beam[data-reverse] .nk-beam-head { offset-distance: calc(30% + var(--nk-beam-lag, 0%)); }
}
`;

// The light along the beam, t = 0 at the head and 1 at the tail: white-hot, then the head color easing
// into the tail color as it fades.
function beamColor(t: number) {
  if (t <= 0) return "color-mix(in srgb, rgb(var(--neon)) 35%, white)";
  const alpha = Math.pow(1 - t, 1.3).toFixed(3);
  const tail = Math.round(Math.min(1, Math.max(0, (t - 0.08) / 0.6)) * 100);
  return `color-mix(in srgb, rgb(var(--neon) / ${alpha}) ${100 - tail}%, rgb(var(--nk-beam-to) / ${alpha}))`;
}

const useIsoLayoutEffect = typeof window === "undefined" ? React.useEffect : React.useLayoutEffect;

export interface BorderBeamProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "color"> {
  /** Head of the beam. Inherits `--neon-accent` when omitted. */
  color?: NeonColor;
  /** Tail of the beam. Defaults to the head color. */
  colorTo?: NeonColor;
  /** Seconds per lap. */
  duration?: number;
  /** Beam length, in degrees of the lap. */
  size?: number;
  /** Border thickness in pixels. */
  borderWidth?: number;
  /** Run counter-clockwise. */
  reverse?: boolean;
}

const BorderBeam = React.forwardRef<HTMLDivElement, BorderBeamProps>(
  (
    {
      className,
      style,
      color,
      colorTo,
      duration = 6,
      size = 90,
      borderWidth = 1,
      reverse = false,
      children,
      ...props
    },
    forwardedRef,
  ) => {
    const ref = React.useRef<HTMLDivElement>(null);
    React.useImperativeHandle(forwardedRef, () => ref.current as HTMLDivElement);

    // The beam's length is a share of the outline, and offset-path needs the corner radius in pixels.
    useIsoLayoutEffect(() => {
      const node = ref.current;
      if (!node) return;
      const measure = () => {
        const width = node.offsetWidth;
        const height = node.offsetHeight;
        const radius = Math.min(parseFloat(getComputedStyle(node).borderTopLeftRadius) || 0, width / 2, height / 2);
        const perimeter = 2 * (width + height) - (8 - 2 * Math.PI) * radius;
        node.style.setProperty("--nk-beam-radius", `${radius}px`);
        node.style.setProperty("--nk-beam-length", `${Math.max(12, (perimeter * Math.min(size, 360)) / 360)}px`);
      };
      measure();
      const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
      observer?.observe(node);
      return () => observer?.disconnect();
    }, [size]);

    const lap = Math.min(size, 360) / 360;
    const segments = Array.from({ length: SEGMENTS }, (_, i) => (
      <span
        key={i}
        className="nk-beam-head"
        style={{
          background: `linear-gradient(to right, ${beamColor((i + 1) / SEGMENTS)}, ${beamColor(i / SEGMENTS)})`,
          // A negative delay of (1 - lag) laps puts this segment `lag` of a lap behind the head.
          "--nk-beam-delay": `${-duration * (1 - (i * lap) / SEGMENTS)}s`,
          "--nk-beam-lag": `${((i * lap) / SEGMENTS) * 100}%`,
        } as React.CSSProperties}
      />
    ));

    const beamStyle = {
      "--nk-beam-to": colorTo ? toNeonRgb(colorTo) : "var(--neon)",
      "--nk-beam-size": `${size}deg`,
      "--nk-beam-duration": `${duration}s`,
      padding: borderWidth,
      animationDirection: reverse ? "reverse" : undefined,
    } as React.CSSProperties;

    return (
      <div
        ref={ref}
        style={neonVars(color, style)}
        className={cn(
          "[--neon:var(--neon-accent,34_211_238)]",
          "relative rounded-2xl",
          className,
        )}
        {...props}
      >
        <style>{css}</style>
        {children}
        <span
          aria-hidden
          data-reverse={reverse || undefined}
          style={beamStyle}
          className="nk-beam pointer-events-none absolute inset-0 rounded-[inherit]"
        >
          {segments}
        </span>
        {/* The glow is blurred after the ring mask, so it spills softly to both sides of the border. */}
        <span aria-hidden className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-75 [filter:blur(6px)_opacity(var(--neon-glow,1))]">
          <span
            data-reverse={reverse || undefined}
            style={{ ...beamStyle, padding: borderWidth + 1 }}
            className="nk-beam absolute inset-0 rounded-[inherit]"
          >
            {segments}
          </span>
        </span>
      </div>
    );
  },
);
BorderBeam.displayName = "BorderBeam";

export { BorderBeam };
