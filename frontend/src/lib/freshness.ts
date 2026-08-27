// Forecast freshness is judged purely against the live manifest's own
// `generated_at` (an absolute, "Z"-suffixed UTC timestamp written by
// forecast/src/pipeline.py) -- never against frontend build time, deployed
// asset timestamps, or `manifest.build_sha`. Those all describe when this
// *code* was built, which is decoupled from forecast publication under
// FORECAST_STORAGE_MODE=r2-cutover (see README "Forecast data hosting"):
// the same frontend deployment must keep reporting fresh/stale correctly
// across many R2-only publish cycles with zero redeploy.
//
// 12h = 2x the 6-hourly pipeline cadence, so one missed/delayed run doesn't
// itself trigger the warning -- only genuine multi-cycle staleness does.
export const STALE_THRESHOLD_HOURS = 12;

export interface StalenessResult {
  stale: boolean;
  // null when `generatedAt` couldn't be parsed -- treated as "unknown", not
  // stale, matching this module's existing safe-by-default behavior rather
  // than surfacing a broken/garbage age to the user.
  ageHours: number | null;
}

export function computeStaleness(
  generatedAt: string | undefined,
  now: number = Date.now(),
  thresholdHours: number = STALE_THRESHOLD_HOURS
): StalenessResult {
  const generatedMs = generatedAt ? new Date(generatedAt).getTime() : NaN;
  if (Number.isNaN(generatedMs)) return { stale: false, ageHours: null };
  const ageHours = (now - generatedMs) / 3600000;
  return { stale: ageHours > thresholdHours, ageHours };
}
