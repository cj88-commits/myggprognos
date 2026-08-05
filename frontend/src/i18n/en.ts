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
  "controlBar.tomorrow": "Tomorrow",
  "controlBar.hour": "Time",
  "controlBar.timeOfDay": "Time of day",
  "controlBar.activity": "Activity",
  "controlBar.layer": "Map view",
  "controlBar.useMyLocation": "Use my location",
  "controlBar.filters": "Settings",
  "controlBar.closeFilters": "Close",

  "layer.daily_peak_risk": "Mosquito risk today",
  "layer.current_risk": "Mosquito risk right now",
  "layer.population_potential": "Mosquito outlook",
  "layer.biting_activity": "Mosquito activity",
  "layer.confidence": "Forecast basis",

  "legend.dailyPeakTitle": "Mosquito risk today (0-100)",
  "legend.currentRiskTitle": "Mosquito risk right now (0-100)",
  "legend.populationTitle": "Mosquito outlook (0-100)",
  "legend.activityTitle": "Mosquito activity (0-100)",
  "legend.confidenceTitle": "Forecast basis",

  "risk.category.very_low": "Very low",
  "risk.category.low": "Low",
  "risk.category.moderate": "Moderate",
  "risk.category.high": "High",
  "risk.category.very_high": "Very high",

  "dataQuality.very_good": "Very good",
  "dataQuality.good": "Good",
  "dataQuality.limited": "Limited",
  "dataQuality.low": "Low",

  "panel.loading": "Loading forecast…",
  "panel.empty": "Select a location on the map, search for a place, or use your current location to see mosquito risk.",
  "panel.heroHeadlineNow": "{category} risk right now",
  "panel.heroHeadline": "{category} risk",
  "panel.heroHeadlineDailyPeak": "{category} risk today",
  "panel.abundanceHeadline.very_low": "Very low mosquito outlook",
  "panel.abundanceHeadline.low": "Low mosquito outlook",
  "panel.abundanceHeadline.moderate": "Moderate mosquito outlook",
  "panel.abundanceHeadline.high": "High mosquito outlook",
  "panel.abundanceHeadline.very_high": "Very high mosquito outlook",
  "panel.abundanceExplain":
    "Based on recent weather and local terrain (rainfall, warmth, wetlands) -- not on current wind or temperature.",
  "panel.whyTitle": "What's affecting the risk right now?",
  "panel.whyTitleToday": "What's affecting today's risk?",
  "panel.whenChangesTitle": "When does it change?",
  "panel.peakAroundTime": "Peak expected around {time}.",
  "panel.dataQualityTitle": "Forecast basis",
  "panel.dataQualityExplain": "Shows how much and how good the underlying data is -- not how dangerous the risk is.",
  "panel.modelDisclaimer":
    "This is a model-calculated risk index based on weather and environmental conditions. It is not a measured mosquito count.",
  "panel.next7days": "Next 7 days",
  "panel.next48h": "Next 48 hours",

  "panel.adviceTitle": "What should I do?",
  "panel.advice.very_low": "Good time for a walk or other outdoor activity.",
  "panel.advice.low": "Low risk for most outdoor activities.",
  "panel.advice.moderate": "Consider mosquito repellent if you're sensitive or staying out long.",
  "panel.advice.high": "Bring repellent and consider covering up.",
  "panel.advice.very_high": "Avoid wetlands and forest if possible. Use repellent.",

  "panel.timelineTitle": "Through the day",
  "panel.cardsTitle": "Coming days",
  "panel.cardToday": "Today",
  "panel.cardTomorrow": "Tomorrow",
  "panel.cardPeak": "Peak at {time}",
  "panel.cardPeakUnknown": "Peak unknown",

  "panel.howItWorksTitle": "How does the forecast work?",
  "panel.detailsTitle": "Technical details",

  "sheet.expand": "Show more",
  "sheet.collapse": "Show less",
  "sheet.swipeUp": "Swipe up",
  "sheet.dragHandleLabel": "Drag to show more or less of the forecast panel",

  "panel.reportButton": "Report mosquitoes here",
  "panel.shareButton": "Share this view",
  "panel.shareCopied": "Link copied!",

  "status.degraded": "Showing degraded-quality forecast data (see manifest warnings).",
  "status.sampleData": "Showing example data for only {count} locations — not full Sweden coverage.",
};

export default en;
