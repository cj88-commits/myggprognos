// Swedish (default locale) UI dictionary. Flat, dot-path keys so lookups
// are a single object index (`dict[key]`) rather than nested traversal.
// Forecast *content* (risk category labels, confidence labels, and the
// explanation text) is generated in Swedish directly by the Python
// pipeline (see forecast/src/config.py, explanation.py) and is displayed
// as-is -- it deliberately does NOT go through this dictionary, since it's
// data, not UI chrome.
const sv = {
  "app.title": "Myggprognos",
  "app.tagline": "Se myggrisken idag och kommande veckan.",
  "app.updated": "Uppdaterad {date}",
  "app.aboutButton": "Om prognosen",

  "controlBar.day": "Dag",
  "controlBar.today": "Idag",
  "controlBar.tomorrow": "Imorgon",
  "controlBar.hour": "Tid",
  "controlBar.timeOfDay": "Tid på dygnet",
  "controlBar.activity": "Aktivitet",
  "controlBar.layer": "Kartvy",
  "controlBar.useMyLocation": "Använd min plats",
  "controlBar.playPause": "Spela upp/pausa timanimering",
  "controlBar.filters": "Inställningar",
  "controlBar.closeFilters": "Stäng",
  "controlBar.productSwitchLabel": "Visa",
  "controlBar.productSwitchHint": "Myggrisk visar bettrisk. Myggläge visar hur mycket mygg som finns i området, oavsett väder just nu.",

  "daySelector.ariaLabel": "Välj prognosdag",

  "daypart.morning": "Morgon",
  "daypart.afternoon": "Eftermiddag",
  "daypart.evening": "Kväll",
  "daypart.night": "Natt",

  "daypartOn.morning": "på morgonen",
  "daypartOn.afternoon": "på eftermiddagen",
  "daypartOn.evening": "på kvällen",
  "daypartOn.night": "på natten",

  "activity.general": "Allmänt",
  "activity.running": "Löpning",
  "activity.hiking": "Vandring",
  "activity.camping": "Camping",
  "activity.fishing": "Fiske",
  "activity.gardening": "Trädgårdsarbete",
  "activity.outdoor_dining": "Utomhusmiddag",

  "layer.daily_peak_risk": "Myggrisk",
  "layer.current_risk": "Myggrisk just nu",
  "layer.population_potential": "Myggläge",
  "layer.biting_activity": "Myggaktivitet",
  "layer.confidence": "Prognosunderlag",

  "search.placeholder": "Sök ort eller kommun",
  "search.ariaLabel": "Sök plats eller koordinater",
  "search.goToCoordinates": "Gå till koordinater {lat}, {lon}",
  "search.onlineUnavailable": "Sökning online är inte tillgänglig; visar bara lokala träffar.",
  "search.attribution": "Platssökning © OpenStreetMap-bidragsgivare",
  "search.myLocation": "Din plats",
  "map.ariaLabel": "Karta över myggrisk i Sverige",
  "map.nearPlace": "Nära {place}",

  "legend.dailyPeakTitle": "Myggrisk idag (0–100)",
  "legend.currentRiskTitle": "Myggrisk just nu (0–100)",
  "legend.populationTitle": "Myggläge (0–100)",
  "legend.activityTitle": "Myggaktivitet (0–100)",
  "legend.confidenceTitle": "Prognosunderlag",
  // Compact, mode-agnostic button label (item 10: the legend is a
  // collapsed-by-default popover, not a "(0-100)" scale readout) -- the
  // expanded panel restates which product it's explaining via
  // legend.modeRisk/legend.modeAbundance below.
  "legend.whatColorsMean": "Vad betyder färgerna?",
  "legend.modeRisk": "Myggrisk – bettrisk idag",
  "legend.modeAbundance": "Myggläge – myggförekomst",

  "risk.category.very_low": "Mycket låg",
  "risk.category.low": "Låg",
  "risk.category.moderate": "Måttlig",
  "risk.category.high": "Hög",
  "risk.category.very_high": "Mycket hög",

  // Legend swatch explanations -- practical, one-sentence meanings per
  // category, distinct per product (item 3 + item 4: Myggrisk answers "will
  // I get bitten", Myggläge answers "are there generally many mosquitoes
  // here", and reusing one set of sentences for both would blur that
  // distinction right where it matters most).
  "legend.risk.explain.very_low": "Du märker troligen knappt av mygg.",
  "legend.risk.explain.low": "Enstaka mygg kan förekomma.",
  "legend.risk.explain.moderate": "Du kan bli störd eller biten.",
  "legend.risk.explain.high": "Myggmedel kan vara bra att ha.",
  "legend.risk.explain.very_high": "Mycket myggaktivitet väntas.",

  "legend.abundance.explain.very_low": "Få mygg väntas finnas i området.",
  "legend.abundance.explain.low": "Relativt lite mygg.",
  "legend.abundance.explain.moderate": "En tydlig myggförekomst är sannolik.",
  "legend.abundance.explain.high": "Mycket mygg väntas finnas i området.",
  "legend.abundance.explain.very_high": "Mycket stor myggförekomst väntas.",

  "dataQuality.very_good": "Mycket bra",
  "dataQuality.good": "Bra",
  "dataQuality.limited": "Begränsat",
  "dataQuality.low": "Lågt",

  "panel.defaultLocationLabel": "Vald plats",
  "panel.loading": "Laddar prognos…",
  "panel.loadError": "Kunde inte läsa in prognosdata: {error}",
  "panel.empty": "Välj en plats på kartan, sök efter en ort, eller använd din nuvarande plats för att se myggrisken.",

  "panel.metricHeadline": "{metric}: {category}",

  // Kicker line above the bare category headline (item 1 + item 8): the
  // very first thing on screen establishes "Myggrisk = bettrisk" before the
  // user even reads the category word below it. Myggläge deliberately has
  // no equivalent kicker -- "Måttlig myggförekomst" already says what it
  // means in one phrase, so splitting it the same way would add a line
  // without adding clarity.
  "panel.riskKicker": "Bettrisk {day}",

  "panel.abundanceHeadline.very_low": "Mycket låg myggförekomst",
  "panel.abundanceHeadline.low": "Låg myggförekomst",
  "panel.abundanceHeadline.moderate": "Måttlig myggförekomst",
  "panel.abundanceHeadline.high": "Hög myggförekomst",
  "panel.abundanceHeadline.very_high": "Mycket hög myggförekomst",
  "panel.abundanceExplain":
    "Bygger på tidigare väder och lokal naturmiljö (nederbörd, värme, våtmarker) – inte på vind eller temperatur just nu.",

  "panel.guidance.very_low": "Bra tid att vara utomhus. Låg risk att störas av mygg.",
  "panel.guidance.low": "Låg risk att störas av mygg.",
  "panel.guidance.moderate": "Måttlig risk. Den som är myggkänslig kan överväga myggmedel, särskilt nära vatten eller skog.",
  "panel.guidance.high": "Hög risk att störas av mygg. Myggmedel och heltäckande kläder rekommenderas.",
  "panel.guidance.very_high": "Mycket hög risk att störas av mygg. Använd myggmedel och skyddande kläder.",

  "panel.risingAfter": "Risken ökar {period}.",
  "panel.peakPeriod": "Högst risk väntas {period}.",
  "panel.peakAroundTime": "Högst risk {day}: omkring kl {time}.",
  "panel.whyTitleToday": "Vad påverkar risken idag?",

  // "Now vs. later today" (item 7): only shown when the category actually
  // changes between the current hour and today's peak -- a same-category
  // drift (e.g. 14 -> 16) is deliberately not "meaningful" enough to
  // mention, to avoid noise (see HourTimeline/ForecastCards for the
  // definition of "meaningful" = category change).
  "panel.nowVsPeak": "{nowCategory} bettrisk nu – {peakCategory} väntas kl {time}.",

  // Myggrisk-vs-Myggläge relationship copy (item 6) -- the two products can
  // genuinely disagree (lots of habitat but suppressed activity, or little
  // habitat but favourable activity conditions right now), and that
  // disagreement is one of the most useful things the app can say. Built
  // deterministically from the two already-computed category tiers, never
  // from an invented mechanism.
  "panel.relationship.abundanceHigherThanRisk":
    "Det finns sannolikt gott om mygg i området, men förhållandena håller nere bettrisken just nu.",
  "panel.relationship.riskHigherThanAbundance":
    "Myggförekomsten är {abundanceCategory}, men lugnt och varmt väder gör att bettrisken är hög just nu.",

  "panel.timeToday": "Idag kl {hour}",
  "panel.timeTomorrow": "Imorgon kl {hour}",
  "panel.timeDaypart": "{day} · {daypart}",

  "panel.activityAdjusted": "Anpassad för {activity}",
  "panel.viewingLayer": "Kartan och siffrorna nedan visar {layer}, inte myggrisk.",
  "panel.modelEstimate":
    "Modellens uppskattning: index {model}. Justerad med {count} nya rapporter i närheten: index {adjusted} (rapportvikt {weight}%).",

  "panel.technicalTitle": "Om siffrorna",
  "panel.indexLabel": "Index {value} av 100",
  "panel.coordinatesLabel": "Plats: {lat}, {lon}",
  "panel.modelDisclaimer":
    "Detta är ett modellberäknat riskindex baserat på väder och naturförhållanden. Det är inte ett uppmätt antal mygg.",

  "panel.population": "Myggförekomst",
  "panel.activity": "Myggaktivitet",
  "panel.exposure": "Risk att störas",
  "panel.dataQualityTitle": "Prognosunderlag",
  "panel.dataQualityExplain":
    "Visar hur mycket och hur bra underlag prognosen bygger på – inte hur farlig risken är.",
  "panel.whyTitle": "Vad påverkar risken just nu?",
  "panel.whyPeakTitle": "Vad påverkar risken när den är som högst?",
  "panel.explanationForPeak":
    "Förklaringen nedan gäller dagens högsta risknivå ({period}), inte nödvändigtvis vald tid.",
  "panel.whenChangesTitle": "När ändras det?",
  "panel.next7days": "Kommande 7 dagar",
  "panel.next48h": "Kommande 48 timmar",

  "panel.adviceTitle": "Vad bör jag göra?",
  "panel.advice.very_low": "Bra tid för promenad eller annan utomhusaktivitet.",
  "panel.advice.low": "Låg risk för de flesta utomhusaktiviteter.",
  "panel.advice.moderate": "Ta gärna med myggmedel om du är känslig eller stannar ute länge.",
  "panel.advice.high": "Ta med myggmedel och överväg heltäckande kläder.",
  "panel.advice.very_high": "Undvik våtmarker och skog om möjligt. Använd myggmedel.",

  // Myggläge has its own recommendation copy -- a different claim than
  // risk ("how mygg-friendly is this area", not "will you get bitten
  // right now"), so it needs its own tone (item 8 of the "simplify around
  // the user's mental model" iteration).
  "panel.abundanceAdvice.very_low": "Ovanligt myggfattig miljö. Låg risk för myggproblem här.",
  "panel.abundanceAdvice.low": "Måttligt myggvänlig miljö.",
  "panel.abundanceAdvice.moderate": "Myggrik miljö. Risken kan öka snabbt vid lugnt och varmt väder.",
  "panel.abundanceAdvice.high": "Mycket myggrik miljö, särskilt nära vatten eller våtmark.",
  "panel.abundanceAdvice.very_high": "Extremt myggrik miljö. Räkna med mygg så fort vädret är gynnsamt.",

  "panel.timelineTitle": "Läge under dagen",
  "panel.timelineAriaLabel": "Myggrisk time för timme, kl {hour}: {category}",
  "panel.timelinePeak": "Topp",

  "panel.cardsTitle": "Kommande dagar",
  "panel.cardToday": "Idag",
  "panel.cardTomorrow": "Imorgon",
  "panel.cardPeak": "Topp kl {time}",
  "panel.cardPeakUnknown": "Topp okänd",
  "panel.cardBest": "Lägst risk",
  "panel.cardWorst": "Högst risk",

  "panel.howItWorksTitle": "Hur fungerar prognosen?",
  "panel.detailsTitle": "Tekniska detaljer",

  "sheet.expand": "Visa mer",
  "sheet.collapse": "Visa mindre",
  "sheet.swipeUp": "Svep upp",
  "sheet.dragHandleLabel": "Dra för att visa mer eller mindre av prognospanelen",

  "panel.reportButton": "Rapportera hur mycket mygg du ser",
  "panel.shareButton": "Dela prognosen",
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
  "chart.now": "Nu",
  "chart.high": "Högst",
  "chart.low": "Lägst",

  "about.title": "Om prognosen",
  "about.howTitle": "Så fungerar prognosen",
  "about.howBody":
    "Prognosen kombinerar väderdata och naturförhållanden – till exempel nederbörd, temperatur, vind och närhet till våtmark och vatten – för att uppskatta hur mycket mygg som sannolikt finns och hur aktiva de är, timme för timme och för de kommande sju dagarna.",
  "about.sourcesTitle": "Datakällor",
  "about.sourcesBody":
    "Väderdata hämtas från SMHI:s öppna data. Uppgifter om terräng (skog, våtmark, vatten och höjd) bygger på ESA WorldCover, Naturvårdsverkets nationella marktäckedata (NMD) och höjddata från Copernicus. Platssökning använder en lokal ortförteckning samt OpenStreetMap/Nominatim.",
  "about.updateTitle": "Uppdatering",
  "about.updateBody": "Prognosen räknas om automatiskt ungefär var sjätte timme.",
  "about.limitationsTitle": "Begränsningar",
  "about.limitationsBody":
    "Detta är ett modellberäknat riskindex baserat på väder och naturförhållanden. Det är inte ett uppmätt antal mygg, och det är inte ett verktyg för att bedöma risk för myggburen sjukdom.",
  "about.close": "Stäng",

  "loading.map": "Laddar karta…",
  "loading.progress1": "Hämtar prognosdata…",
  "loading.progress2": "Läser in väderunderlag…",
  "loading.progress3": "Nästan klart…",
} as const;

export default sv;
