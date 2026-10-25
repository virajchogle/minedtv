"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { neonVars, type NeonColor } from "@/lib/neon";

const EASE = "cubic-bezier(0.23,1,0.32,1)";

const css = `
@keyframes nk-neon-frame-draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }
@keyframes nk-neon-frame-ignite { 0% { opacity: 1; } 20% { opacity: 0.25; } 34% { opacity: 1; } 52% { opacity: 0.55; } 70%, 100% { opacity: 1; } }
@keyframes nk-neon-frame-scan { 0% { transform: translateY(-100%); opacity: 0; } 6% { opacity: 1; } 64% { transform: translateY(0); opacity: 1; } 72%, 100% { transform: translateY(0); opacity: 0; } }
.nk-neon-frame-corner {
  transform: scale(var(--nk-sx), var(--nk-sy));
  filter: drop-shadow(0 0 1.5px rgb(var(--neon) / calc(0.9 * var(--neon-glow, 1)))) drop-shadow(0 0 7px rgb(var(--neon) / calc(0.45 * var(--neon-glow, 1))));
  transition: transform 260ms ${EASE}, filter 200ms ease-out;
}
.nk-neon-frame:is(:hover, :focus-within) > .nk-neon-frame-corner,
.nk-neon-frame[data-active="true"] > .nk-neon-frame-corner {
  filter: drop-shadow(0 0 2px rgb(var(--neon) / var(--neon-glow, 1))) drop-shadow(0 0 12px rgb(var(--neon) / calc(0.75 * var(--neon-glow, 1))));
}
.nk-neon-frame[data-active="true"] > .nk-neon-frame-corner {
  transform: translate(calc(var(--nk-sx) * 3px), calc(var(--nk-sy) * 3px)) scale(var(--nk-sx), var(--nk-sy));
}
.nk-neon-frame-light { transition: opacity 200ms ease-out; }
.nk-neon-frame[data-active="false"] > .nk-neon-frame-corner { filter: none; }
.nk-neon-frame[data-active="false"] .nk-neon-frame-light,
.nk-neon-frame[data-active="false"] .nk-neon-frame-fade { opacity: 0; }
.nk-neon-frame[data-active="false"]:is(:hover, :focus-within) > .nk-neon-frame-corner { filter: drop-shadow(0 0 6px rgb(var(--neon) / calc(0.4 * var(--neon-glow, 1)))); }
.nk-neon-frame[data-active="false"]:is(:hover, :focus-within) .nk-neon-frame-light { opacity: 0.7; }
.nk-neon-frame-arm { stroke-dasharray: 1; stroke-dashoffset: 0; }
.nk-neon-frame[data-state="armed"] .nk-neon-frame-arm { stroke-dashoffset: 1; }
.nk-neon-frame[data-state="armed"] .nk-neon-frame-fade { opacity: 0; }
.nk-neon-frame[data-state="armed"] .nk-neon-frame-tab { opacity: 0; transform: translateY(var(--nk-ty)) translateY(var(--nk-from)); }
.nk-neon-frame[data-state="drawing"] .nk-neon-frame-arm { animation: nk-neon-frame-draw 420ms ${EASE} var(--nk-delay) both; }
.nk-neon-frame[data-state="drawing"] .nk-neon-frame-light > g { animation: nk-neon-frame-ignite 380ms linear calc(var(--nk-delay) + 380ms); }
.nk-neon-frame-fade { transition: opacity 400ms ease-out 260ms; }
.nk-neon-frame-tab { transform: translateY(var(--nk-ty)); transition: opacity 220ms ease-out 420ms, transform 260ms ${EASE} 420ms; }
.nk-neon-frame-scan { animation: nk-neon-frame-scan 5.5s cubic-bezier(0.45,0,0.55,1) infinite; }
@media (prefers-reduced-motion: reduce) {
  .nk-neon-frame[data-state] .nk-neon-frame-arm { animation: none; stroke-dashoffset: 0; }
  .nk-neon-frame[data-state] .nk-neon-frame-light > g { animation: none; }
  .nk-neon-frame[data-state] .nk-neon-frame-fade { opacity: 1; transition: none; }
  .nk-neon-frame[data-state] .nk-neon-frame-tab { opacity: 1; transform: translateY(var(--nk-ty)); transition: none; }
  .nk-neon-frame-corner { transition: filter 200ms ease-out; }
  .nk-neon-frame-scan { display: none; }
}
`;

type Corner = "topLeft" | "topRight" | "bottomRight" | "bottomLeft";

const corners: { corner: Corner; position: string; sx: number; sy: number; delay: number }[] = [
  { corner: "topLeft", position: "-left-px -top-px", sx: 1, sy: 1, delay: 0 },
  { corner: "topRight", position: "-right-px -top-px", sx: -1, sy: 1, delay: 90 },
  { corner: "bottomRight", position: "-bottom-px -right-px", sx: -1, sy: -1, delay: 180 },
  { corner: "bottomLeft", position: "-bottom-px -left-px", sx: 1, sy: -1, delay: 270 },
];

export interface NeonFrameTabs {
  topRight?: React.ReactNode;
  bottomLeft?: React.ReactNode;
  bottomRight?: React.ReactNode;
}

export interface NeonFrameProps
  extends Omit<React.HTMLAttributes<HTMLElement>, "color"> {
  as?: "div" | "section" | "article" | "aside" | "figure";
  /** Palette name or any hex color. Inherits `--neon-accent` when omitted. */
  color?: NeonColor;
  /** The frame's name, on a lit tab at the top-left edge. Labels a section, article, aside or figure. */
  label?: React.ReactNode;
  /** Quieter tabs on the other corners, for a channel, a status or a reading. */
  tabs?: NeonFrameTabs;
  /** A slow scan line sweeps down the frame. */
  scanline?: boolean;
  /** Length of each bracket arm in pixels. */
  bracket?: number;
  /**
   * For frames people pick between. true locks on: the brackets tighten in and
   * brighten. false parks the frame in standby: unlit glass brackets that light
   * up on hover and focus. Leave it undefined for a frame that is always lit.
   */
  active?: boolean;
  /** Draw the brackets in from the corners when the frame scrolls into view. */
  animate?: boolean;
}

const NeonFrame = React.forwardRef<HTMLElement, NeonFrameProps>(
  (
    {
      className,
      style,
      color,
      as: Comp = "div",
      label,
      tabs,
      scanline = false,
      bracket = 18,
      active,
      animate = true,
      children,
      ...props
    },
    ref,
  ) => {
    const labelId = React.useId();
    const rootRef = React.useRef<HTMLElement | null>(null);
    const setRefs = React.useCallback(
      (node: HTMLElement | null) => {
        rootRef.current = node;
        if (typeof ref === "function") ref(node);
        else if (ref) ref.current = node;
      },
      [ref],
    );

    const [phase, setPhase] = React.useState<"armed" | "drawing" | "lit">(animate ? "armed" : "lit");

    React.useEffect(() => {
      const node = rootRef.current;
      if (!animate || !node) return;
      let timeout: ReturnType<typeof setTimeout> | undefined;
      const start = () => {
        setPhase("drawing");
        timeout = setTimeout(() => setPhase("lit"), 1100);
      };
      if (typeof IntersectionObserver === "undefined") {
        const frame = requestAnimationFrame(start);
        return () => {
          cancelAnimationFrame(frame);
          clearTimeout(timeout);
        };
      }
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            observer.disconnect();
            start();
          }
        },
        { threshold: 0.3 },
      );
      observer.observe(node);
      return () => {
        observer.disconnect();
        clearTimeout(timeout);
      };
    }, [animate]);

    const hasLabel = label != null && label !== false;
    const landmark = Comp !== "div";
    const labelled =
      landmark && hasLabel && props["aria-label"] === undefined && props["aria-labelledby"] === undefined;

    const tab = (
      content: React.ReactNode,
      side: "top" | "bottom",
      edge: "left" | "right",
      primary = false,
    ) => (
      <span
        id={primary ? labelId : undefined}
        className={cn(
          "nk-neon-frame-tab absolute z-10 inline-flex h-5 items-center gap-1.5 whitespace-nowrap border bg-[#07080c] px-2",
          // Set in the body face and left in the case it's given; wrap readings in font-mono yourself.
          "text-[11px] font-medium leading-none tracking-[0.01em]",
          side === "top" ? "top-0" : "bottom-0",
          edge === "left" ? "left-[calc(var(--nk-arm)+10px)]" : "right-[calc(var(--nk-arm)+10px)]",
          primary
            ? "border-[rgb(var(--neon)/0.4)] text-[rgb(var(--neon))] [text-shadow:0_0_8px_rgb(var(--neon)/CALC(0.55*var(--neon-glow,1)))]"
            : "border-white/10 text-white/55",
        )}
        style={
          {
            "--nk-ty": side === "top" ? "-50%" : "50%",
            "--nk-from": side === "top" ? "4px" : "-4px",
          } as React.CSSProperties
        }
      >
        {primary && (
          <span aria-hidden className="size-1 shrink-0 bg-[rgb(var(--neon))] shadow-[0_0_6px_rgb(var(--neon)/var(--neon-glow,1))]" />
        )}
        {content}
      </span>
    );

    return (
      <Comp
        ref={setRefs as React.Ref<HTMLDivElement>}
        data-state={phase}
        data-active={active === undefined ? undefined : String(active)}
        aria-labelledby={labelled ? labelId : undefined}
        style={neonVars(color, { "--nk-arm": `${bracket}px`, ...style } as React.CSSProperties)}
        className={cn(
          "[--neon:var(--neon-accent,34_211_238)]",
          "nk-neon-frame relative isolate border border-white/[0.08] bg-white/[0.02] p-5",
          className,
        )}
        {...props}
      >
        <style>{css}</style>

        {/* The brackets' light on the panel */}
        <span
          aria-hidden
          className="nk-neon-frame-fade pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_0_0,rgb(var(--neon)/CALC(0.1*var(--neon-glow,1))),transparent_72px),radial-gradient(circle_at_100%_0,rgb(var(--neon)/CALC(0.1*var(--neon-glow,1))),transparent_72px),radial-gradient(circle_at_100%_100%,rgb(var(--neon)/CALC(0.1*var(--neon-glow,1))),transparent_72px),radial-gradient(circle_at_0_100%,rgb(var(--neon)/CALC(0.1*var(--neon-glow,1))),transparent_72px)]"
        />

        {hasLabel && tab(label, "top", "left", true)}
        {tabs?.topRight != null && tab(tabs.topRight, "top", "right")}

        {children}

        {tabs?.bottomLeft != null && tab(tabs.bottomLeft, "bottom", "left")}
        {tabs?.bottomRight != null && tab(tabs.bottomRight, "bottom", "right")}

        {scanline && (
          <span aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
            <span className="nk-neon-frame-scan absolute inset-0">
              <span className="absolute inset-x-0 bottom-0 h-16 bg-[linear-gradient(to_bottom,transparent,rgb(var(--neon)/0.07))]" />
              <span className="absolute inset-x-0 bottom-0 h-px bg-[rgb(var(--neon)/0.5)] shadow-[0_0_8px_rgb(var(--neon)/CALC(0.6*var(--neon-glow,1)))]" />
            </span>
          </span>
        )}

        {corners.map(({ corner, position, sx, sy, delay }) => (
          <svg
            key={corner}
            aria-hidden
            data-corner={corner}
            viewBox={`0 0 ${bracket + 2} ${bracket + 2}`}
            className={cn("nk-neon-frame-corner pointer-events-none absolute overflow-visible", position)}
            style={
              {
                width: bracket + 2,
                height: bracket + 2,
                "--nk-sx": sx,
                "--nk-sy": sy,
                "--nk-delay": `${delay}ms`,
              } as React.CSSProperties
            }
          >
            {/* The glass, there before the light runs through it */}
            <g>
              {[`M1 1V${bracket + 1}`, `M1 1H${bracket + 1}`].map((d) => (
                <path key={d} d={d} fill="none" strokeWidth={2} strokeLinecap="round" style={{ stroke: "rgb(var(--neon) / 0.2)" }} />
              ))}
            </g>
            <g className="nk-neon-frame-light">
              <g>
                {[`M1 1V${bracket + 1}`, `M1 1H${bracket + 1}`].map((d) => (
                  <React.Fragment key={d}>
                    <path
                      d={d}
                      pathLength={1}
                      className="nk-neon-frame-arm"
                      fill="none"
                      strokeWidth={2}
                      strokeLinecap="round"
                      style={{ stroke: "rgb(var(--neon))" }}
                    />
                    <path
                      d={d}
                      pathLength={1}
                      className="nk-neon-frame-arm"
                      fill="none"
                      strokeWidth={0.9}
                      strokeLinecap="round"
                      style={{ stroke: "color-mix(in srgb, rgb(var(--neon)) 30%, white)" }}
                    />
                  </React.Fragment>
                ))}
              </g>
            </g>
          </svg>
        ))}
      </Comp>
    );
  },
);
NeonFrame.displayName = "NeonFrame";

export { NeonFrame };
