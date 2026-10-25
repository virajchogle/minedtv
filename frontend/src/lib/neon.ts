import type * as React from "react";

/**
 * The NeonKit palette, stored as space-separated RGB channels so components
 * can apply any alpha with `rgb(var(--neon) / 0.4)`.
 */
export const neonColors = {
  cyan: "34 211 238",
  blue: "79 139 255",
  violet: "168 85 247",
  magenta: "240 70 235",
  pink: "255 95 162",
  red: "255 77 94",
  orange: "255 138 61",
  amber: "251 191 36",
  lime: "163 230 53",
  green: "52 211 153",
  white: "230 237 247",
} as const;

export type NeonColorName = keyof typeof neonColors;

/** A palette name or any hex color (`#0ff`, `#ff00aa`). */
export type NeonColor = NeonColorName | (string & {});

export const neonColorNames = Object.keys(neonColors) as NeonColorName[];

/** Resolves a palette name or hex string to `"r g b"` channels. */
export function toNeonRgb(color: NeonColor): string {
  if (color in neonColors) return neonColors[color as NeonColorName];

  let hex = color.trim().replace(/^#/, "");
  if (hex.length === 3) hex = hex.replace(/./g, (c) => c + c);
  if (!/^[0-9a-f]{6}$/i.test(hex)) return neonColors.cyan;

  const value = parseInt(hex, 16);
  return `${(value >> 16) & 255} ${(value >> 8) & 255} ${value & 255}`;
}

/**
 * Inline style that sets a component's neon color.
 *
 * Components read `--neon`. Leave `color` undefined and they inherit
 * `--neon-accent` from any ancestor, falling back to cyan.
 */
export function neonVars(
  color?: NeonColor,
  style?: React.CSSProperties,
): React.CSSProperties | undefined {
  if (!color) return style;
  const rgb = toNeonRgb(color);
  return { "--neon": rgb, "--neon-accent": rgb, ...style } as React.CSSProperties;
}
