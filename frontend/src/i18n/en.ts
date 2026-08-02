import type { I18nDict } from "./types";

// Partial English dictionary -- proves the i18n structure is
// locale-agnostic without doing full bilingual QA the product spec didn't
// ask for (default/primary locale is Swedish, see sv.ts). Any key missing
// here falls back to the Swedish string (see index.tsx's `t()`).
const en: Partial<I18nDict> = {
  "app.title": "Mosquito Forecast",
  "app.updated": "Updated {date}",

  "controlBar.day": "Day",
  "controlBar.today": "Today",
  "controlBar.hour": "Hour (UTC)",
  "controlBar.timeOfDay": "Time of day",
  "controlBar.activity": "Activity",
  "controlBar.layer": "Layer",
  "controlBar.useMyLocation": "Use my location",
  "controlBar.filters": "Filters",
  "controlBar.closeFilters": "Close filters",

  "layer.risk": "Overall risk",
  "layer.population_potential": "Population potential",
  "layer.biting_activity": "Biting activity",
  "layer.confidence": "Confidence",

  "legend.riskTitle": "Mosquito risk (0-100)",
  "legend.confidenceTitle": "Forecast confidence",

  "risk.category.very_low": "Very low",
  "risk.category.low": "Low",
  "risk.category.moderate": "Moderate",
  "risk.category.high": "High",
  "risk.category.very_high": "Very high",

  "confidence.low": "Low",
  "confidence.medium": "Medium",
  "confidence.high": "High",

  "panel.loading": "Loading forecast…",
  "panel.empty": "Select a location on the map, search for a place, or use your current location to see mosquito risk.",
  "panel.whyTitle": "Why is it like this?",
  "panel.next7days": "Next 7 days",
  "panel.next48h": "Next 48 hours",
  "panel.reportButton": "Report mosquitoes here",
  "panel.shareButton": "Share this view",
  "panel.shareCopied": "Link copied!",

  "status.degraded": "Showing degraded-quality forecast data (see manifest warnings).",
  "status.sampleData": "Showing example data for only {count} locations — not full Sweden coverage.",
};

export default en;
