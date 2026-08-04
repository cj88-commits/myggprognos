// All forecast timestamps/hour-buckets are keyed in UTC internally (see
// forecast/src/output.py -- hourly files are named "<ISO-date>T<UTC-hour>"),
// since that's what the pipeline computes against. None of that should ever
// reach the UI, though: every user-facing time is formatted in Sweden's own
// timezone via these helpers, which also transparently handles the
// CET/CEST daylight-saving switch (Intl's timeZone database does this for
// free -- no manual offset math needed).
export const STOCKHOLM_TZ = "Europe/Stockholm";

function localeTag(locale: string): string {
  return locale === "sv" ? "sv-SE" : "en-GB";
}

// Parses a UTC hour-bucket label like "2026-08-04T14" (as found in
// manifest.hourly_files, with the "hourly/" prefix and ".json.gz" suffix
// already stripped) into the Date it actually represents.
export function hourBucketToDate(hourLabel: string): Date {
  return new Date(`${hourLabel}:00:00Z`);
}

// "14:00" in Stockholm local time, from a UTC hour-bucket label.
export function formatStockholmHourLabel(hourLabel: string, locale: string): string {
  return hourBucketToDate(hourLabel).toLocaleTimeString(localeTag(locale), {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: STOCKHOLM_TZ,
  });
}

// Just the hour ("14"), for compact chart axis ticks.
export function formatStockholmHourShort(hourLabel: string, locale: string): string {
  return hourBucketToDate(hourLabel).toLocaleTimeString(localeTag(locale), {
    hour: "numeric",
    hour12: false,
    timeZone: STOCKHOLM_TZ,
  });
}

export function formatStockholmWeekday(dateIso: string, locale: string): string {
  const d = new Date(`${dateIso}T12:00:00Z`); // noon UTC avoids any DST edge flipping the calendar day
  return d.toLocaleDateString(localeTag(locale), { weekday: "short", timeZone: STOCKHOLM_TZ });
}

export function formatStockholmDateLabel(dateIso: string, locale: string): string {
  const d = new Date(`${dateIso}T12:00:00Z`);
  return d.toLocaleDateString(localeTag(locale), {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: STOCKHOLM_TZ,
  });
}

// The UTC hour-bucket label (e.g. "2026-08-04T14") matching the current
// instant -- used only to find/highlight "now" among already UTC-keyed
// data points, never displayed directly.
export function currentHourBucketLabel(): string {
  return new Date().toISOString().slice(0, 13);
}

export function currentDateIso(): string {
  return new Date().toISOString().slice(0, 10);
}
