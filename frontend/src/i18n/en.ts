import type { I18nDict } from "./types";

// Partial English dictionary -- proves the i18n structure is
// locale-agnostic without doing full bilingual QA the product spec didn't
// ask for (default/primary locale is Swedish, see sv.ts). Any key missing
// here falls back to the Swedish string (see index.tsx's `t()`).
const en: Partial<I18nDict> = {
  "app.title": "Mosquito Forecast",
  "app.tagline": "See today's and this week's mosquito risk.",
  "app.updated": "Updated {date}",
  "app.aboutButton": "About the forecast",

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
  "controlBar.productSwitchLabel": "Show",
  "controlBar.productSwitchHint": "Mosquito risk shows bite risk. Mosquito outlook shows how many mosquitoes are in the area, regardless of current weather.",

  "daySelector.ariaLabel": "Choose forecast day",

  "search.placeholder": "Search place or municipality",

  "layer.daily_peak_risk": "Mosquito risk",
  "layer.current_risk": "Mosquito risk right now",
  "layer.population_potential": "Mosquito outlook",
  "layer.biting_activity": "Mosquito activity",
  "layer.confidence": "Forecast basis",

  "legend.dailyPeakTitle": "Mosquito risk today (0-100)",
  "legend.currentRiskTitle": "Mosquito risk right now (0-100)",
  "legend.populationTitle": "Mosquito outlook (0-100)",
  "legend.activityTitle": "Mosquito activity (0-100)",
  "legend.confidenceTitle": "Forecast basis",
  "legend.whatColorsMean": "What do the colours mean?",
  "legend.modeRisk": "Mosquito risk – bite risk today",
  "legend.modeAbundance": "Mosquito outlook – how many mosquitoes",

  "risk.category.very_low": "Very low",
  "risk.category.low": "Low",
  "risk.category.moderate": "Moderate",
  "risk.category.high": "High",
  "risk.category.very_high": "Very high",

  "legend.risk.explain.very_low": "You'll likely barely notice mosquitoes.",
  "legend.risk.explain.low": "A few mosquitoes may be around.",
  "legend.risk.explain.moderate": "You may be bothered or bitten.",
  "legend.risk.explain.high": "Repellent is a good idea.",
  "legend.risk.explain.very_high": "Heavy mosquito activity expected.",

  "legend.abundance.explain.very_low": "Few mosquitoes expected in the area.",
  "legend.abundance.explain.low": "Relatively few mosquitoes.",
  "legend.abundance.explain.moderate": "A clear mosquito presence is likely.",
  "legend.abundance.explain.high": "Many mosquitoes expected in the area.",
  "legend.abundance.explain.very_high": "A very large mosquito presence expected.",

  "dataQuality.very_good": "Very good",
  "dataQuality.good": "Good",
  "dataQuality.limited": "Limited",
  "dataQuality.low": "Low",

  "panel.loading": "Loading forecast…",
  "panel.empty": "Select a location on the map, search for a place, or use your current location to see mosquito risk.",
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
  "panel.peakAroundTime": "Highest risk {day}: around {time}.",
  "panel.riskKicker": "Bite risk {day}",
  "panel.coordinatesLabel": "Location: {lat}, {lon}",
  "panel.nowVsPeak": "{nowCategory} bite risk now – {peakCategory} expected around {time}.",
  "panel.relationship.abundanceHigherThanRisk":
    "There are likely plenty of mosquitoes in the area, but conditions are keeping bite risk down right now.",
  "panel.relationship.riskHigherThanAbundance":
    "The mosquito outlook here is {abundanceCategory}, but calm, warm weather is pushing bite risk up right now.",
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

  "panel.abundanceAdvice.very_low": "Unusually mosquito-poor area. Low risk of problems here.",
  "panel.abundanceAdvice.low": "Moderately mosquito-friendly area.",
  "panel.abundanceAdvice.moderate": "Mosquito-rich area. Risk can rise quickly in calm, warm weather.",
  "panel.abundanceAdvice.high": "Very mosquito-rich area, especially near water or wetland.",
  "panel.abundanceAdvice.very_high": "Extremely mosquito-rich area. Expect mosquitoes as soon as weather is favourable.",

  "panel.timelineTitle": "Through the day",
  "panel.timelinePeak": "Peak",
  "panel.cardsTitle": "Coming days",
  "panel.cardToday": "Today",
  "panel.cardTomorrow": "Tomorrow",
  "panel.cardPeak": "Peak at {time}",
  "panel.cardPeakUnknown": "Peak unknown",
  "panel.cardBest": "Lowest risk",
  "panel.cardWorst": "Highest risk",

  "panel.howItWorksTitle": "How does the forecast work?",
  "panel.detailsTitle": "Technical details",

  "sheet.expand": "Show more",
  "sheet.collapse": "Show less",
  "sheet.swipeUp": "Swipe up",
  "sheet.showMap": "Show map",
  "sheet.dragHandleLabel": "Drag to show more or less of the forecast panel",

  "panel.reportButton": "Report how many mosquitoes you see",
  "panel.shareButton": "Share the forecast",
  "panel.shareCopied": "Link copied!",

  "status.sampleData": "Showing example data for only {count} locations — not full Sweden coverage.",

  "about.title": "About the forecast",
  "about.howTitle": "How the forecast works",
  "about.howBody":
    "The forecast combines weather data and environmental conditions -- rainfall, temperature, wind, and proximity to wetland and water -- to estimate how many mosquitoes are likely present and how active they are, hour by hour and for the coming seven days.",
  "about.sourcesTitle": "Data sources",
  "about.sourcesBody":
    "Weather data comes from SMHI's open data. Terrain information (forest, wetland, water and elevation) is based on ESA WorldCover, the Swedish EPA's national land-cover data (NMD) and Copernicus elevation data. Place search uses a local place index plus OpenStreetMap/Nominatim.",
  "about.updateTitle": "Updates",
  "about.updateBody": "The forecast is automatically recalculated roughly every six hours.",
  "about.limitationsTitle": "Limitations",
  "about.limitationsBody":
    "This is a model-calculated risk index based on weather and environmental conditions. It is not a measured mosquito count, and it is not a tool for assessing mosquito-borne disease risk.",
  "about.close": "Close",
};

export default en;
