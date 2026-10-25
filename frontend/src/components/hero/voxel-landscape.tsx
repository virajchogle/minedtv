"use client";

/**
 * A procedurally generated blocky landscape, used when no hero image is
 * available (see minecraft-sunrise-hero.tsx).
 *
 * It is split into a background plate and a foreground plate so the hero can
 * render the "MinedIt" wordmark *between* them — the depth effect where the
 * terrain overlaps the lettering. A flat photograph cannot do this without a
 * hand-authored alpha cutout; an SVG can, because the silhouette is real
 * geometry with correct edges.
 *
 * Geometry is generated once at module scope from a fixed seed, so it is
 * stable across renders and identical between server and client.
 */

const VIEW_W = 1600;
const VIEW_H = 900;

/** Deterministic PRNG — the scene must not change between SSR and hydration. */
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * A stepped ridge line: a random walk quantised to block-sized stairs, which
 * is what reads as "voxel terrain" rather than a smooth hill.
 */
function ridgePath(options: {
  seed: number;
  block: number;
  baseY: number;
  amplitude: number;
  drift: number;
}): string {
  const { seed, block, baseY, amplitude, drift } = options;
  const random = mulberry32(seed);
  const steps = Math.ceil(VIEW_W / block) + 1;

  let y = baseY;
  const points: string[] = [`M -${block} ${VIEW_H}`, `L -${block} ${y}`];

  for (let i = 0; i <= steps; i += 1) {
    const x = i * block;
    // Bias the walk back toward baseY so the ridge never wanders off-canvas.
    const pull = (baseY - y) * 0.12;
    y += (random() - 0.5) * 2 * drift + pull;
    y = Math.max(baseY - amplitude, Math.min(baseY + amplitude, y));
    const snapped = Math.round(y / block) * block;
    points.push(`L ${x} ${snapped}`, `L ${x + block} ${snapped}`);
  }

  points.push(`L ${VIEW_W + block} ${VIEW_H}`, "Z");
  return points.join(" ");
}

/** Blocky conifers, the one silhouette that instantly reads as Minecraft. */
function treeRects(seed: number, count: number, groundY: number, scale: number) {
  const random = mulberry32(seed);
  const rects: { x: number; y: number; w: number; h: number; shade: number }[] = [];

  for (let i = 0; i < count; i += 1) {
    const x = random() * VIEW_W;
    const trunk = 10 * scale;
    const tiers = 3;
    const tierH = 22 * scale;
    const baseW = 54 * scale;
    const jitter = (random() - 0.5) * 18 * scale;
    const footY = groundY + jitter;

    rects.push({ x: x - trunk / 2, y: footY - tierH * 0.6, w: trunk, h: tierH * 0.8, shade: 0 });
    for (let t = 0; t < tiers; t += 1) {
      const w = baseW * (1 - t * 0.26);
      rects.push({
        x: x - w / 2,
        y: footY - tierH * (t + 1.1),
        w,
        h: tierH,
        shade: 1,
      });
    }
  }
  return rects;
}

const FAR_RIDGE = ridgePath({ seed: 7, block: 32, baseY: 430, amplitude: 110, drift: 34 });
const MID_RIDGE = ridgePath({ seed: 21, block: 40, baseY: 560, amplitude: 120, drift: 46 });
const NEAR_RIDGE = ridgePath({ seed: 53, block: 52, baseY: 690, amplitude: 90, drift: 44 });
const FRONT_RIDGE = ridgePath({ seed: 91, block: 64, baseY: 760, amplitude: 130, drift: 78 });

const MID_TREES = treeRects(11, 26, 585, 0.7);
const FRONT_TREES = treeRects(29, 18, 775, 1.35);

/**
 * Distant terrain. Sits behind the wordmark.
 * `light` (0 = pre-dawn, 1 = full morning) warms and brightens the plates so
 * the terrain participates in the sunrise instead of staying flat.
 */
export function VoxelLandscapeBack({ light = 0 }: { light?: number }) {
  const l = Math.max(0, Math.min(1, light));
  // Pre-dawn terrain is cold and dark; morning terrain is warmer and lighter.
  const mix = (dawn: [number, number, number], day: [number, number, number]) =>
    `rgb(${dawn.map((c, i) => Math.round(c + (day[i] - c) * l)).join(",")})`;

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      preserveAspectRatio="xMidYMax slice"
      className="h-full w-full"
      aria-hidden
    >
      <path d={FAR_RIDGE} fill={mix([26, 34, 54], [92, 118, 138])} />
      <path d={MID_RIDGE} fill={mix([19, 27, 44], [62, 96, 74])} />
      {MID_TREES.map((r, i) => (
        <rect
          key={i}
          x={r.x}
          y={r.y}
          width={r.w}
          height={r.h}
          fill={
            r.shade
              ? mix([14, 24, 32], [44, 82, 56])
              : mix([12, 16, 22], [58, 44, 30])
          }
        />
      ))}
      <path d={NEAR_RIDGE} fill={mix([13, 19, 32], [46, 76, 58])} />
    </svg>
  );
}

/**
 * Near terrain. Sits *in front of* the wordmark — this is the layer that
 * creates the overlap depth.
 */
export function VoxelLandscapeFront({ light = 0 }: { light?: number }) {
  const l = Math.max(0, Math.min(1, light));
  const mix = (dawn: [number, number, number], day: [number, number, number]) =>
    `rgb(${dawn.map((c, i) => Math.round(c + (day[i] - c) * l)).join(",")})`;

  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      preserveAspectRatio="xMidYMax slice"
      className="h-full w-full"
      aria-hidden
    >
      <path d={FRONT_RIDGE} fill={mix([7, 11, 19], [26, 46, 34])} />
      {FRONT_TREES.map((r, i) => (
        <rect
          key={i}
          x={r.x}
          y={r.y}
          width={r.w}
          height={r.h}
          fill={
            r.shade ? mix([6, 10, 15], [22, 42, 30]) : mix([5, 8, 12], [34, 26, 18])
          }
        />
      ))}
    </svg>
  );
}
