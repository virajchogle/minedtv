"use client";

/**
 * MinedIt's site footer: the wordmark stamps itself in letter by letter with
 * an ink-texture filter and a puff of dust, a hand-drawn ground line draws
 * itself underneath, and a handful of doodles (flame/star/sparkle/bolt)
 * drift around — pushed away by the pointer within reach, and popping when
 * clicked. Everything plays once, when it scrolls into view, then stays
 * alive: the doodles keep drifting, letters wobble on hover.
 *
 * Adapted from the "DoodleCrewFooter" reference supplied in chat, reskinned
 * for MinedIt (black + sunflower-yellow) and simplified: the illustrated
 * mascot crew (named characters standing on the letters, with gaze-tracking
 * and speech bubbles) is left out — six cartoon animals didn't fit this
 * site's plain, minimal look. The crew plumbing (CrewMember, ART, seatPoint,
 * gaze tracking) from the original is dropped for the same reason: no point
 * carrying code nobody exercises. Everything else — the wordmark stamp-in,
 * ink filter, ground line, floating doodles, reduced-motion handling — is
 * real and wired up.
 *
 * No dependencies beyond what's already in this app: React + framer-motion
 * (already installed) for the entrance reveal, everything else is inline
 * SVG and a scoped <style> block.
 */

import * as React from "react";

// ---- pure helpers (deterministic, no React) --------------------------------

/** Small deterministic hash -> [0, 1), so every render lays the scene out the same way. */
const hash = (n: number): number => {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
};

const clamp = (v: number, lo: number, hi: number): number => (v < lo ? lo : v > hi ? hi : v);

/** Per-letter advances (font units) -> left edge of each letter + total width, with `tracking` (em) between letters. */
function layoutWord(advances: number[], tracking: number, fontSize: number): { x: number[]; width: number } {
  const x: number[] = [];
  let at = 0;
  const gap = (Number.isFinite(tracking) ? tracking : 0) * fontSize;
  for (let i = 0; i < advances.length; i++) {
    const a = Number.isFinite(advances[i]) && advances[i] > 0 ? advances[i] : 0;
    x.push(at);
    at += a + (i < advances.length - 1 ? gap : 0);
  }
  return { x, width: Math.max(0, at) };
}

type Floater = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  rot: number;
  vr: number;
  fall: number;
  phase: number;
  /** Seconds left in a pop; 0 means alive. */
  pop: number;
};

/** One step of a doodle's drift: falls + sways, the pointer pushes it away within `radius`, wraps round the box. */
function stepFloater(f: Floater, dt: number, t: number, w: number, h: number, px: number, py: number, radius: number, rand: () => number): Floater {
  const step = clamp(Number.isFinite(dt) ? dt : 0, 0, 0.05);
  const m = 40;
  if (f.pop > 0) {
    f.pop -= step;
    if (f.pop <= 0) {
      f.pop = 0;
      f.x = rand() * w;
      f.y = -m;
      f.vx = 0;
      f.vy = f.fall;
    }
    return f;
  }
  const sway = Math.sin(t * 0.7 + f.phase) * 14;
  if (Number.isFinite(px) && Number.isFinite(py) && radius > 0) {
    const dx = f.x - px;
    const dy = f.y - py;
    const d = Math.hypot(dx, dy);
    if (d < radius && d > 0.01) {
      const k = (1 - d / radius) * (1 - d / radius) * 2400;
      f.vx += (dx / d) * k * step;
      f.vy += (dy / d) * k * step;
      f.vr += (dx > 0 ? 1 : -1) * k * 0.004 * step;
    }
  }
  const ease = Math.min(1, step * 2.4);
  f.vx += (sway - f.vx) * ease;
  f.vy += (f.fall - f.vy) * ease;
  f.vr += (Math.sin(f.phase * 3) * 18 - f.vr) * Math.min(1, step * 0.8);
  f.x += f.vx * step;
  f.y += f.vy * step;
  f.rot = (f.rot + f.vr * step) % 360;
  if (f.y > h + m) {
    f.y = -m;
    f.x = rand() * w;
  } else if (f.y < -m * 3) {
    f.y = h + m;
  }
  if (f.x < -m) f.x = w + m;
  else if (f.x > w + m) f.x = -m;
  return f;
}

/** Storyboard, in ms from the moment the footer scrolls into view. */
function timeline(letters: number, words: number, actionsCount: number) {
  const L = Math.max(0, Math.floor(letters) || 0);
  const W = Math.max(0, Math.floor(words) || 0);
  const A = Math.max(0, Math.floor(actionsCount) || 0);
  const letter = (i: number) => 80 + i * 70;
  const groundAt = 0;
  const doodles = letter(Math.max(0, L - 1)) + 360;
  const copy = letter(Math.max(0, L - 1)) + 420;
  const word = (k: number) => copy + k * 45;
  const actionsStart = word(W) + 120;
  const action = (k: number) => actionsStart + k * 100;
  return { ground: groundAt, letter, doodles, word, action, total: action(Math.max(0, A - 1)) + 500 };
}

// ---- doodles -----------------------------------------------------------------

export type DoodleKind = "flame" | "star" | "heart" | "bolt" | "sparkle";

const ACCENT = { flame: "#ff7a1a", flameCore: "#ffd23f", gold: "#eab308", heart: "#ff5c7a", sparkle: "#8fdcff" };

/** Each doodle in a 32-unit box centred on (0, 0). */
function Doodle({ kind }: { kind: DoodleKind }) {
  switch (kind) {
    case "flame":
      return (
        <>
          <path fill={ACCENT.flame} d="M0 14 C-9 14 -12 6 -10 0 C-8 -5 -4 -6 -4 -12 C1 -9 3 -5 2 -1 C4 -3 5 -6 5 -8 C10 -3 11 4 8 9 C6 12 3 14 0 14 Z" />
          <path fill={ACCENT.flameCore} d="M0 11.5 C-4 11.5 -6 8 -5 5 C-4 2 -1 1 -1 -3 C2 -1 4 3 3 6 C4 5 5 4 5 3 C7 6 5 11.5 0 11.5 Z" />
        </>
      );
    case "star":
      return <path fill={ACCENT.gold} d="M0 -13 L3.6 -4.4 L13 -4 L5.8 2.2 L8.2 12 L0 6.6 L-8.2 12 L-5.8 2.2 L-13 -4 L-3.6 -4.4 Z" />;
    case "heart":
      return <path fill={ACCENT.heart} d="M0 11 C-6 6 -13 1 -13 -5 C-13 -10 -8 -13 -4 -11 C-2 -10 -1 -8 0 -6 C1 -8 2 -10 4 -11 C8 -13 13 -10 13 -5 C13 1 6 6 0 11 Z" />;
    case "bolt":
      return <path fill={ACCENT.gold} d="M3 -14 L-8 2 L-1 2 L-4 14 L8 -3 L1 -3 Z" />;
    case "sparkle":
      return <path fill={ACCENT.sparkle} d="M0 -13 C1 -4 4 -1 13 0 C4 1 1 4 0 13 C-1 4 -4 1 -13 0 C-4 -1 -1 -4 0 -13 Z" />;
  }
}

// ---- types ---------------------------------------------------------------

export interface FooterLink {
  label: string;
  href?: string;
}

export interface FooterColumn {
  title: string;
  links: FooterLink[];
}

export interface FooterAction {
  label: string;
  href?: string;
  onClick?: () => void;
  variant?: "solid" | "outline";
}

export interface DoodleCrewFooterProps {
  /** The giant stamped-in word. Short, upper case, 4-9 letters reads best. */
  wordmark?: string;
  brand?: string;
  blurb?: string;
  tagline?: string;
  columns?: FooterColumn[];
  actions?: FooterAction[];
  copyright?: string;
  legal?: FooterLink[];
  backToTop?: boolean;
  doodles?: DoodleKind[];
  doodleCount?: number;
  /** Letter spacing of the wordmark, in em. Defaults to -0.02. */
  tracking?: number;
  /** Pointer push + hover/click play. Defaults to true. */
  interactive?: boolean;
  /** Minimum height; the footer grows past it if its content needs to. */
  height?: string;
  className?: string;
}

const DEFAULT_COLUMNS: FooterColumn[] = [
  { title: "Explore", links: [{ label: "Home", href: "/" }, { label: "Explore clips", href: "/explore" }, { label: "My Library", href: "/library" }] },
  { title: "Create", links: [{ label: "Upload a clip", href: "/upload" }, { label: "Dashboard", href: "/dashboard" }, { label: "Profile", href: "/profile" }] },
];

const DEFAULT_ACTIONS: FooterAction[] = [
  { label: "Explore Library", href: "/library", variant: "outline" },
  { label: "Upload a Clip", href: "/upload", variant: "solid" },
];

const DEFAULT_DOODLES: DoodleKind[] = ["flame", "star", "sparkle", "bolt", "flame", "star"];

const FONT_SIZE = 200;
const DEFAULT_FONT = '"Arial Black", "Inter Display", Inter, "Helvetica Neue", Helvetica, Arial, sans-serif';

const estimate = (word: string): { advances: number[]; cap: number } => ({
  advances: Array.from(word).map((c) => (c === " " ? 0.3 : /[IJ1]/.test(c) ? 0.42 : /[MW]/.test(c) ? 0.98 : 0.76) * FONT_SIZE),
  cap: 0.73 * FONT_SIZE,
});

function measure(word: string, family: string): { advances: number[]; cap: number } | null {
  if (typeof document === "undefined") return null;
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return null;
  ctx.font = "900 " + FONT_SIZE + "px " + family;
  const chars = Array.from(word);
  const advances: number[] = [];
  let prev = 0;
  for (let i = 0; i < chars.length; i++) {
    const wNow = ctx.measureText(chars.slice(0, i + 1).join("")).width;
    advances.push(wNow - prev);
    prev = wNow;
  }
  const m = ctx.measureText(word.replace(/\s/g, "") || "H");
  const cap = m.actualBoundingBoxAscent > 0 ? m.actualBoundingBoxAscent : 0.73 * FONT_SIZE;
  return { advances, cap };
}

const useIso = typeof window !== "undefined" ? React.useLayoutEffect : React.useEffect;

function FooterLinkItem({ link, className }: { link: FooterLink; className?: string }) {
  return link.href ? (
    <a className={className} href={link.href}>
      <span>{link.label}</span>
      <svg className="dcf-squiggle" viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true">
        <path pathLength={1} d="M1 5 C10 1 16 7 25 4 S40 1 50 4 S66 7 75 4 S90 1 99 4" />
      </svg>
    </a>
  ) : (
    <span className={className}>{link.label}</span>
  );
}

export function DoodleCrewFooter({
  wordmark = "MINEDIT",
  brand = "MinedIt",
  blurb = "Search your gaming moments by what happened, not what you named the file.",
  tagline = "Clip the plays that blow your mind.",
  columns = DEFAULT_COLUMNS,
  actions = DEFAULT_ACTIONS,
  copyright = `© ${new Date().getFullYear()} MinedIt`,
  legal = [],
  backToTop = true,
  doodles = DEFAULT_DOODLES,
  doodleCount = 10,
  tracking = -0.02,
  interactive = true,
  height = "560px",
  className,
}: DoodleCrewFooterProps) {
  const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const word = wordmark.toUpperCase();
  const chars = React.useMemo(() => Array.from(word), [word]);

  const rootRef = React.useRef<HTMLElement | null>(null);
  const svgRef = React.useRef<SVGSVGElement | null>(null);
  const worldRef = React.useRef<HTMLDivElement | null>(null);
  const doodleRefs = React.useRef<(HTMLDivElement | null)[]>([]);

  const [metrics, setMetrics] = React.useState(() => estimate(word));
  const [play, setPlay] = React.useState(false);
  const [reduced, setReduced] = React.useState(false);

  // ---- measure the real face, again once late web fonts land ----
  useIso(() => {
    const run = () => {
      const m = measure(word, DEFAULT_FONT);
      if (m) setMetrics(m);
    };
    run();
    const fonts = typeof document !== "undefined" ? document.fonts : undefined;
    if (!fonts) return;
    let alive = true;
    fonts.ready.then(() => alive && run());
    fonts.addEventListener?.("loadingdone", run);
    return () => {
      alive = false;
      fonts.removeEventListener?.("loadingdone", run);
    };
  }, [word]);

  const layout = React.useMemo(() => layoutWord(metrics.advances, tracking, FONT_SIZE), [metrics, tracking]);
  const cap = metrics.cap;

  const view = React.useMemo(() => {
    const pad = 24;
    return { x: -pad, y: -cap - pad, w: layout.width + pad * 2, h: cap + 30 + pad * 2 };
  }, [layout, cap]);

  const words = tagline.split(/\s+/).filter(Boolean);
  const tl = timeline(chars.length, words.length, actions.length);

  const ground = React.useMemo(() => {
    const x0 = view.x + 6;
    const x1 = view.x + view.w - 6;
    let d = "M" + x0.toFixed(1) + " 6";
    const n = 14;
    for (let k = 1; k <= n; k++) {
      const x = x0 + ((x1 - x0) * k) / n;
      d += " Q" + (x - (x1 - x0) / n / 2).toFixed(1) + " " + (6 + (hash(k * 3.1) - 0.5) * 5).toFixed(1) + " " + x.toFixed(1) + " " + (6 + (hash(k * 7.7) - 0.5) * 2).toFixed(1);
    }
    let tufts = "";
    for (let k = 0; k < 22; k++) {
      const x = x0 + 20 + hash(k * 11.3) * (x1 - x0 - 40);
      const s = 0.7 + hash(k * 5.9) * 0.6;
      tufts += "M" + x.toFixed(1) + " 6 l" + (2 * s).toFixed(1) + " " + (-9 * s).toFixed(1) + " M" + (x + 3 * s).toFixed(1) + " 6 l" + (1 * s).toFixed(1) + " " + (-12 * s).toFixed(1) + " M" + (x + 6 * s).toFixed(1) + " 6 l" + (-1 * s).toFixed(1) + " " + (-7 * s).toFixed(1) + " ";
    }
    const pebbles = Array.from({ length: 9 }, (_, k) => ({ x: x0 + 40 + hash(k * 17.1) * (x1 - x0 - 80), y: 14 + hash(k * 2.3) * 8, r: 2 + hash(k * 9.4) * 2.6 }));
    return { d, tufts, pebbles };
  }, [view]);

  // ---- doodles ----
  const doodleList = React.useMemo(() => {
    const kinds = doodles.length ? doodles : [];
    const n = kinds.length ? clamp(Math.floor(doodleCount) || 0, 0, 40) : 0;
    return Array.from({ length: n }, (_, k) => ({ kind: kinds[k % kinds.length], size: 20 + hash(k * 4.7) * 12, seed: k }));
  }, [doodles, doodleCount]);

  const sim = React.useRef({
    floaters: [] as Floater[],
    w: 0,
    h: 0,
    px: NaN,
    py: NaN,
    inside: false,
    visible: false,
    seed: 1,
    start: 0,
  });

  const paintDoodles = () => {
    const s = sim.current;
    const k = clamp(s.w / 1100, 0.5, 1);
    for (let i = 0; i < s.floaters.length; i++) {
      const el = doodleRefs.current[i];
      const f = s.floaters[i];
      if (!el || !f) continue;
      let sc = k;
      let op = 1;
      if (f.pop > 0) {
        const age = 1.4 - f.pop;
        sc = k * (1 + Math.min(1, age / 0.3) * 0.7);
        op = Math.max(0, 1 - age / 0.3);
      }
      el.style.transform = "translate3d(" + f.x.toFixed(1) + "px," + f.y.toFixed(1) + "px,0) rotate(" + f.rot.toFixed(1) + "deg) scale(" + sc.toFixed(3) + ")";
      el.style.opacity = String(op);
    }
  };

  useIso(() => {
    const el = worldRef.current;
    if (!el) return;
    const s = sim.current;
    const size = () => {
      const r = el.getBoundingClientRect();
      const ow = s.w;
      const oh = s.h;
      s.w = r.width;
      s.h = r.height;
      if (s.floaters.length !== doodleList.length || !ow) {
        s.floaters = doodleList.map((d, k) => ({
          x: (0.04 + 0.92 * ((k + hash(k * 9.1) * 0.8) / Math.max(1, doodleList.length))) * r.width,
          y: (0.02 + hash(k * 3.3) * 0.56) * r.height,
          vx: 0,
          vy: 0,
          rot: (hash(k * 1.7) - 0.5) * 50,
          vr: (hash(k * 6.1) - 0.5) * 30,
          fall: 9 + hash(k * 2.9) * 16,
          phase: hash(k * 8.3) * Math.PI * 2,
          pop: 0,
        }));
      } else if (ow && oh) {
        for (const f of s.floaters) {
          f.x *= r.width / ow;
          f.y *= r.height / oh;
        }
      }
      paintDoodles();
    };
    size();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(size);
    ro.observe(el);
    return () => ro.disconnect();
  }, [doodleList]);

  React.useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduced(mq.matches);
    on();
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);

  React.useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const s = sim.current;
    if (typeof IntersectionObserver === "undefined") {
      s.visible = true;
      const raf = requestAnimationFrame(() => setPlay(true));
      return () => cancelAnimationFrame(raf);
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          s.visible = e.isIntersecting;
          if (e.isIntersecting && e.intersectionRatio > 0.12) setPlay(true);
        }
      },
      { threshold: [0, 0.12, 0.3] }
    );
    io.observe(root);
    return () => io.disconnect();
  }, []);

  React.useEffect(() => {
    if (play && !sim.current.start) sim.current.start = performance.now();
  }, [play]);

  // ---- the living loop: doodles drift/push/pop, ink-boil on the letters ----
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const s = sim.current;
    let raf = 0;
    let last = performance.now();
    let boilAt = 0;
    let boil = 0;
    const rand = () => {
      s.seed = (s.seed * 16807) % 2147483647;
      return s.seed / 2147483647;
    };
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (!s.visible || document.hidden) {
        last = now;
        return;
      }
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = now / 1000;
      const world = worldRef.current;

      if (world && s.floaters.length) {
        const started = play && s.start ? now - s.start > tl.doodles || reduced : false;
        if (started) {
          const r = world.getBoundingClientRect();
          const px = s.inside && interactive ? s.px - r.left : NaN;
          const py = s.inside && interactive ? s.py - r.top : NaN;
          if (!reduced) for (const f of s.floaters) stepFloater(f, dt, t, s.w, s.h, px, py, 110, rand);
          paintDoodles();
        }
      }

      if (!reduced && svgRef.current && now - boilAt > 125) {
        boilAt = now;
        boil = (boil + 1) % 3;
        svgRef.current.style.setProperty("--dcf-boil", "url(#" + uid + "-boil" + boil + ")");
      }
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [play, reduced, interactive, uid, tl.doodles]);

  const onPointerMove = (e: React.PointerEvent) => {
    const s = sim.current;
    s.px = e.clientX;
    s.py = e.clientY;
    s.inside = true;
  };
  const onPointerLeave = () => {
    sim.current.inside = false;
  };

  const popDoodle = (k: number) => {
    if (!interactive) return;
    const f = sim.current.floaters[k];
    if (f && f.pop <= 0) {
      f.pop = 1.4;
      paintDoodles();
    }
  };

  const toTop = () => {
    if (typeof window === "undefined") return;
    window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
  };

  const vars = { minHeight: height } as React.CSSProperties;

  return (
    <footer
      ref={rootRef as React.RefObject<HTMLElement>}
      className={"dcf" + (className ? " " + className : "")}
      data-play={play || reduced ? "1" : "0"}
      style={vars}
      onPointerMove={onPointerMove}
      onPointerDown={onPointerMove}
      onPointerLeave={onPointerLeave}
    >
      <style>{CSS}</style>

      <div className="dcf-top dcf-rise" style={{ "--d": "0ms" } as React.CSSProperties}>
        <div className="dcf-brand">
          <span className="dcf-brandname">{brand}</span>
        </div>
        {blurb && <p className="dcf-blurb">{blurb}</p>}
        {columns.length > 0 && (
          <nav className="dcf-cols" aria-label="Footer">
            {columns.map((col) => (
              <div className="dcf-col" key={col.title}>
                <h2 className="dcf-coltitle">{col.title}</h2>
                <ul>
                  {col.links.map((l) => (
                    <li key={l.label}>
                      <FooterLinkItem link={l} className="dcf-link" />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        )}
      </div>

      <div className="dcf-world" ref={worldRef}>
        <div className="dcf-stage">
          <h2 className="dcf-sr">{wordmark}</h2>
          <svg
            ref={svgRef}
            className="dcf-svg"
            viewBox={view.x.toFixed(1) + " " + view.y.toFixed(1) + " " + view.w.toFixed(1) + " " + view.h.toFixed(1)}
            aria-hidden="true"
          >
            <defs>
              {[0, 1, 2].map((k) => (
                <filter key={k} id={uid + "-boil" + k} x="-10%" y="-10%" width="120%" height="120%">
                  <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed={k * 7 + 3} result="n" />
                  <feDisplacementMap in="SourceGraphic" in2="n" scale="2.6" xChannelSelector="R" yChannelSelector="G" />
                </filter>
              ))}
              <filter id={uid + "-ink"} x="-4%" y="-6%" width="108%" height="112%">
                <feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves="3" seed="11" result="edge" />
                <feDisplacementMap in="SourceGraphic" in2="edge" scale="5" xChannelSelector="R" yChannelSelector="G" result="rough" />
                <feTurbulence type="fractalNoise" baseFrequency="0.018 0.32" numOctaves="2" seed="4" result="streak" />
                <feColorMatrix in="streak" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -16 5.6" result="streakA" />
                <feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="1" seed="9" result="speck" />
                <feColorMatrix in="speck" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -24 7.0" result="speckA" />
                <feComposite in="streakA" in2="speckA" operator="arithmetic" k1="0" k2="1" k3="1" k4="0" result="holes" />
                <feComposite in="rough" in2="holes" operator="out" />
              </filter>
            </defs>

            <g className="dcf-ground">
              <path className="dcf-draw" pathLength={1} d={ground.d} style={{ "--d": tl.ground + "ms" } as React.CSSProperties} />
              <path className="dcf-tufts dcf-fade" d={ground.tufts} style={{ "--d": tl.ground + 500 + "ms" } as React.CSSProperties} />
              {ground.pebbles.map((pb, k) => (
                <ellipse key={k} className="dcf-pebble dcf-fade" cx={pb.x} cy={pb.y} rx={pb.r * 1.5} ry={pb.r} style={{ "--d": tl.ground + 600 + "ms" } as React.CSSProperties} />
              ))}
            </g>

            {chars.map((c, i) =>
              c === " " ? null : (
                <g key={i} className="dcf-letter" style={{ "--d": tl.letter(i) + "ms", "--r": ((hash(i * 2.3) - 0.5) * 9).toFixed(2) + "deg" } as React.CSSProperties}>
                  <g className="dcf-glyph">
                    <text x={layout.x[i]} y={0} fontSize={FONT_SIZE} fontWeight={900} style={{ fontFamily: DEFAULT_FONT }} filter={"url(#" + uid + "-ink)"}>
                      {c}
                    </text>
                  </g>
                  <path
                    className="dcf-dust"
                    d={
                      "M" + (layout.x[i] - 6) + " -6 l-16 -6 M" + (layout.x[i] - 4) + " -16 l-12 -12 M" + (layout.x[i] + 6) + " -6 l16 -6 M" + (layout.x[i] + 4) + " -16 l12 -12"
                    }
                  />
                </g>
              )
            )}
          </svg>
        </div>

        {doodleList.length > 0 && (
          <div className="dcf-doodles" aria-hidden="true">
            {doodleList.map((d, k) => (
              <div
                key={k}
                className="dcf-doodle"
                ref={(el) => void (doodleRefs.current[k] = el)}
                style={{ width: d.size, height: d.size, marginLeft: -d.size / 2, marginTop: -d.size / 2 }}
                onPointerDown={() => popDoodle(k)}
              >
                <span className="dcf-doodle-in" style={{ "--d": tl.doodles + k * 70 + "ms" } as React.CSSProperties}>
                  <svg viewBox="-16 -16 32 32" width={d.size} height={d.size}>
                    <Doodle kind={d.kind} />
                  </svg>
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="dcf-cta">
          <p className="dcf-tagline">
            {words.map((w, k) => (
              <span key={k} className="dcf-word" style={{ "--d": tl.word(k) + "ms" } as React.CSSProperties}>
                {w}{" "}
              </span>
            ))}
          </p>
          {actions.length > 0 && (
            <div className="dcf-actions">
              {actions.map((a, k) => {
                const cls = "dcf-action dcf-action-" + (a.variant ?? "solid");
                const style = { "--d": tl.action(k) + "ms" } as React.CSSProperties;
                return a.href ? (
                  <a key={a.label} href={a.href} className={cls} style={style}>
                    {a.label}
                  </a>
                ) : (
                  <button key={a.label} type="button" onClick={a.onClick} className={cls} style={style}>
                    {a.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className="dcf-bottom dcf-rise" style={{ "--d": tl.total + "ms" } as React.CSSProperties}>
        <p className="dcf-copyright">{copyright}</p>
        {legal.length > 0 && (
          <ul className="dcf-legal">
            {legal.map((l) => (
              <li key={l.label}>
                <FooterLinkItem link={l} />
              </li>
            ))}
          </ul>
        )}
        {backToTop && (
          <button type="button" onClick={toTop} className="dcf-totop">
            Back to top
          </button>
        )}
      </div>
    </footer>
  );
}

// ---- styles ------------------------------------------------------------------
// MinedIt's own palette (black + sunflower-yellow), not the original demo's
// configurable preset system — this footer only ever ships on one site.

const CSS = `
.dcf {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: #050505;
  color: #ffffff;
  border-top: 1px solid rgba(255,255,255,0.06);
  font-family: var(--font-space-grotesk, inherit);
}

.dcf-rise { opacity: 0; transform: translateY(16px); transition: opacity 500ms ease-out var(--d, 0ms), transform 500ms cubic-bezier(0.22,1,0.36,1) var(--d, 0ms); }
.dcf[data-play="1"] .dcf-rise { opacity: 1; transform: translateY(0); }

.dcf-top { padding: 3rem 1.5rem 1.5rem; margin: 0 auto; width: 100%; max-width: 72rem; }
.dcf-brandname { font-family: var(--font-display, inherit); font-size: 1.1rem; font-weight: 800; letter-spacing: -0.01em; }
.dcf-blurb { margin-top: 0.75rem; max-width: 32rem; font-size: 0.9rem; line-height: 1.5; color: rgba(255,255,255,0.55); }

.dcf-cols { margin-top: 2rem; display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 2rem; max-width: 28rem; }
.dcf-coltitle { font-family: var(--font-jetbrains-mono, monospace); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.15em; color: rgba(255,255,255,0.4); margin-bottom: 0.75rem; }
.dcf-col ul { display: flex; flex-direction: column; gap: 0.5rem; list-style: none; padding: 0; margin: 0; }
.dcf-link { position: relative; display: inline-flex; width: fit-content; font-size: 0.875rem; color: rgba(255,255,255,0.75); text-decoration: none; }
.dcf-link:hover, .dcf-link:focus-visible { color: #eab308; }
.dcf-squiggle { position: absolute; left: 0; right: 0; bottom: -3px; width: 100%; height: 6px; overflow: visible; }
.dcf-squiggle path { fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; pathLength: 1; stroke-dasharray: 1; stroke-dashoffset: 1; transition: stroke-dashoffset 300ms ease-out; }
.dcf-link:hover .dcf-squiggle path, .dcf-link:focus-visible .dcf-squiggle path { stroke-dashoffset: 0; }

.dcf-world { position: relative; flex: 1; display: flex; flex-direction: column; justify-content: center; min-height: 0; padding: 1rem 1.5rem 0; }
.dcf-stage { position: relative; margin: 0 auto; width: 100%; max-width: 72rem; }
.dcf-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
.dcf-svg { display: block; width: 100%; height: auto; overflow: visible; }

.dcf-ground path { fill: none; stroke: rgba(255,255,255,0.35); stroke-width: 2.5; stroke-linecap: round; }
.dcf-ground .dcf-tufts, .dcf-ground .dcf-pebble { stroke-width: 1.5; }
.dcf-ground .dcf-pebble { fill: rgba(255,255,255,0.18); stroke: none; }
.dcf-draw { stroke-dasharray: 1; stroke-dashoffset: 1; transition: stroke-dashoffset 900ms cubic-bezier(0.22,1,0.36,1) var(--d, 0ms); }
.dcf[data-play="1"] .dcf-draw { stroke-dashoffset: 0; }
.dcf-fade { opacity: 0; transition: opacity 500ms ease-out var(--d, 0ms); }
.dcf[data-play="1"] .dcf-fade { opacity: 1; }

.dcf-letter { transform-origin: center bottom; }
.dcf-glyph { transform: scale(0) rotate(var(--r, 0deg)); transform-origin: center bottom; transition: transform 480ms cubic-bezier(0.34,1.56,0.64,1) var(--d, 0ms); }
.dcf[data-play="1"] .dcf-glyph { transform: scale(1) rotate(0deg); }
.dcf-letter text { fill: #ffffff; filter: var(--dcf-boil, none); }
.dcf-letter:hover .dcf-glyph { transform: scale(1) rotate(calc(var(--r, 0deg) * 0.4)); transition-duration: 220ms; }
.dcf-dust { fill: none; stroke: rgba(255,255,255,0.5); stroke-width: 3; stroke-linecap: round; opacity: 0; transition: opacity 260ms ease-out calc(var(--d, 0ms) + 200ms), transform 420ms ease-out calc(var(--d, 0ms) + 200ms); transform: scale(0.6); transform-origin: center; }
.dcf[data-play="1"] .dcf-dust { opacity: 0.8; transform: scale(1); }

.dcf-doodles { position: absolute; inset: 0; pointer-events: none; overflow: visible; z-index: 0; }
.dcf-doodle { position: absolute; top: 0; left: 0; pointer-events: auto; cursor: pointer; will-change: transform; }
.dcf-doodle-in { display: block; opacity: 0; transform: scale(0.3); transition: opacity 400ms ease-out var(--d, 0ms), transform 400ms cubic-bezier(0.34,1.56,0.64,1) var(--d, 0ms); }
.dcf[data-play="1"] .dcf-doodle-in { opacity: 0.9; transform: scale(1); }

.dcf-cta { position: relative; z-index: 1; margin: 2.5rem auto 0; max-width: 72rem; text-align: center; padding-bottom: 1rem; }
.dcf-tagline { font-size: 1.1rem; font-weight: 600; color: rgba(255,255,255,0.85); }
.dcf-word { display: inline-block; opacity: 0; transform: translateY(8px); transition: opacity 350ms ease-out var(--d, 0ms), transform 350ms ease-out var(--d, 0ms); }
.dcf[data-play="1"] .dcf-word { opacity: 1; transform: translateY(0); }

.dcf-actions { margin-top: 1.25rem; display: flex; flex-wrap: wrap; justify-content: center; gap: 0.75rem; }
.dcf-action { display: inline-flex; align-items: center; justify-content: center; padding: 0.6rem 1.25rem; border-radius: 0.75rem; font-size: 0.875rem; font-weight: 700; text-decoration: none; cursor: pointer; opacity: 0; transform: translateY(8px); transition: opacity 350ms ease-out var(--d, 0ms), transform 350ms ease-out var(--d, 0ms), background-color 150ms, border-color 150ms, color 150ms; }
.dcf[data-play="1"] .dcf-action { opacity: 1; transform: translateY(0); }
.dcf-action-solid { background: #eab308; color: #000000; border: 1px solid #eab308; }
.dcf-action-solid:hover { opacity: 0.9; }
.dcf-action-outline { background: transparent; color: #ffffff; border: 1px solid rgba(255,255,255,0.2); }
.dcf-action-outline:hover { background: rgba(255,255,255,0.06); }

.dcf-bottom { position: relative; z-index: 1; margin-top: 2rem; padding: 1.25rem 1.5rem 2rem; max-width: 72rem; margin-left: auto; margin-right: auto; width: 100%; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 1rem; border-top: 1px solid rgba(255,255,255,0.08); font-size: 0.75rem; color: rgba(255,255,255,0.4); }
.dcf-legal { display: flex; gap: 1.25rem; list-style: none; padding: 0; margin: 0; }
.dcf-totop { background: none; border: none; color: rgba(255,255,255,0.4); font-size: 0.75rem; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
.dcf-totop:hover { color: #eab308; }

@media (max-width: 640px) {
  .dcf-cols { grid-template-columns: 1fr 1fr; }
}

@media (prefers-reduced-motion: reduce) {
  .dcf-rise, .dcf-glyph, .dcf-fade, .dcf-word, .dcf-action, .dcf-doodle-in { transition: none !important; opacity: 1 !important; transform: none !important; }
  .dcf-draw { transition: none !important; stroke-dashoffset: 0 !important; }
  .dcf-letter text { filter: none !important; }
  .dcf-doodles { display: none; }
}
`;
