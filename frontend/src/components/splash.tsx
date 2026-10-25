/**
 * Launch splash, ported from the Android app's SplashScreen.kt: the tile pops in, the brain
 * draws itself stroke by stroke, "Mined" slides up, "Tv" pops, then the tagline; ~2.6 s.
 *
 * Pure CSS, so it costs nothing to render and never flashes. It shows once per browser session:
 * an inline script in the layout adds `mtv-splash-seen` to <html> on later page loads, which
 * hides it. Clicking skips it, and it's skipped entirely for reduced-motion users.
 */

import { BRAIN_STROKES } from "@/components/brand";

const STAGGER_S = 0.06;

export function Splash() {
  return (
    <div className="mtv-splash" aria-hidden>
      <div className="mtv-splash-glow" />
      <div className="mtv-splash-body">
        <div className="mtv-splash-tile-wrap">
          <span className="mtv-splash-ring" />
          <span className="mtv-splash-ring mtv-splash-ring-2" />
          <div className="mtv-splash-tile">
            <svg viewBox="0 0 24 24" fill="none">
              {BRAIN_STROKES.map((d, i) => (
                <path
                  key={d}
                  d={d}
                  pathLength={1}
                  className="mtv-splash-stroke"
                  style={{ animationDelay: `${0.2 + i * STAGGER_S}s` }}
                />
              ))}
            </svg>
          </div>
        </div>
        <p className="mtv-splash-word">
          <span className="mtv-splash-mined">Mined</span>
          <span className="mtv-splash-tv">It</span>
        </p>
        <p className="mtv-splash-tagline">Clip the plays that blow your mind</p>
      </div>
    </div>
  );
}
