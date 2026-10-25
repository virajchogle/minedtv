"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import { neonVars, toNeonRgb, type NeonColor } from "@/lib/neon";

const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? React.useLayoutEffect : React.useEffect;

export type GlowChartX = string | number | Date;
export type GlowChartFormatContext = "axis" | "tooltip";

export interface GlowChartPoint {
  x: GlowChartX;
  /** `null` leaves a gap in the line. */
  y: number | null;
}

export interface GlowChartSeries {
  name: string;
  data: GlowChartPoint[];
  /** Palette name or hex. The first series defaults to `--neon`. */
  color?: NeonColor;
  /** Per-series override inside a line or area chart. */
  type?: "line" | "area";
  /** Draw it quietly, without glow: a comparison or baseline series. */
  muted?: boolean;
}

export interface GlowChartThreshold {
  y: number;
  label?: string;
  color?: NeonColor;
}

type ChartType = "line" | "area" | "bar";
type XKind = "date" | "number" | "category";

// Series after the first fall back to these, in this order.
const FALLBACK_COLORS = [
  "230 237 247",
  "251 191 36",
  "168 85 247",
  "52 211 153",
  "255 95 162",
  "79 139 255",
];

const PAD_TOP = 10;
const AXIS_BAND = 26;
const EASE = "cubic-bezier(0.23,1,0.32,1)";

const css = `
@keyframes nk-glow-chart-reveal { from { clip-path: inset(-12px calc(100% - var(--nk-gc-left)) -12px -12px); } to { clip-path: inset(-12px -12px -12px -12px); } }
@keyframes nk-glow-chart-beam { 0% { transform: translateX(0); opacity: 0; } 8% { opacity: 1; } 80% { opacity: 1; } 100% { transform: translateX(100%); opacity: 0; } }
@keyframes nk-glow-chart-grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
@keyframes nk-glow-chart-ignite { 0% { opacity: 0.25; } 30% { opacity: 1; } 45% { opacity: 0.55; } 70%, 100% { opacity: 1; } }
[data-reveal="armed"] .nk-glow-chart-reveal { clip-path: inset(0 100% 0 0); }
[data-reveal="armed"] .nk-glow-chart-bar { transform: scaleY(0); }
[data-reveal="armed"] .nk-glow-chart-beam { opacity: 0; }
[data-reveal="play"] .nk-glow-chart-reveal { animation: nk-glow-chart-reveal 1150ms cubic-bezier(0.65,0,0.35,1) both, nk-glow-chart-ignite 420ms linear 1150ms; }
[data-reveal="play"] .nk-glow-chart-beam { animation: nk-glow-chart-beam 1150ms cubic-bezier(0.65,0,0.35,1) both; }
[data-reveal="play"] .nk-glow-chart-bar { animation: nk-glow-chart-grow 640ms ${EASE} both; }
.nk-glow-chart-beam { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  [data-reveal] .nk-glow-chart-reveal, [data-reveal] .nk-glow-chart-bar { animation: none; clip-path: none; transform: none; }
  [data-reveal] .nk-glow-chart-beam { animation: none; opacity: 0; }
}
`;

/* -------------------------------------------------------------------------------------------------
 * Data helpers
 * -----------------------------------------------------------------------------------------------*/

const compactNumber = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const fullNumber = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const dayFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
const weekdayFormat = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
const timeFormat = new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "UTC" });
const monthFormat = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" });
const monthYearFormat = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
const longMonthFormat = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" });

// Node and browsers disagree on which invisible space Intl puts in some outputs.
const clean = (text: string) => text.replace(/[   ]/g, " ");

function defaultYFormat(value: number, context: GlowChartFormatContext) {
  return clean(context === "axis" ? compactNumber.format(value) : fullNumber.format(value));
}

function makeDefaultXFormat(xs: GlowChartX[], kind: XKind) {
  if (kind === "number") return (x: GlowChartX) => clean(fullNumber.format(x as number));
  if (kind === "category") return (x: GlowChartX) => String(x);

  const dates = xs as Date[];
  const span = dates.length > 1 ? dates[dates.length - 1].getTime() - dates[0].getTime() : 0;
  const hasTime = dates.some((d) => d.getUTCHours() !== 0 || d.getUTCMinutes() !== 0);
  const monthly = !hasTime && dates.length > 1 && dates.every((d) => d.getUTCDate() === 1);
  const day = 86_400_000;

  return (x: GlowChartX, context: GlowChartFormatContext) => {
    const date = x as Date;
    if (monthly) {
      if (context === "tooltip") return clean(longMonthFormat.format(date));
      const yearly = span > 330 * day && date.getUTCMonth() === 0;
      return clean((yearly ? monthYearFormat : monthFormat).format(date));
    }
    if (hasTime) {
      if (context === "axis" && span <= 2 * day) return clean(timeFormat.format(date));
      if (context === "axis") return clean(dayFormat.format(date));
      return clean(`${dayFormat.format(date)}, ${timeFormat.format(date)}`);
    }
    return clean((context === "axis" ? dayFormat : weekdayFormat).format(date));
  };
}

const keyOf = (x: GlowChartX) =>
  x instanceof Date ? `d${x.getTime()}` : `${typeof x}:${String(x)}`;

const numeric = (x: GlowChartX) => (x instanceof Date ? x.getTime() : (x as number));

function isSeriesList(data: GlowChartPoint[] | GlowChartSeries[]): data is GlowChartSeries[] {
  return data.length > 0 && typeof data[0] === "object" && data[0] !== null && "data" in data[0];
}

type ModelSeries = {
  name: string;
  named: boolean;
  colorVar: string;
  rgb: string;
  type: ChartType;
  muted: boolean;
  values: (number | null)[];
};

function buildModel(data: GlowChartPoint[] | GlowChartSeries[], type: ChartType) {
  const list: GlowChartSeries[] = isSeriesList(data)
    ? data
    : data.length > 0
      ? [{ name: "", data: data as GlowChartPoint[] }]
      : [];

  const all = list.flatMap((s) => s.data.map((p) => p.x));
  const kind: XKind =
    all.length > 0 && all.every((x) => x instanceof Date)
      ? "date"
      : all.length > 0 && all.every((x) => typeof x === "number")
        ? "number"
        : "category";

  const byKey = new Map<string, GlowChartX>();
  for (const x of all) if (!byKey.has(keyOf(x))) byKey.set(keyOf(x), x);
  const xs = [...byKey.values()];
  if (kind !== "category") xs.sort((a, b) => numeric(a) - numeric(b));
  const keys = xs.map(keyOf);

  let fallback = 0;
  const series: ModelSeries[] = list.map((s, index) => {
    const lookup = new Map<string, number | null>();
    for (const p of s.data) {
      lookup.set(keyOf(p.x), typeof p.y === "number" && Number.isFinite(p.y) ? p.y : null);
    }
    const rgb = s.color
      ? toNeonRgb(s.color)
      : index === 0
        ? ""
        : FALLBACK_COLORS[fallback++ % FALLBACK_COLORS.length];
    return {
      name: s.name,
      named: s.name.trim() !== "",
      colorVar: `--nk-gc-c${index}`,
      rgb,
      type: type === "bar" ? "bar" : (s.type ?? type),
      muted: Boolean(s.muted),
      values: keys.map((key) => lookup.get(key) ?? null),
    };
  });

  return { kind, xs, series };
}

function niceStep(range: number, count: number) {
  const raw = range / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / magnitude;
  const nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
  return nice * magnitude;
}

function computeDomain(
  series: ModelSeries[],
  type: ChartType,
  tickCount: number,
  fixed?: [number, number],
  thresholds?: GlowChartThreshold[],
) {
  const values = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  for (const t of thresholds ?? []) values.push(t.y);

  if (fixed) {
    const [lo, hi] = fixed[0] < fixed[1] ? fixed : [fixed[1], fixed[0]];
    const step = niceStep(hi - lo || 1, tickCount);
    const ticks: number[] = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) ticks.push(+v.toFixed(10));
    return { min: lo, max: hi, ticks };
  }

  let lo = values.length ? Math.min(...values) : 0;
  let hi = values.length ? Math.max(...values) : 1;
  if (type !== "line") {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  } else {
    const pad = (hi - lo) * 0.12;
    lo -= pad;
    hi += pad;
  }
  if (hi === lo) {
    hi += 1;
    if (type === "line") lo -= 1;
  }
  const step = niceStep(hi - lo, tickCount);
  const min = Math.floor(lo / step + 1e-9) * step;
  const max = Math.ceil(hi / step - 1e-9) * step;
  const ticks: number[] = [];
  for (let v = min; v <= max + step * 1e-9; v += step) ticks.push(+v.toFixed(10));
  return { min, max, ticks };
}

type Pt = [number, number];

function linearPath(points: Pt[]) {
  return points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join("");
}

// Monotone cubic interpolation (Fritsch–Carlson, as in d3's curveMonotoneX):
// smooth, but never overshoots a peak or dips below a trough.
function smoothPath(points: Pt[]) {
  const n = points.length;
  if (n < 3) return linearPath(points);
  const slopes: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    const dx = points[i + 1][0] - points[i][0];
    slopes.push(dx === 0 ? 0 : (points[i + 1][1] - points[i][1]) / dx);
  }
  const tangents: number[] = new Array(n);
  for (let i = 1; i < n - 1; i++) {
    const s0 = slopes[i - 1];
    const s1 = slopes[i];
    const h0 = points[i][0] - points[i - 1][0];
    const h1 = points[i + 1][0] - points[i][0];
    if (s0 * s1 <= 0) tangents[i] = 0;
    else {
      const p = (s0 * h1 + s1 * h0) / (h0 + h1);
      tangents[i] = (Math.sign(s0) + Math.sign(s1)) * Math.min(Math.abs(s0), Math.abs(s1), 0.5 * Math.abs(p));
    }
  }
  tangents[0] = (3 * slopes[0] - tangents[1]) / 2;
  tangents[n - 1] = (3 * slopes[n - 2] - tangents[n - 2]) / 2;

  let d = `M${points[0][0].toFixed(2)},${points[0][1].toFixed(2)}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    const h = (x1 - x0) / 3;
    d += `C${(x0 + h).toFixed(2)},${(y0 + tangents[i] * h).toFixed(2)},${(x1 - h).toFixed(2)},${(y1 - tangents[i + 1] * h).toFixed(2)},${x1.toFixed(2)},${y1.toFixed(2)}`;
  }
  return d;
}

// A bar with a rounded data end and a square foot on the baseline.
function barPath(x: number, width: number, yValue: number, yBase: number, radius: number) {
  const height = Math.abs(yBase - yValue);
  if (height < 0.5) return "";
  const r = Math.min(radius, width / 2, height);
  const up = yValue < yBase;
  const end = up ? yValue + r : yValue - r;
  const sweep = up ? 1 : 0;
  return (
    `M${x},${yBase}V${end}` +
    `A${r},${r} 0 0 ${sweep} ${x + r},${yValue}` +
    `H${x + width - r}` +
    `A${r},${r} 0 0 ${sweep} ${x + width},${end}` +
    `V${yBase}Z`
  );
}

/* -------------------------------------------------------------------------------------------------
 * GlowChart
 * -----------------------------------------------------------------------------------------------*/

export interface GlowChartProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "color"> {
  /** Points for one series, or a list of named series. */
  data: GlowChartPoint[] | GlowChartSeries[];
  type?: ChartType;
  /** Color of the first series. Inherits `--neon-accent` when omitted. */
  color?: NeonColor;
  curve?: "smooth" | "linear";
  /** Horizontal gridlines at each y tick. */
  grid?: boolean;
  /** Tick labels on both axes. */
  axis?: boolean;
  /** Crosshair, tooltip and keyboard reading. */
  tooltip?: boolean;
  /** Series key above the plot. Defaults to on for two or more series. */
  legend?: boolean;
  yFormat?: (value: number, context: GlowChartFormatContext) => string;
  xFormat?: (x: GlowChartX, context: GlowChartFormatContext) => string;
  /** Height of the plot, x-axis labels included, in pixels. */
  height?: number;
  /** Fixed y range. By default area and bar charts start at zero and lines fit the data. */
  yDomain?: [number, number];
  /** Rough number of y ticks. */
  yTicks?: number;
  /** Horizontal reference lines, like an SLO or a target. */
  thresholds?: GlowChartThreshold[];
  /** What the chart shows. Leads the accessible summary and captions the data table. */
  label?: string;
  /** Header for the x column of the data table. */
  xLabel?: string;
  /** Draw the series in when the chart scrolls into view. */
  animate?: boolean;
  /** The point under the crosshair, or null when nothing is active. */
  onActiveIndexChange?: (index: number | null) => void;
}

const GlowChart = React.forwardRef<HTMLDivElement, GlowChartProps>(
  (
    {
      className,
      style,
      color,
      data,
      type = "area",
      curve = "smooth",
      grid = true,
      axis = true,
      tooltip = true,
      legend,
      yFormat,
      xFormat,
      height = 240,
      yDomain,
      yTicks = 4,
      thresholds,
      label,
      xLabel,
      animate = true,
      onActiveIndexChange,
      "aria-label": ariaLabel,
      ...props
    },
    ref,
  ) => {
    const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
    const rootRef = React.useRef<HTMLDivElement>(null);
    const plotRef = React.useRef<HTMLDivElement>(null);
    const keyboardRef = React.useRef(false);
    const setRefs = React.useCallback(
      (node: HTMLDivElement | null) => {
        rootRef.current = node;
        if (typeof ref === "function") ref(node);
        else if (ref) ref.current = node;
      },
      [ref],
    );

    const [measured, setMeasured] = React.useState<number | null>(null);
    const [inView, setInView] = React.useState(false);
    const [active, setActiveState] = React.useState<number | null>(null);
    const [shown, setShown] = React.useState<number | null>(null);
    const [announcement, setAnnouncement] = React.useState("");

    const model = React.useMemo(() => buildModel(data, type), [data, type]);
    const { xs, series, kind } = model;
    const n = xs.length;
    const fx = React.useMemo(
      () => xFormat ?? makeDefaultXFormat(xs, kind),
      [xFormat, xs, kind],
    );
    const fy = yFormat ?? defaultYFormat;
    const domain = React.useMemo(
      () => computeDomain(series, type, yTicks, yDomain, thresholds),
      [series, type, yTicks, yDomain, thresholds],
    );

    useIsomorphicLayoutEffect(() => {
      const node = plotRef.current;
      if (!node) return;
      const measure = () => {
        // Layout width, not the painted one: an ancestor mid scale-in (a dialog opening at 0.96)
        // would otherwise bake its transform into the geometry.
        const next = node.offsetWidth || Math.round(node.getBoundingClientRect().width);
        if (next > 0) setMeasured((previous) => (previous === next ? previous : next));
      };
      measure();
      if (typeof ResizeObserver === "undefined") {
        window.addEventListener("resize", measure);
        return () => window.removeEventListener("resize", measure);
      }
      const observer = new ResizeObserver(measure);
      observer.observe(node);
      return () => observer.disconnect();
    }, []);

    React.useEffect(() => {
      const node = rootRef.current;
      if (!animate || !node) return;
      if (typeof IntersectionObserver === "undefined") {
        const frame = requestAnimationFrame(() => setInView(true));
        return () => cancelAnimationFrame(frame);
      }
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            setInView(true);
            observer.disconnect();
          }
        },
        { threshold: 0.35 },
      );
      observer.observe(node);
      return () => observer.disconnect();
    }, [animate]);

    /* Geometry ---------------------------------------------------------------------------------- */

    const W = measured ?? 640;
    const bar = type === "bar";
    const yLabels = domain.ticks.map((t) => fy(t, "axis"));
    const gutter = axis ? Math.max(28, Math.max(...yLabels.map((t) => t.length)) * 6.6 + 12) : 0;
    const left = gutter;
    const right = bar ? 0 : 12;
    const top = PAD_TOP;
    const bottom = height - (axis ? AXIS_BAND : 8);
    const innerW = Math.max(1, W - left - right);
    const innerH = Math.max(1, bottom - top);

    const yPx = (value: number) =>
      top + (1 - (value - domain.min) / (domain.max - domain.min || 1)) * innerH;
    const baseValue = Math.min(Math.max(0, domain.min), domain.max);
    const baseY = yPx(baseValue);

    const band = innerW / Math.max(1, n);
    const xPos = React.useMemo(() => {
      if (n === 0) return [] as number[];
      if (bar) return xs.map((_, i) => left + band * (i + 0.5));
      if (n === 1) return [left + innerW / 2];
      if (kind === "category") return xs.map((_, i) => left + (i / (n - 1)) * innerW);
      const lo = numeric(xs[0]);
      const span = numeric(xs[n - 1]) - lo || 1;
      return xs.map((x) => left + ((numeric(x) - lo) / span) * innerW);
    }, [xs, n, bar, band, left, innerW, kind]);

    const primary = series.findIndex((s) => !s.muted);

    /* Interaction ------------------------------------------------------------------------------ */

    const activeIndex = active !== null && active < n ? active : null;
    const shownIndex = activeIndex ?? (shown !== null && shown < n ? shown : null);

    const readout = (index: number) => {
      const values = series.map((s) => {
        const v = s.values[index];
        const text = v === null ? "no data" : fy(v, "tooltip");
        return s.named ? `${s.name} ${text}` : text;
      });
      return `${fx(xs[index], "tooltip")}: ${values.join(", ")}`;
    };

    const setActive = (index: number | null, fromKeyboard = false) => {
      if (index === activeIndex && !fromKeyboard) return;
      if (index !== null && index !== shown) setShown(index);
      if (fromKeyboard && index !== null) setAnnouncement(readout(index));
      if (index === activeIndex) return;
      setActiveState(index);
      onActiveIndexChange?.(index);
    };

    const indexAt = (clientX: number) => {
      const node = plotRef.current;
      if (!node || n === 0) return null;
      const rect = node.getBoundingClientRect();
      const px = ((clientX - rect.left) / (rect.width || W)) * W;
      if (bar) return Math.min(n - 1, Math.max(0, Math.floor((px - left) / band)));
      let lo = 0;
      let hi = n - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (xPos[mid] < px) lo = mid;
        else hi = mid;
      }
      return Math.abs(xPos[lo] - px) <= Math.abs(xPos[hi] - px) ? lo : hi;
    };

    const interactive = tooltip && n > 0;

    const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!interactive) return;
      const current = activeIndex ?? n - 1;
      const page = Math.max(1, Math.round(n / 10));
      let next: number | null;
      switch (event.key) {
        case "ArrowRight":
          next = activeIndex === null ? current : Math.min(n - 1, current + 1);
          break;
        case "ArrowLeft":
          next = activeIndex === null ? current : Math.max(0, current - 1);
          break;
        case "PageUp":
          next = Math.min(n - 1, current + page);
          break;
        case "PageDown":
          next = Math.max(0, current - page);
          break;
        case "Home":
          next = 0;
          break;
        case "End":
          next = n - 1;
          break;
        case "Escape":
          if (activeIndex === null) return;
          next = null;
          break;
        default:
          return;
      }
      event.preventDefault();
      keyboardRef.current = true;
      setActive(next, true);
    };

    /* Text alternatives ------------------------------------------------------------------------ */

    const summary = React.useMemo(() => {
      const typeName = type === "bar" ? "Bar chart" : type === "line" ? "Line chart" : "Area chart";
      if (n === 0) return `${label ? `${label}. ` : ""}${typeName} with no data.`;
      const range =
        n === 1
          ? `1 point, ${fx(xs[0], "tooltip")}`
          : `${n} points from ${fx(xs[0], "tooltip")} to ${fx(xs[n - 1], "tooltip")}`;
      const parts = series.map((s) => {
        const values = s.values.filter((v): v is number => v !== null);
        const low = fy(Math.min(...values), "tooltip");
        const high = fy(Math.max(...values), "tooltip");
        const latest = fy(values[values.length - 1], "tooltip");
        const stats = values.length ? `low ${low}, high ${high}, latest ${latest}.` : "no data.";
        return s.named ? `${s.name}: ${stats}` : stats.charAt(0).toUpperCase() + stats.slice(1);
      });
      return `${label ? `${label}. ` : ""}${typeName}, ${range}. ${parts.join(" ")}`;
    }, [type, n, label, fx, fy, xs, series]);

    const columnHeader =
      xLabel ?? (kind === "date" ? "Date" : kind === "number" ? "Value" : "Label");

    /* Paths ------------------------------------------------------------------------------------ */

    const build = curve === "smooth" ? smoothPath : linearPath;
    const paths = bar
      ? []
      : series.map((s) => {
          const segments: Pt[][] = [];
          let run: Pt[] = [];
          s.values.forEach((v, i) => {
            if (v === null) {
              if (run.length) segments.push(run);
              run = [];
            } else run.push([xPos[i], yPx(v)]);
          });
          if (run.length) segments.push(run);
          const area = segments
            .filter((seg) => seg.length > 1)
            .map((seg) => `${build(seg)}L${seg[seg.length - 1][0].toFixed(2)},${baseY.toFixed(2)}L${seg[0][0].toFixed(2)},${baseY.toFixed(2)}Z`)
            .join("");
          return {
            line: segments.map(build).join(""),
            area,
            lastIndex: s.values.reduce<number>((acc, v, i) => (v === null ? acc : i), -1),
            singles: segments.filter((seg) => seg.length === 1).map((seg) => seg[0]),
          };
        });

    /* Ticks ------------------------------------------------------------------------------------ */

    const xTicks = React.useMemo(() => {
      if (!axis || n === 0) return [] as number[];
      const longest = Math.max(...xs.map((x) => fx(x, "axis").length));
      const spacing = Math.max(64, longest * 6.6 + 20);
      const step = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(innerW / spacing))));
      if (step === 1) return xs.map((_, i) => i);

      // Hourly and monthly data tick on calendar boundaries (00:00, 06:00 · Jan, Apr).
      if (kind === "date" && n > 2) {
        const dates = xs as Date[];
        const gap = (dates[n - 1].getTime() - dates[0].getTime()) / (n - 1);
        const hour = 3_600_000;
        const pick = (units: number[], unitOf: (d: Date) => number | null) => {
          const every = units.find((u) => u >= step) ?? units[units.length - 1] * Math.ceil(step / units[units.length - 1]);
          return dates.flatMap((d, i) => {
            const unit = unitOf(d);
            return unit !== null && unit % every === 0 ? [i] : [];
          });
        };
        if (Math.abs(gap - hour) < hour * 0.1) {
          const ticks = pick([1, 2, 3, 4, 6, 8, 12, 24], (d) => (d.getUTCMinutes() === 0 ? d.getUTCHours() : null));
          if (ticks.length > 1) return ticks;
        }
        if (dates.every((d) => d.getUTCDate() === 1 && d.getUTCHours() === 0)) {
          const ticks = pick([1, 2, 3, 4, 6, 12], (d) => d.getUTCMonth());
          if (ticks.length > 1) return ticks;
        }
      }

      // Otherwise count back from the newest point so the latest value always has a label.
      const picks: number[] = [];
      for (let i = n - 1; i >= 0; i -= step) picks.unshift(i);
      return picks;
    }, [axis, n, xs, fx, innerW, kind]);

    const showLegend = legend ?? series.length > 1;
    const revealKey = `${series.length}-${n}-${type}`;
    const pct = (x: number) => `${(x / W) * 100}%`;

    const seriesStyle = Object.fromEntries(
      series.map((s, i) => [s.colorVar, s.rgb || (i === 0 ? "var(--neon)" : FALLBACK_COLORS[0])]),
    );

    const barCount = series.length;
    const groupGap = 2;
    const barWidth =
      barCount > 0
        ? Math.max(2, Math.min(barCount > 1 ? 16 : 24, (band * 0.64 - groupGap * (barCount - 1)) / barCount))
        : 0;
    const groupWidth = barWidth * barCount + groupGap * (barCount - 1);

    const shownX = shownIndex !== null ? xPos[shownIndex] : 0;
    const flip = shownX > left + innerW * 0.62;

    return (
      <div
        ref={setRefs}
        style={neonVars(color, { ...seriesStyle, ...style } as React.CSSProperties)}
        className={cn("[--neon:var(--neon-accent,34_211_238)]", "relative w-full min-w-0", className)}
        {...props}
      >
        <style>{css}</style>

        {showLegend && (
          <ul aria-hidden className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
            {series.map((s) => (
              <li key={s.colorVar} className="flex items-center gap-2 text-xs text-white/55">
                {s.type === "bar" ? (
                  <span
                    className="size-2 rounded-[2px]"
                    style={{
                      background: `rgb(var(${s.colorVar}) / ${s.muted ? 0.45 : 0.9})`,
                      boxShadow: s.muted ? undefined : `0 0 6px rgb(var(${s.colorVar}) / calc(0.6 * var(--neon-glow, 1)))`,
                    }}
                  />
                ) : (
                  <span
                    className="h-0.5 w-3.5 rounded-full"
                    style={{
                      background: `rgb(var(${s.colorVar}) / ${s.muted ? 0.45 : 1})`,
                      boxShadow: s.muted ? undefined : `0 0 6px rgb(var(${s.colorVar}) / calc(0.7 * var(--neon-glow, 1)))`,
                    }}
                  />
                )}
                {s.name}
              </li>
            ))}
          </ul>
        )}

        <div
          ref={plotRef}
          role="img"
          aria-label={ariaLabel ?? summary}
          aria-describedby={interactive ? `${uid}-hint` : undefined}
          tabIndex={interactive ? 0 : undefined}
          data-reveal={animate ? (inView ? "play" : "armed") : undefined}
          onKeyDown={handleKeyDown}
          onFocus={(event) => {
            if (!interactive) return;
            let visible = true;
            try {
              visible = event.currentTarget.matches(":focus-visible");
            } catch {
              visible = true;
            }
            if (visible) {
              keyboardRef.current = true;
              setActive(activeIndex ?? n - 1, true);
            }
          }}
          onBlur={() => {
            keyboardRef.current = false;
            setActive(null);
          }}
          onPointerMove={(event) => {
            if (!interactive) return;
            keyboardRef.current = false;
            setActive(indexAt(event.clientX));
          }}
          onPointerDown={(event) => {
            if (interactive && event.pointerType !== "mouse") setActive(indexAt(event.clientX));
          }}
          onPointerLeave={() => {
            if (!keyboardRef.current) setActive(null);
          }}
          style={{ height, "--nk-gc-left": pct(left) } as React.CSSProperties}
          className={cn(
            "relative select-none rounded-md outline-none [touch-action:pan-y]",
            "focus-visible:ring-2 focus-visible:ring-[rgb(var(--neon)/0.6)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#05060a]",
          )}
        >
          {/* Grid, reference lines and the active band */}
          <svg
            aria-hidden
            viewBox={`0 0 ${W} ${height}`}
            preserveAspectRatio="none"
            className="pointer-events-none absolute inset-0 size-full overflow-visible"
          >
            {bar && shownIndex !== null && (
              <rect
                x={left + band * shownIndex}
                y={top}
                width={band}
                height={bottom - top}
                rx={4}
                className="transition-opacity duration-150"
                style={{ fill: "rgb(255 255 255 / 0.035)", opacity: activeIndex !== null ? 1 : 0 }}
              />
            )}
            {grid &&
              domain.ticks.map((tick) => {
                const y = Math.round(yPx(tick)) + 0.5;
                return (
                  <line
                    key={tick}
                    x1={left}
                    x2={W}
                    y1={y}
                    y2={y}
                    shapeRendering="crispEdges"
                    vectorEffect="non-scaling-stroke"
                    style={{ stroke: tick === baseValue ? "rgb(255 255 255 / 0.14)" : "rgb(255 255 255 / 0.06)" }}
                  />
                );
              })}
            {!grid && n > 0 && (
              <line
                x1={left}
                x2={W}
                y1={Math.round(baseY) + 0.5}
                y2={Math.round(baseY) + 0.5}
                shapeRendering="crispEdges"
                vectorEffect="non-scaling-stroke"
                style={{ stroke: "rgb(255 255 255 / 0.12)" }}
              />
            )}
            {thresholds?.map((t, i) => (
              <line
                key={`${t.y}-${i}`}
                x1={left}
                x2={W}
                y1={yPx(t.y)}
                y2={yPx(t.y)}
                strokeDasharray="4 4"
                vectorEffect="non-scaling-stroke"
                style={{ stroke: `rgb(${t.color ? toNeonRgb(t.color) : "255 255 255"} / ${t.color ? 0.6 : 0.3})` }}
              />
            ))}
          </svg>

          {/* The light */}
          <svg
            key={revealKey}
            aria-hidden
            viewBox={`0 0 ${W} ${height}`}
            preserveAspectRatio="none"
            className={cn(
              "pointer-events-none absolute inset-0 size-full overflow-visible",
              !bar && "nk-glow-chart-reveal",
            )}
          >
            <defs>
              <filter
                id={`${uid}-glow`}
                filterUnits="userSpaceOnUse"
                x={-20}
                y={-20}
                width={W + 40}
                height={height + 40}
              >
                <feGaussianBlur stdDeviation={3.5} />
              </filter>
              {series.map((s, i) => (
                <linearGradient key={s.colorVar} id={`${uid}-fill-${i}`} x1="0" y1="0" x2="0" y2="1">
                  {bar ? (
                    <>
                      <stop offset="0" style={{ stopColor: `rgb(var(${s.colorVar}))`, stopOpacity: s.muted ? 0.22 : 0.42 }} />
                      <stop offset="1" style={{ stopColor: `rgb(var(${s.colorVar}))`, stopOpacity: s.muted ? 0.04 : 0.07 }} />
                    </>
                  ) : (
                    <>
                      <stop offset="0" style={{ stopColor: `rgb(var(${s.colorVar}))`, stopOpacity: s.muted ? 0.06 : i === primary ? 0.26 : 0.14 }} />
                      <stop offset="0.6" style={{ stopColor: `rgb(var(${s.colorVar}))`, stopOpacity: s.muted ? 0.02 : 0.06 }} />
                      <stop offset="1" style={{ stopColor: `rgb(var(${s.colorVar}))`, stopOpacity: 0 }} />
                    </>
                  )}
                </linearGradient>
              ))}
              {bar &&
                series.map((s, i) => (
                  <linearGradient key={s.colorVar} id={`${uid}-lit-${i}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" style={{ stopColor: `rgb(var(${s.colorVar}))`, stopOpacity: 0.78 }} />
                    <stop offset="1" style={{ stopColor: `rgb(var(${s.colorVar}))`, stopOpacity: 0.18 }} />
                  </linearGradient>
                ))}
            </defs>

            {!bar &&
              series
                .map((s, i) => ({ s, i, p: paths[i] }))
                .reverse()
                .map(({ s, i, p }) => {
                  const stroke = `rgb(var(${s.colorVar}))`;
                  const core = `color-mix(in srgb, rgb(var(${s.colorVar})) 30%, white)`;
                  const last = p.lastIndex >= 0 ? ([xPos[p.lastIndex], yPx(s.values[p.lastIndex] as number)] as Pt) : null;
                  return (
                    <g key={s.colorVar}>
                      {s.type === "area" && p.area && <path d={p.area} fill={`url(#${uid}-fill-${i})`} />}
                      {!s.muted && (
                        <path
                          d={p.line}
                          fill="none"
                          filter={`url(#${uid}-glow)`}
                          strokeWidth={4}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          style={{ stroke, strokeOpacity: `calc(${i === primary ? 0.8 : 0.45} * var(--neon-glow, 1))` }}
                        />
                      )}
                      <path
                        d={p.line}
                        fill="none"
                        strokeWidth={s.muted ? 1.5 : 2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        style={{ stroke, strokeOpacity: s.muted ? 0.38 : 1 }}
                      />
                      {!s.muted && (
                        <path
                          d={p.line}
                          fill="none"
                          strokeWidth={0.8}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          style={{ stroke: core, strokeOpacity: 0.9 }}
                        />
                      )}
                      {p.singles.map(([x, y]) => (
                        <circle key={x} cx={x} cy={y} r={2.5} style={{ fill: stroke, opacity: s.muted ? 0.45 : 1 }} />
                      ))}
                      {!s.muted && last && (
                        <g>
                          <circle cx={last[0]} cy={last[1]} r={5} filter={`url(#${uid}-glow)`} style={{ fill: stroke, opacity: "calc(0.9 * var(--neon-glow, 1))" }} />
                          <circle cx={last[0]} cy={last[1]} r={2.5} style={{ fill: core }} />
                        </g>
                      )}
                    </g>
                  );
                })}

            {bar &&
              xs.map((x, i) => {
                const lit = activeIndex === i;
                return (
                  <g
                    key={keyOf(x)}
                    className="nk-glow-chart-bar"
                    style={{
                      transformBox: "view-box",
                      transformOrigin: `0px ${baseY}px`,
                      animationDelay: `${Math.min(i * 32, 480)}ms`,
                    }}
                  >
                    {series.map((s, si) => {
                      const v = s.values[i];
                      if (v === null) return null;
                      const bx = xPos[i] - groupWidth / 2 + si * (barWidth + groupGap);
                      const vy = yPx(v);
                      const d = barPath(bx, barWidth, vy, baseY, 4);
                      if (!d) return null;
                      const r = Math.min(4, barWidth / 2);
                      const capY = v >= 0 ? vy + 0.75 : vy - 0.75;
                      const cap = `M${bx + r},${capY}H${bx + barWidth - r}`;
                      return (
                        <g key={s.colorVar}>
                          <path d={d} fill={`url(#${uid}-fill-${si})`} />
                          <path
                            d={d}
                            fill={`url(#${uid}-lit-${si})`}
                            className="transition-opacity duration-150 ease-out"
                            style={{ opacity: lit ? 1 : 0 }}
                          />
                          {!s.muted && (
                            <path
                              d={cap}
                              filter={`url(#${uid}-glow)`}
                              strokeWidth={3}
                              strokeLinecap="round"
                              className="transition-opacity duration-150 ease-out"
                              style={{ stroke: `rgb(var(${s.colorVar}))`, opacity: `calc(${lit ? 1 : 0.55} * var(--neon-glow, 1))` }}
                            />
                          )}
                          <path
                            d={cap}
                            strokeWidth={1.5}
                            strokeLinecap="round"
                            style={{
                              stroke: s.muted
                                ? `rgb(var(${s.colorVar}) / 0.5)`
                                : `color-mix(in srgb, rgb(var(${s.colorVar})) ${lit ? 30 : 60}%, white)`,
                            }}
                          />
                        </g>
                      );
                    })}
                  </g>
                );
              })}
          </svg>

          {/* The beam that draws the line in */}
          {!bar && animate && n > 1 && (
            <div
              key={`beam-${revealKey}`}
              aria-hidden
              className="pointer-events-none absolute right-0 overflow-hidden"
              style={{ left: pct(left), top, height: bottom - top }}
            >
              <div className="nk-glow-chart-beam absolute inset-0">
                <span
                  className="absolute inset-y-0 left-0 w-px"
                  style={{
                    background: "linear-gradient(to bottom, transparent, rgb(var(--nk-gc-c0) / 0.9) 35%, rgb(var(--nk-gc-c0)))",
                    boxShadow: "0 0 8px rgb(var(--nk-gc-c0) / calc(0.8 * var(--neon-glow, 1)))",
                  }}
                />
                <span
                  className="absolute inset-y-0 right-full w-20"
                  style={{ background: "linear-gradient(to right, transparent, rgb(var(--nk-gc-c0) / 0.1))" }}
                />
              </div>
            </div>
          )}

          {/* Crosshair and points */}
          {!bar && shownIndex !== null && (
            <svg
              aria-hidden
              viewBox={`0 0 ${W} ${height}`}
              preserveAspectRatio="none"
              className="pointer-events-none absolute inset-0 size-full overflow-visible transition-opacity duration-150 ease-out"
              style={{ opacity: activeIndex !== null ? 1 : 0 }}
            >
              <defs>
                <linearGradient id={`${uid}-beam`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" style={{ stopColor: "rgb(var(--nk-gc-c0))", stopOpacity: 0 }} />
                  <stop offset="1" style={{ stopColor: "rgb(var(--nk-gc-c0))", stopOpacity: 0.75 }} />
                </linearGradient>
                <radialGradient id={`${uid}-pool`}>
                  <stop offset="0" style={{ stopColor: "rgb(var(--nk-gc-c0))", stopOpacity: "calc(0.55 * var(--neon-glow, 1))" }} />
                  <stop offset="1" style={{ stopColor: "rgb(var(--nk-gc-c0))", stopOpacity: 0 }} />
                </radialGradient>
                <filter id={`${uid}-dot`} x="-2" y="-2" width="5" height="5">
                  <feGaussianBlur stdDeviation={2.5} />
                </filter>
              </defs>
              <g
                className="transition-transform duration-150 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none"
                style={{ transform: `translateX(${shownX}px)` }}
              >
                <line x1={0} x2={0} y1={top} y2={baseY} strokeWidth={1} style={{ stroke: `url(#${uid}-beam)` }} />
                <ellipse cx={0} cy={baseY} rx={22} ry={3.5} fill={`url(#${uid}-pool)`} />
              </g>
              {series.map((s) => {
                const v = s.values[shownIndex];
                if (v === null) return null;
                return (
                  <g
                    key={s.colorVar}
                    className="transition-transform duration-150 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none"
                    style={{ transform: `translate(${shownX}px, ${yPx(v)}px)` }}
                  >
                    {!s.muted && (
                      <circle r={7} filter={`url(#${uid}-dot)`} style={{ fill: `rgb(var(${s.colorVar}))`, opacity: "calc(0.75 * var(--neon-glow, 1))" }} />
                    )}
                    <circle
                      r={4}
                      strokeWidth={2}
                      style={{
                        fill: s.muted
                          ? `rgb(var(${s.colorVar}) / 0.7)`
                          : `color-mix(in srgb, rgb(var(${s.colorVar})) 35%, white)`,
                        stroke: "#05060a",
                      }}
                    />
                  </g>
                );
              })}
            </svg>
          )}

          {/* Axis labels */}
          {axis &&
            domain.ticks.map((tick, i) => (
              <span
                key={tick}
                aria-hidden
                className="pointer-events-none absolute left-0 -translate-y-1/2 pr-2 text-right text-[11px] leading-none tabular-nums text-white/40"
                style={{ top: yPx(tick), width: gutter }}
              >
                {yLabels[i]}
              </span>
            ))}
          {axis &&
            xTicks.map((index) => {
              const x = xPos[index];
              const text = fx(xs[index], "axis");
              // Center under the point unless that would push the label well out of the chart.
              const half = text.length * 3.4;
              const edge = bar ? "center" : x - half < -10 ? "start" : x + half > W + 10 ? "end" : "center";
              return (
                <span
                  key={keyOf(xs[index])}
                  aria-hidden
                  className={cn(
                    "pointer-events-none absolute whitespace-nowrap text-[11px] leading-none tabular-nums text-white/40",
                    edge === "center" && "-translate-x-1/2",
                    edge === "end" && "-translate-x-full",
                  )}
                  style={{ left: pct(x), top: bottom + 10 }}
                >
                  {text}
                </span>
              );
            })}
          {thresholds?.map((t, i) =>
            t.label ? (
              <span
                key={`${t.y}-${i}-label`}
                aria-hidden
                className="pointer-events-none absolute -translate-y-[calc(100%+3px)] whitespace-nowrap rounded-[4px] bg-[#05060a]/70 px-1.5 py-0.5 text-[11px] font-medium leading-4 text-white/60"
                style={{ top: yPx(t.y), left: left + 6 }}
              >
                {t.label}
              </span>
            ) : null,
          )}

          {n === 0 && (
            <span
              aria-hidden
              className="absolute inset-x-0 top-1/2 -translate-y-1/2 text-center text-sm text-white/40"
            >
              No data
            </span>
          )}

          {/* Tooltip */}
          {interactive && shownIndex !== null && (
            <div
              aria-hidden
              className={cn(
                "pointer-events-none absolute left-0 top-0 z-10 min-w-[8.5rem] rounded-lg border border-white/10 bg-[#0a0b11]/95 px-3 py-2.5",
                "shadow-[0_18px_48px_-12px_rgb(0_0_0/0.85),0_0_0_1px_rgb(var(--neon)/0.06),0_0_28px_-10px_rgb(var(--neon)/CALC(0.45*var(--neon-glow,1)))]",
                "transition-[transform,opacity] duration-150 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none",
              )}
              style={{
                opacity: activeIndex !== null ? 1 : 0,
                transform: flip
                  ? `translate(calc(${shownX}px - 100% - 14px), ${top}px)`
                  : `translate(${shownX + 14}px, ${top}px)`,
              }}
            >
              <p className="whitespace-nowrap text-[11px] leading-4 text-white/50">{fx(xs[shownIndex], "tooltip")}</p>
              <ul className="mt-1.5 grid gap-1">
                {series.map((s) => {
                  const v = s.values[shownIndex];
                  return (
                    <li key={s.colorVar} className="flex items-center gap-2 whitespace-nowrap">
                      <span
                        className="h-0.5 w-2.5 shrink-0 rounded-full"
                        style={{
                          background: `rgb(var(${s.colorVar}) / ${s.muted ? 0.5 : 1})`,
                          boxShadow: s.muted ? undefined : `0 0 6px rgb(var(${s.colorVar}) / calc(0.7 * var(--neon-glow, 1)))`,
                        }}
                      />
                      <span className="text-sm font-medium tabular-nums leading-5 text-white/90">
                        {v === null ? "–" : fy(v, "tooltip")}
                      </span>
                      {s.named && <span className="text-xs leading-5 text-white/50">{s.name}</span>}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>

        {interactive && (
          <span id={`${uid}-hint`} className="sr-only">
            Use the left and right arrow keys to read each point.
          </span>
        )}
        <span aria-live="polite" className="sr-only">
          {announcement}
        </span>

        <table className="sr-only">
          <caption>{label ?? "Chart data"}</caption>
          <thead>
            <tr>
              <th scope="col">{columnHeader}</th>
              {series.map((s) => (
                <th key={s.colorVar} scope="col">
                  {s.named ? s.name : label ?? "Value"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {xs.map((x, i) => (
              <tr key={keyOf(x)}>
                <th scope="row">{fx(x, "tooltip")}</th>
                {series.map((s) => {
                  const v = s.values[i];
                  return <td key={s.colorVar}>{v === null ? "No data" : fy(v, "tooltip")}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  },
);
GlowChart.displayName = "GlowChart";

/* -------------------------------------------------------------------------------------------------
 * Sparkline
 * -----------------------------------------------------------------------------------------------*/

export interface SparklineProps
  extends Omit<React.HTMLAttributes<HTMLSpanElement>, "color"> {
  data: number[];
  /** Palette name or any hex color. Inherits `--neon-accent` when omitted. */
  color?: NeonColor;
  /** Pixels, or any CSS length such as "100%". */
  width?: number | string;
  height?: number;
  curve?: "smooth" | "linear";
  /** A soft wash under the line. */
  area?: boolean;
  /** Marks the latest value. */
  dot?: boolean;
  /** The latest-value dot pings, for streaming data. */
  live?: boolean;
  /** Accessible name. Defaults to a summary of the trend. */
  label?: string;
  yFormat?: (value: number) => string;
}

const Sparkline = React.forwardRef<HTMLSpanElement, SparklineProps>(
  (
    {
      className,
      style,
      color,
      data,
      width = 96,
      height = 28,
      curve = "smooth",
      area = true,
      dot = true,
      live = false,
      label,
      yFormat,
      ...props
    },
    ref,
  ) => {
    const uid = React.useId().replace(/[^a-zA-Z0-9_-]/g, "");
    const values = data.filter((v) => Number.isFinite(v));
    const format = yFormat ?? ((v: number) => clean(fullNumber.format(v)));

    const pad = 3;
    const lo = values.length ? Math.min(...values) : 0;
    const hi = values.length ? Math.max(...values) : 1;
    const span = hi - lo || 1;
    const points: Pt[] = values.map((v, i) => [
      values.length > 1 ? (i / (values.length - 1)) * 100 : 50,
      hi === lo ? height / 2 : pad + (1 - (v - lo) / span) * (height - pad * 2),
    ]);
    const line = points.length > 1 ? (curve === "smooth" ? smoothPath(points) : linearPath(points)) : "";
    const wash = line
      ? `${line}L100,${height}L0,${height}Z`
      : "";
    const end = points[points.length - 1];

    const summary =
      label ??
      (values.length === 0
        ? "No data"
        : `Trend of ${values.length} values from ${format(values[0])} to ${format(values[values.length - 1])}, low ${format(lo)}, high ${format(hi)}`);

    return (
      <span
        ref={ref}
        role="img"
        aria-label={summary}
        style={neonVars(color, { width, height, ...style })}
        className={cn(
          "[--neon:var(--neon-accent,34_211_238)]",
          "relative inline-block shrink-0 align-middle",
          className,
        )}
        {...props}
      >
        <span aria-hidden className="absolute inset-y-0 left-0 right-[3px]">
          {area && wash && (
            <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="absolute inset-0 size-full">
              <defs>
                <linearGradient id={`${uid}-wash`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" style={{ stopColor: "rgb(var(--neon))", stopOpacity: 0.24 }} />
                  <stop offset="1" style={{ stopColor: "rgb(var(--neon))", stopOpacity: 0 }} />
                </linearGradient>
              </defs>
              <path d={wash} fill={`url(#${uid}-wash)`} />
            </svg>
          )}
          {line && (
            <svg
              viewBox={`0 0 100 ${height}`}
              preserveAspectRatio="none"
              className="absolute inset-0 size-full overflow-visible [filter:drop-shadow(0_0_2px_rgb(var(--neon)/CALC(0.85*var(--neon-glow,1))))_drop-shadow(0_0_6px_rgb(var(--neon)/CALC(0.4*var(--neon-glow,1))))]"
            >
              <path
                d={line}
                fill="none"
                vectorEffect="non-scaling-stroke"
                strokeWidth={1.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ stroke: "rgb(var(--neon))" }}
              />
              <path
                d={line}
                fill="none"
                vectorEffect="non-scaling-stroke"
                strokeWidth={0.6}
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ stroke: "color-mix(in srgb, rgb(var(--neon)) 30%, white)" }}
              />
            </svg>
          )}
          {dot && end && (
            <span
              className="absolute size-[5px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[color-mix(in_srgb,rgb(var(--neon))_30%,white)] shadow-[0_0_4px_rgb(var(--neon)/var(--neon-glow,1)),0_0_10px_rgb(var(--neon)/CALC(0.7*var(--neon-glow,1)))]"
              style={{ left: `${end[0]}%`, top: end[1] }}
            >
              {live && (
                <span className="absolute -inset-[3px] animate-ping rounded-full border border-[rgb(var(--neon)/0.7)] [animation-duration:1.6s] motion-reduce:hidden" />
              )}
            </span>
          )}
        </span>
      </span>
    );
  },
);
Sparkline.displayName = "Sparkline";

export { GlowChart, Sparkline };
