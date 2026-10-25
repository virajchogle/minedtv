/**
 * The MinedTv logo, shared with the Android app (rishikesh-web/MinedTv): a brain ("Mined" ->
 * "Mind") drawn as strokes on an accent tile, next to the "Mined" + accented "Tv" wordmark.
 * BRAIN_PATH is the same 24x24 path as the app's BrainIcon.kt and launcher icon.
 */

import { cn } from "@/lib/utils";

export const BRAIN_PATH =
  // Left hemisphere
  "M12,4.5 C10.8,3.2 8.6,3.3 7.8,4.8 C6,4.6 4.6,6.2 5.1,7.9 C3.6,8.7 3.3,10.9 4.6,12 " +
  "C3.5,13.3 4,15.4 5.6,15.9 C5.6,17.7 7.4,19 9.1,18.4 C9.9,19.8 11.3,20 12,19.4 Z " +
  // Right hemisphere
  "M12,4.5 C13.2,3.2 15.4,3.3 16.2,4.8 C18,4.6 19.4,6.2 18.9,7.9 C20.4,8.7 20.7,10.9 19.4,12 " +
  "C20.5,13.3 20,15.4 18.4,15.9 C18.4,17.7 16.6,19 14.9,18.4 C14.1,19.8 12.7,20 12,19.4 " +
  // Folds
  "M8,8.2 C9,8 9.8,8.8 9.6,9.8 M6.8,12.2 C8,11.8 9.2,12.6 9,13.8 M9.5,15.8 C10.2,15.2 10.4,14.3 10,13.6 " +
  "M16,8.2 C15,8 14.2,8.8 14.4,9.8 M17.2,12.2 C16,11.8 14.8,12.6 15,13.8 M14.5,15.8 C13.8,15.2 13.6,14.3 14,13.6";

/** Each "M" starts one stroke; the splash screen draws them one after another. */
export const BRAIN_STROKES = BRAIN_PATH.split("M")
  .map((s) => s.trim())
  .filter(Boolean)
  .map((s) => `M${s}`);

/** The brain mark on its accent tile. `size` is the tile's edge in pixels. */
export function BrainMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <span
      className={cn("inline-flex shrink-0 items-center justify-center bg-[var(--mtv-gold)]", className)}
      style={{ width: size, height: size, borderRadius: size / 4 }}
      aria-hidden
    >
      <svg viewBox="0 0 24 24" width={size * 0.8} height={size * 0.8} fill="none">
        <path d={BRAIN_PATH} stroke="#000" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

/** Mark + "MinedTv" wordmark, for navigation. */
export function Logo({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <BrainMark size={size} />
      <span className="text-base font-extrabold tracking-tight text-white">
        Mined<span className="text-[var(--mtv-gold)]">Tv</span>
      </span>
    </span>
  );
}
