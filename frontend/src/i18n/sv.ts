// Swedish (default locale) UI dictionary. Flat, dot-path keys so lookups
// are a single object index (`dict[key]`) rather than nested traversal.
// Forecast *content* (risk category labels, confidence labels, and the
// explanation text) is generated in Swedish directly by the Python
// pipeline (see forecast/src/config.py, explanation.py) and is displayed
// as-is -- it deliberately does NOT go through this dictionary, since it's
// data, not UI chrome.
const sv = {
  "app.title": "Myggprognos",
  "app.subtitle": "Sverige · experimentell prognos, inte en myggräkning",
  "app.updated": "Uppdaterad {date}",

  "controlBar.day": "Dag",
  "controlBar.today": "Idag",
  "controlBar.tomorrow": "Imorgon",
  "controlBar.hour": "Timme (UTC)",
  "controlBar.timeOfDay": "Tid på dygnet",
  "controlBar.activity": "Aktivitet",
  "controlBar.layer": "Lager",
  "controlBar.useMyLocation": "Använd min plats",
  "controlBar.playPause": "Spela upp/pausa timanimering",
  "controlBar.filters": "Filter",
  "controlBar.closeFilters": "Stäng filter",

  "daypart.morning": "Morgon",
  "daypart.afternoon": "Eftermiddag",
  "daypart.evening": "Kväll",
  "daypart.night": "Natt",

  "activity.general": "Allmänt",
  "activity.running": "Löpning",
  "activity.hiking": "Vandring",
  "activity.camping": "Camping",
  "activity.fishing": "Fiske",
  "activity.gardening": "Trädgårdsarbete",
  "activity.outdoor_dining": "Utomhusmiddag",

  "layer.risk": "Total risk",
  "layer.population_potential": "Populationspotential",
  "layer.biting_activity": "Bettaktivitet",
  "layer.confidence": "Konfidens",

  "search.placeholder": "Sök ort, kommun eller lat, lon",
  "search.ariaLabel": "Sök plats eller koordinater",
  "search.goToCoordinates": "Gå till koordinater {lat}, {lon}",
  "search.onlineUnavailable": "Sökning online är inte tillgänglig; visar bara lokala träffar.",
  "search.attribution": "Platssökning © OpenStreetMap-bidragsgivare",
  "search.myLocation": "Din plats",
  "map.ariaLabel": "Karta över myggrisk i Sverige",

  "legend.riskTitle": "Myggrisk (0–100)",
  "legend.confidenceTitle": "Prognosens konfidens",

  "risk.category.very_low": "Mycket låg",
  "risk.category.low": "Låg",
  "risk.category.moderate": "Måttlig",
  "risk.category.high": "Hög",
  "risk.category.very_high": "Mycket hög",

  "confidence.low": "Låg",
  "confidence.medium": "Medel",
  "confidence.high": "Hög",

  "panel.defaultLocationLabel": "Vald plats",
  "panel.loading": "Laddar prognos…",
  "panel.loadError": "Kunde inte läsa in prognosdata: {error}",
  "panel.empty": "Välj en plats på kartan, sök efter en ort, eller använd din nuvarande plats för att se myggrisken.",
  "panel.riskLabel": "{category} risk",
  "panel.activityAdjusted": "Aktivitetsanpassad för {activity}",
  "panel.modelEstimate":
    "Modellens uppskattning: {model}. Justerad med {count} nya rapporter i närheten: {adjusted} (rapportvikt {weight}%).",
  "panel.population": "Population",
  "panel.activity": "Aktivitet",
  "panel.exposure": "Exponering",
  "panel.confidenceTitle": "Konfidens",
  "panel.whyTitle": "Varför ser det ut så här?",
  "panel.peakPeriod": "Högst aktivitet väntas på {period}.",
  "panel.next7days": "Kommande 7 dagar",
  "panel.next48h": "Kommande 48 timmar",
  "panel.reportButton": "Rapportera mygg här",
  "panel.shareButton": "Dela vyn",
  "panel.shareCopied": "Länk kopierad!",
  "panel.offlineDemo":
    "Rapportering körs i offline-demoläge; inskickade rapporter sparas inte förrän Worker-API:et är konfigurerat (se README).",

  "report.title": "Hur illa är myggen här just nu?",
  "report.severity": "Allvarlighetsgrad",
  "report.severity.none": "Inga",
  "report.severity.few": "Några få",
  "report.severity.noticeable": "Märkbart",
  "report.severity.many": "Många",
  "report.severity.unbearable": "Outhärdligt",
  "report.terrain": "Terräng (valfritt)",
  "report.terrain.urban": "Stad",
  "report.terrain.countryside": "Öppen landsbygd",
  "report.terrain.forest": "Skog",
  "report.terrain.wetland": "Våtmark",
  "report.terrain.waterside": "Vid vatten",
  "report.activity": "Aktivitet (valfritt)",
  "report.activity.stationary": "Stillastående",
  "report.activity.walking": "Promenad",
  "report.activity.running": "Löpning",
  "report.activity.camping": "Camping",
  "report.activity.fishing": "Fiske",
  "report.activity.gardening": "Trädgårdsarbete",
  "report.repellent": "Använde du myggmedel? (valfritt)",
  "report.yes": "Ja",
  "report.no": "Nej",
  "report.comment": "Kommentar (valfritt, max 280 tecken)",
  "report.commentPlaceholder": "Inga namn, e-postadresser eller telefonnummer, tack.",
  "report.privacyNote":
    "Vi sparar endast en ungefärlig (avrundad) plats och prognosruta, aldrig ditt namn, e-post eller exakta GPS-position.",
  "report.errorSeverityRequired": "Välj hur illa myggen är här just nu.",
  "report.errorPersonalData":
    "Ta bort sådant som ser ut som en e-postadress eller ett telefonnummer från kommentaren.",
  "report.submitting": "Skickar…",
  "report.submit": "Skicka rapport",
  "report.cancel": "Avbryt",

  "status.retry": "Försök igen",
  "status.degraded": "Visar prognosdata med sänkt kvalitet (se manifestvarningar).",
  "status.sampleData":
    "Visar exempeldata för endast {count} platser — inte den fullständiga Sverigetäckningen.",
  "status.stale": "Prognosdata är {hours} timmar gammal och kan vara inaktuell.",
  "status.loadFailed": "Kunde inte läsa in prognosen: {error}",

  "chart.tooltip": "Risk {value} · {category}",

  "loading.map": "Laddar karta…",
  "loading.progress1": "Hämtar prognosdata…",
  "loading.progress2": "Läser in väderunderlag…",
  "loading.progress3": "Nästan klart…",
} as const;

export default sv;
