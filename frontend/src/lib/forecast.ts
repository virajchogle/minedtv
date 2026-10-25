/**
 * MinedIt Forecast: illustrative earnings/attention projection.
 *
 * This is explicitly NOT a validated predictive model. It's one transparent,
 * documented formula turning a clip's real virality score and real view
 * history into a smooth attention curve and a views×RPM earnings estimate,
 * so a creator can explore "what if" scenarios. Every number that isn't
 * derived from the clip's own real data (view_count, created_at, the
 * virality engine's score) is a clearly-labeled assumption, not a prediction
 * backed by historical outcomes.
 *
 * Design choices that keep the math honest (see dashboard/forecast-module.tsx
 * for where these are surfaced to the user):
 *  - RPM only scales earnings, never predicted views.
 *  - Scenario only scales predicted views/earnings, independent of RPM.
 *  - The full 365-day daily series is computed once; every horizon (15..365)
 *    reads a slice/day of that SAME series; horizons are never independently
 *    recomputed, so a 90-day and a 365-day forecast agree on day 90.
 *  - Daily views/earnings are a sum of two non-negative terms (a Gaussian
 *    spike + a decaying evergreen floor), so cumulative values are provably
 *    monotonically non-decreasing, with no clamping required to enforce it.
 */

export type Scenario = "conservative" | "expected" | "breakout";

export const SCENARIOS: { id: Scenario; label: string }[] = [
  { id: "conservative", label: "Conservative" },
  { id: "expected", label: "Expected" },
  { id: "breakout", label: "Breakout" },
];

export const HORIZONS = [15, 30, 45, 60, 90, 120, 240, 365] as const;
export type Horizon = (typeof HORIZONS)[number];

export const MAX_HORIZON_DAYS = 365;

/**
 * Assumed $ per 1,000 views. Not official payout tables.
 *
 * TikTok's Creativity Program is typically cited in the low-cents-per-1k range,
 * far below YouTube ads. Twitch and Medal are not used here: they are not
 * how a short clip earns, and those old presets invented a mid-dollar RPM
 * that made TikTok forecasts look like streaming income.
 */
export const TIKTOK_RPM = 0.04;

export const RPM_PRESETS: { id: string; label: string; rpm: number }[] = [
  { id: "tiktok", label: "TikTok assumed ($0.04)", rpm: TIKTOK_RPM },
  { id: "youtube", label: "YouTube assumed ($2.50)", rpm: 2.5 },
];

const SCENARIO_PARAMS: Record<Scenario, { viewMultiplier: number; peakDayFactor: number; spreadFactor: number }> = {
  // viewMultiplier scales the whole curve's height. peakDayFactor/spreadFactor
  // shape *when* and *how sharply* attention arrives; breakout clips are
  // modeled as arriving faster and sharper; conservative ones slower and flatter.
  conservative: { viewMultiplier: 0.5, peakDayFactor: 1.5, spreadFactor: 1.4 },
  expected: { viewMultiplier: 1.0, peakDayFactor: 1.0, spreadFactor: 1.0 },
  breakout: { viewMultiplier: 2.4, peakDayFactor: 0.55, spreadFactor: 0.75 },
};

/** No virality check yet: assume a neutral-low score rather than pretending to know. */
export const UNSCORED_DEFAULT_VIRALITY = 30;

export interface ForecastInput {
  /** The clip's real lifetime view count so far. */
  existingViews: number;
  /** Real virality score (0–100), or null if this clip hasn't been checked. */
  viralityScore: number | null;
  /** Real days since the clip was published (0 for not-yet-published / brand new). */
  daysSincePublish: number;
  /** $ assumed earned per 1,000 views. Only ever affects earnings, never views. */
  rpm: number;
  scenario: Scenario;
}

export interface ForecastDay {
  /** 1-indexed day offset from today, into the future. */
  day: number;
  views: number;
  cumulativeViews: number;
  earnings: number;
  cumulativeEarnings: number;
}

export interface ForecastResult {
  input: ForecastInput;
  /** Always MAX_HORIZON_DAYS entries; callers slice to the selected horizon. */
  days: ForecastDay[];
  usedDefaultScore: boolean;
}

/**
 * The score→views mapping: an explicit, tunable, documented formula:
 * score 0 → the clip's own recent run-rate; score 100 → 10× that run-rate at
 * peak. This has not been fit to any outcome data; it only guarantees "higher
 * score → bigger modeled audience," which is the one property the real
 * virality engine's score is designed to carry.
 */
export function forecast(input: ForecastInput): ForecastResult {
  const usedDefaultScore = input.viralityScore == null;
  const score = Math.max(0, Math.min(100, input.viralityScore ?? UNSCORED_DEFAULT_VIRALITY));

  // Recent run-rate: views-per-day so far, floored so a brand-new upload
  // (0 views, 0 days old) still seeds a visible curve rather than a flat zero.
  const runRate = Math.max(input.existingViews / Math.max(1, input.daysSincePublish), 25);

  const s = SCENARIO_PARAMS[input.scenario];
  const scoreMultiplier = 1 + (score / 100) * 9; // 1x..10x
  const peakViews = runRate * scoreMultiplier * s.viewMultiplier;
  const peakDay = Math.max(1, 4 * s.peakDayFactor + ((100 - score) / 100) * 6 * s.peakDayFactor);
  const spread = Math.max(2, peakDay * 0.6 * s.spreadFactor);
  // Evergreen floor: a small fraction of peak that decays far more slowly than
  // the spike, so long-horizon forecasts keep accruing instead of flatlining
  // to exactly zero (the "second-wave / evergreen" case, modeled as a gentle
  // residual rather than a separate resurgence event).
  const tailFloor = peakViews * 0.03;
  const tailDecay = peakDay * 10;

  const days: ForecastDay[] = [];
  let cumulativeViews = 0;
  let cumulativeEarnings = 0;
  for (let day = 1; day <= MAX_HORIZON_DAYS; day++) {
    // The curve is anchored to publish day, not today: a clip that already had
    // its spike is on its tail now, instead of being modeled as launching again.
    const age = input.daysSincePublish + day;
    const spike = peakViews * Math.exp(-((age - peakDay) ** 2) / (2 * spread ** 2));
    const tail = tailFloor * Math.exp(-age / tailDecay);
    const views = Math.max(0, spike + tail);
    const earnings = (views / 1000) * input.rpm;
    cumulativeViews += views;
    cumulativeEarnings += earnings;
    days.push({ day, views, cumulativeViews, earnings, cumulativeEarnings });
  }

  return { input, days, usedDefaultScore };
}

export interface ForecastSummary {
  horizonDays: number;
  totalViews: number;
  totalEarnings: number;
  peakDay: number;
  peakViews: number;
  earnings30d: number;
  /** Share of the horizon's total earnings captured in the first 30 days, 0..1. */
  earningsShareFirst30d: number;
}

/** Headline stats for one horizon, read off the single shared daily series. */
export function summarize(result: ForecastResult, horizonDays: number): ForecastSummary {
  const clamped = Math.max(1, Math.min(MAX_HORIZON_DAYS, horizonDays));
  const atHorizon = result.days[clamped - 1];
  const at30 = result.days[Math.min(30, clamped) - 1];
  const peak = result.days.slice(0, clamped).reduce((a, b) => (b.views > a.views ? b : a), result.days[0]);
  return {
    horizonDays: clamped,
    totalViews: atHorizon.cumulativeViews,
    totalEarnings: atHorizon.cumulativeEarnings,
    peakDay: peak.day,
    peakViews: peak.views,
    earnings30d: at30.cumulativeEarnings,
    earningsShareFirst30d: atHorizon.cumulativeEarnings > 0 ? at30.cumulativeEarnings / atHorizon.cumulativeEarnings : 0,
  };
}
