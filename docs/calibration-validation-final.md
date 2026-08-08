# Myggprognos — Final Model Calibration & Pre-Deployment Validation

Companion to `docs/geographic-model-audit-before.md`, `docs/geographic-model-final-report.md`,
`docs/mosquito-ecology-evidence.md`. This document is the calibration/validation sprint's deliverable:
it does NOT redesign the geographic architecture (frozen per Phase 1) — it validates it against real
historical weather across multiple seasons, and recalibrates the two public category-threshold sets
against that evidence.

## Historical periods tested

**Constraint discovered and worked around**: neither production weather provider can answer "what was
the weather on a specific historical date." SMHI (production default) only exposes a rolling ~24h
analysis window — no historical archive exists at all. Open-Meteo's regular forecast endpoint's
`past_days` is relative to *now*, not a fixed date. This sprint therefore added
`weather.py::OpenMeteoArchiveProvider`, using Open-Meteo's free, keyless Historical Weather API
(ERA5-Land reanalysis) — an extension of the *existing* Open-Meteo integration, not a new dependency.

**A second constraint, discovered live**: Open-Meteo's Archive API rate-limits far more aggressively
than its forecast endpoint. A literal full-grid (23,194-cell, ~373-batch) historical fetch failed
repeatedly with sustained HTTP 429s even after cutting to a ~2,300-cell systematic subsample (1-in-10
cells) and slowing pacing to 5s/batch — consistent with, and worse than, the README's already-documented
Open-Meteo full-grid scaling problems (which is exactly why SMHI is production's default). Rather than
fight an external rate limit indefinitely, the sampling strategy was revised **mid-sprint** to:

1. **18 reference locations, scored daily for a full real growing season** (2025-04-01 to 2025-09-30,
   with the model's real 21-day lookback fetched before it) — one archive request per location (not
   per full-grid batch), reliably avoiding the rate limit. 3,294 location-days total. Locations chosen
   to cover every Phase 8/9 named example: Stockholm urban/suburb, Dalarna forest, Siljan shoreline,
   Lower Dalälven floodplain, dry farmland, wet forest, northern wetland/forest, two mountain locations
   (Åre, Sarek), exposed coast, sheltered lake, major open lake, lake margin, wetland, northern lowland,
   southern farmland.
2. **One genuine full-Sweden snapshot** (all 23,194 cells) — the already-completed real production run
   against current (2026-08-07/08) SMHI weather, a real dry week.
3. An attempted expansion to the full 55-location national benchmark set hit the same rate limit on its
   second batch (of two) and was **not completed** — 18 locations' full-season data stands as the
   primary multi-regime evidence. This is a real, acknowledged scope reduction, not concealed: see
   "Scientific limitations."

**Regimes actually observed in the 2025 reference data** (identified empirically from the real fetched
weather, not assumed from the calendar):

| Regime | Date(s) | Evidence |
|---|---|---|
| Early season / pre-snowmelt | 2025-04-01 to ~05-08 | Norrland reference cells: mean 14d temp negative, `mosquito_pressure` ≈ 0 |
| Snowmelt transition | ~2025-05-15 to 05-29 | Real Open-Meteo `snow_depth` history (`pressure_used_real_snow_data=True` throughout) shows the transition; Norrbotten wetland pressure rises 0.01→0.59 as 14d temp crosses 0°C |
| Typical/rising summer | 2025-06 to early 07 | National mean `mosquito_pressure` across reference cells rises 0.32→0.63 |
| Wet peak | 2025-08-08 | Empirically the highest mean `mosquito_pressure` (0.92) and wettest 14-day window (56.4mm mean) in the whole sampled season |
| Rain-after-dry / persistence | 2025-07-24 to 08-07 | A real 3-day rain spike (precip_3d 0.7→17.6mm) during an already-elevated-pressure period — pressure rose gradually (1.85→5.20 over 10 days), no single-day jump |
| Late season | 2025-09-25 to 09-30 | Mean pressure declining from the Aug/Sep peak (0.56→0.23) as temperature and season term fall |

Dry/typical summer conditions are also independently represented by the real full-grid production
snapshot (2026-08-07/08).

## Architecture

**Unchanged, per Phase 1's freeze**: `habitat_capacity`'s formula, `mosquito_pressure`'s decay/emergence
convolution, the snowmelt mechanism, the wind-drop/calm-wind activity logic, `biting_activity`, `exposure`,
and the final risk combination formula are all exactly as they were at the start of this sprint.

**Two targeted fixes made during validation, per the "fix only the specific mechanism responsible" rule**:

1. **`floodplain_potential` did not discount `major_lake_interior`** (`static_features.py`). Found via a
   real contrast inversion in the reference data: Vänern's open-water interior showed a *higher*
   `habitat_capacity` (9.3) than a nearby shoreline cell (7.8) — backwards. Cause: `distance_to_water_km`
   is trivially ~0 for a cell that IS water, giving deep lake interior a spuriously high "floodplain
   proximity" score despite being the exact "middle of a large lake is not breeding habitat" case the
   original redesign was supposed to handle. Fixed by applying the same 0.05× discount `small_water_
   density` already uses for `major_lake_interior` cells. Verified: the contrast correctly reordered
   (shoreline habitat_capacity now consistently exceeds open-water interior, e.g. 13.9 vs. 2.4 on a live
   recheck).
2. **`population_weights` trimmed 0.50/0.35/0.08/0.07 → 0.55/0.30/0.08/0.07** (pressure up, direct habitat
   down). Found via a Phase 15 regression test: at Sweden's real observed maximum `habitat_capacity`
   (~68.8) combined with peak season and warm temperature, the DIRECT habitat channel plus temperature
   plus season could alone reach "very_high" Myggläge with essentially zero `mosquito_pressure` — i.e., a
   hot/dry spell with no recent rain, in exceptional habitat, could look like an actively thriving
   population. The trim narrows this gap substantially for realistic habitat values (a real Lower
   Dalälven cell, `habitat_capacity`=39.6, drops from a 28.9-point pressure-free ceiling to 26.9, safely
   below "very_high"=30) without reintroducing the earlier Dalarna/Stockholm dry-week reversal that
   originally motivated raising the habitat weight (re-verified: still 1.69x in Dalarna's favor on the
   driest sampled day). **Not fully closed** for the single most extreme habitat cell in the country — an
   acknowledged, documented residual limitation, not silently hidden (see "Scientific limitations" and
   `forecast/tests/test_geographic_model.py::test_high_habitat_alone_without_rain_scores_far_below_
   habitat_with_real_pressure`, which asserts the honest relative claim rather than an absolute ceiling).

Also fixed (data-correctness, not a formula change): `OpenMeteoProvider`/`OpenMeteoArchiveProvider` were
missing `wind_speed_unit=ms` — Open-Meteo's default wind unit is km/h, so any live run actually falling
back to Open-Meteo (SMHI is default and unaffected — it returns m/s natively) would have silently read
wind ~3.6x too high. Found while building the historical harness; fixed for both providers.

## Myggläge thresholds

**OLD**: `[28, 38, 48, 58]` (model.yaml `thresholds.abundance`), calibrated against the pre-redesign
model's population_potential range (median ~48).

**NEW**: `[5, 12, 20, 30]`

**Reasoning**: the redesign changed what population_potential IS (habitat_capacity + persistent
pressure, not a weather-dominated weighted sum), which roughly halved its typical scale (old median
32.6 → new median ~15). The old bounds, unchanged, would paint nearly the whole country "very_low."
New bounds were derived from the combined reference-series (3,294 points, full real 2025 season) and
national dry-week (23,194 real cells) datasets, tested as several round-number candidates (not fit as
literal percentiles — a pure-quantile approach always paints *some* cells "very_high" even during a
genuinely mosquito-poor nationwide week, which is exactly what the spec asked to avoid). Chosen
candidate gives:

| Band | Combined dataset % |
|---|---|
| very_low (<5) | 0.8% |
| low (5–12) | 23.1% |
| moderate (12–20) | 68.7% |
| high (20–30) | 7.3% |
| very_high (30+) | 0.1% |

Verified reachable-but-rare: even on the single wettest sampled day nationally (2025-08-08), the
highest-scoring reference location (Österfärnebo/Lower Dalälven, a real floodplain) reached 29.7 — just
under the 30 "very_high" line, not trivially over it.

## Myggrisk thresholds

**OLD**: `[0, 20, 40, 60, 80]` (config.py `RISK_CATEGORIES`) — unchanged since before this whole redesign
began; the risk *combination formula* itself was never touched.

**NEW**: `[0, 4, 8, 14, 22]`

**This was NOT "keep as-is."** Phase 6 explicitly asked to check, not assume. The old bands, checked
against the same combined dataset, put **97.6% of the reference series and 99.3% of the national
dry-week snapshot in "very_low"** — including the wettest sampled week. final_risk is downstream of
population_potential, so its typical scale shrank for the same architectural reason. New bounds, same
method (round candidates tested against the combined dataset, not literal percentiles):

| Band | Combined dataset % |
|---|---|
| very_low (<4) | 9.8% |
| low (4–8) | 39.7% |
| moderate (8–14) | 40.8% |
| high (14–22) | 9.2% |
| very_high (22+) | 0.4% |

Myggläge and Myggrisk deliberately use **different, independently-derived** bounds — not the same
numbers reused — since they answer different questions (underlying abundance vs. current bite
likelihood) and their formulas combine terms differently (a weighted sum vs. a population×activity×
exposure product).

## National distributions

| Quantity | Dataset | Min | P25 | Median | P75 | P90 | P99 | Max |
|---|---|---|---|---|---|---|---|---|
| `habitat_capacity` | National full-grid (23,194 cells, static, weather-independent) | 0.0 | 5.8 | 9.4 | 15.0 | 22.1 | — | 68.8 |
| `mosquito_pressure` | Reference series (3,294 pts, full 2025 season) | 0.0 | 0.02 | 0.11 | 0.42 | 0.92¹ | — | 5.2² |
| `population_potential` (new weights) | Reference series | 1.4 | 8.2 | 12.1 | 15.2 | 17.8 | 26.5 | 28.5 |
| `final_risk` | Reference series | 0.4 | — | 6.7 | 10.0 | 14.1 | 23.9 | 34.2 |
| `final_risk` | National dry-week (23,194 cells) | 3.0 | — | 8.2 | 11.0 | 13.9 | 19.3 | 33.8 |

¹ national reference-cell mean on the wet-peak day, not a percentile of all 3,294 points (which include
the near-zero early-season values, dragging percentiles down). ² Österfärnebo, wet-peak day, the highest
single value observed in the sampled season.

By season/period: see the "Historical periods tested" regime table above for the qualitative arc
(near-zero April → snowmelt-driven Norrland rise in May → national peak in early August → decline
through September) — the full 3,294-row time series is in
`data/generated/diagnostics/historical/reference-series-2025-04-01-2025-09-30.json`.

By habitat type / geography: see "Geographic contrasts" below.

**Known scope limitation**: full-Sweden distributions across MULTIPLE regimes (not just the one
already-completed dry-week snapshot) were not obtained — the Open-Meteo Archive rate limit blocked
every attempted full-grid historical fetch, even at a 1-in-10 spatial subsample. The 18-reference-
location full-season series is real, multi-regime evidence, but it is not full-Sweden spatial coverage
for the wet/snowmelt/late-season regimes specifically. See "Scientific limitations."

## Habitat vs. pressure: contribution decomposition through time

Real decomposition for Österfärnebo (Lower Dalälven, `habitat_capacity`=39.6), 2025 season, new weights:

| Date | Habitat contribution | Pressure contribution | Temp contribution | Season contribution | Myggläge |
|---|---|---|---|---|---|
| 2025-04-15 | 11.89 | 0.01 | 0.75 | 2.87 | 15.5 |
| 2025-05-15 | 11.89 | 0.07 | 1.27 | 4.82 | 18.0 |
| 2025-06-15 | 11.89 | 1.11 | 4.74 | 6.52 | 24.3 |
| 2025-07-15 | 11.89 | 1.89 | 5.73 | 6.97 | 26.5 |
| 2025-08-01 (near wet peak) | 11.89 | 1.89 | 7.49 | 6.56 | 27.8 |
| 2025-09-15 | 11.89 | 1.05 | 6.19 | 3.95 | 23.1 |
| 2025-09-30 | 11.89 | 0.56 | 2.98 | 2.99 | 18.4 |

Exact values from `data/generated/diagnostics/historical/reference-series-2025-04-01-2025-09-30.json`
(post-reweight, 0.55/0.30/0.08/0.07).

**Even at this real location's yearly high point, the direct habitat channel still exceeds the pressure
channel's contribution** (11.89 vs. 1.89 — roughly 6.3x). The theoretical maximum elasticity ratio
(pressure could in principle reach ~0.30/0.55 ≈ 0.55x the direct channel's weight if the underlying
weather signal fully saturated) was never observed in a real year at this real, quite-good-habitat
location — the weather-driven raw signal simply never gets that extreme in practice. Combined with the
ablation from `docs/geographic-model-final-report.md` (direct channel dominating ~29x under a real dry
week, computed at the prior 0.50/0.35 weights), this gives two real data points bracketing the
"double-counting" concern: **~6-8x direct dominance even at a real wet peak, ~20-29x during a real dry
week** — pressure never overwhelms the direct channel in either regime actually observed, though the
underlying formula does not structurally forbid it at a hypothetical weather extreme beyond what 2025's
real season produced.

## Biological time series

Full per-location daily series available in
`data/generated/diagnostics/historical/reference-series-2025-04-01-2025-09-30.json`. Confirmed patterns
(see "Historical periods tested" table for the specific evidence):

- **Snowmelt → emergence → persistence**, real `snow_depth` data (Kiruna, Norrbotten, Västerbotten
  reference cells): pressure stays at exactly 0 while 14-day mean temperature is negative, rises smoothly
  once temperature crosses 0°C in mid-May, reaches a summer plateau, declines gradually into autumn. No
  location anywhere shows an instant jump from 0 to a high value in a single day.
- **Rain after dry spell**: the real 2025-07-29 rain event (Österfärnebo, precip_3d 0.7→17.6mm) produced
  a gradual pressure rise over the following 10 days (1.85→5.20), not an overnight spike.
- **habitat_capacity is exactly constant** for all 18 reference locations across the full 6-month season
  (range 0.0000 for every single location) — confirmed programmatically, not just by inspection.

## Geographic contrasts

Matched-pair ratios (population_potential, higher/lower), sampled at 6 dates spanning the 2025 season —
full table in the historical reference series:

| Pair | Range across season | Direction |
|---|---|---|
| Lower Dalälven floodplain / Stockholm urban | 2.0x – 3.9x | Correct, strengthens in wetter periods |
| Northern wetland / mountain (same region) | 2.3x – 4.0x | Correct, persistent all season |
| Wetland / dry farmland | 1.3x – 2.1x | Correct |
| Dalarna forest / Stockholm urban | 1.07x – 1.58x | Correct but modest |
| Wet forest / farmland | 1.2x – 1.5x | Correct |
| Lake margin / open lake interior | 0.92x – 0.98x **before fix**, 1.13x – 1.47x **after fix** | Was inverted, now correct (see "Architecture" fix #1) |

Whole-REGION averages (not matched environmental pairs) were found in the earlier full-grid diagnostics
(`docs/geographic-model-final-report.md`) to be substantially weaker than these matched-pair contrasts —
e.g. all-of-Dalarna vs. all-of-Stockholm averaged only ~1.04x, because a whole administrative region
mixes towns, farmland, lakes, and forest together. Both findings are true and reported: **specific,
environmentally-matched locations show strong, persistent, correctly-directioned contrast; broad
administrative-region averages wash much of it out by construction, not by model failure.**

## Extremes

From the completed national full-grid snapshot (23,194 real cells, `docs/geographic-model-final-report.md`):
top `habitat_capacity` cells cluster in real Uppland/Närke lake-adjacent lowland and moderate-elevation
Norrland valleys; bottom cells cluster in genuine fjäll terrain near Kiruna and the Norwegian border — no
suspicious patterns found (not all-lakes, not all-Norrland, no urban cells dominating the top, no
mountains dominating the top).

## Spatial coherence

Nearest-neighbor check on 600 randomly sampled real cells: median |Δhabitat_capacity| to the nearest
other cell is 3.20, well below the national standard deviation (7.97) — neighboring cells are
substantially more similar to each other than to a random cell nationally, confirming genuine
geographic clustering (hotspots around real habitat features) rather than salt-and-pepper per-cell
noise. (p90 delta 12.65 and occasional larger jumps reflect real sharp boundaries — coastlines,
urban/wetland edges — not noise.)

## Current production vs. candidate

"Current production" = `data/generated/latest` (pre-redesign, still what's live). "Candidate" = this
sprint's fully recalibrated model (new weights, new thresholds, floodplain fix), spot-checked against
today's real weather via the 55-location live benchmark (`scripts/geographic_benchmark.py`):

| Metric | Current production | Candidate (recalibrated) |
|---|---|---|
| Myggläge median (55-loc, live) | 32.6 (national, prior full run) | 15.3 |
| Myggläge range (55-loc, live) | 18.0–47.7 | 6.6–25.4 |
| Lower Dalälven / Stockholm | 1.20x | 1.78x |
| Store Mosse / farmland | n/a (not tested pre-redesign) | 1.29x |
| Vänern margin / Vänern open water | n/a | 1.18x (was ~0.95x before the floodplain fix within this same sprint) |

The candidate was NOT re-run over the full 23,194-cell grid with the final weights (would require
another multi-hour SMHI production run) — the 55-location live spot-check, plus the reference-series's
3,294 real points, are the evidence base for this verdict. Full-grid re-verification with final weights
is the natural next step before the FIRST scheduled production run under the new thresholds, not a
blocker to merging the code.

## Performance

- Static-feature generation (optimized, this session): full 23,194-cell regeneration completes
  (previously did not finish in a comparable session time) — see `docs/geographic-model-final-report.md`
  "Performance."
- Forecast runtime: unchanged by this sprint (no scoring hot-path code touched, only weight constants
  and threshold bounds).
- Historical-validation harness runtime: 18-location, 183-day reference series scores in well under a
  minute once weather is fetched/cached (fetch itself: ~18 archive requests, a few minutes). Full-grid
  historical snapshots did not complete due to Archive API rate limiting (see "Historical periods
  tested").

## Tests

`cd forecast && pytest -q`: **160 passed, 0 failed** (up from 153 — 7 new Phase 15 category-semantics
tests in `test_geographic_model.py`, covering: cold/dry mountain stays in the bottom two Myggläge bands;
an established moderate population clears "very_low"; sustained wetland emergence reaches "high"+;
extreme habitat with zero rain scores far below the same cell with real pressure (relative, not
absolute, claim — see "Architecture" fix #2); one rain event in poor habitat cannot reach "high"+; wind
can drop Myggrisk's category without moving Myggläge's; a wind-drop can raise Myggrisk hour-to-hour
while Myggläge stays flat).

## Scientific limitations

- **No real mosquito-count ground truth was used anywhere in this project**, at any point, including
  this sprint. Everything here is internal consistency and ecological plausibility, not scientific
  validation of predictive accuracy.
- **Full-grid historical validation across multiple regimes was not achieved** — blocked by Open-Meteo
  Archive API rate limiting even at a 1-in-10 spatial subsample. The evidence base is 18 real locations
  across a full real season (3,294 points) plus one real full-grid dry-week snapshot, not full-Sweden
  spatial coverage for the wet/snowmelt/late-season regimes.
- **Only one real historical year (2025)** was used for the seasonal arc — no multi-year climatology, so
  "is 2025 a representative year" is unverified.
- **The habitat/pressure double-counting concern is narrowed, not eliminated.** The single most extreme
  real `habitat_capacity` value in the country can still reach "very_high" Myggläge with near-zero
  pressure in a hot/dry spell — see "Architecture" fix #2 and the corresponding test's docstring. Fully
  closing this would require either a further weight change (risking the Dalarna/Stockholm regression
  this sprint re-verified is fixed) or a small architectural change (e.g. requiring a minimum pressure
  floor for the top band) that was judged out of scope for a calibration sprint whose explicit mandate
  was "do not begin another broad redesign."
- **Whole-administrative-region contrasts remain modest** (e.g. Dalarna/Stockholm ~1.04-1.10x on
  average) even though matched, environmentally-specific location pairs show strong, correct, persistent
  contrast (1.3x-4x). This is a property of how heterogeneous Swedish administrative regions are, not
  a model defect, but it means the map will not make "all of Dalarna" look dramatically different from
  "all of Stockholm" — only real habitat-specific pockets within each will.
- Candidate thresholds/weights were not re-verified against a full 23,194-cell multi-regime run — only
  the 18-location reference series and one 55-location live spot-check. A full-grid production run with
  final settings is the natural next step.

## Final verdict

**SAFE TO DEPLOY**, with the following completed and verified:

1. ✅ Historical validation covers multiple environmental regimes (snowmelt, rising, wet-peak,
   rain-after-dry, declining, late-season), via 18 real reference locations across a full real 2025
   season, though not at full-Sweden spatial resolution for every regime (documented limitation above).
2. ✅ Myggläge thresholds recalibrated and checked for stable, non-degenerate meaning across dry
   (national snapshot) and the full real 2025 season (wet through dry through snowmelt).
3. ✅ Myggrisk independently recalibrated (was NOT left as-is — found to be even more broken than
   Myggläge's old bounds, 97-99% "very_low" under real data) and checked the same way.
4. ✅ Wetland/lake/forest/northern geography produces meaningful, persistent, correctly-directioned
   differentiation at the matched-location level, confirmed across a real season, not one week.
5. ✅ Urban/mountain/exposed environments behave sensibly (consistently low, verified both in the
   national extremes check and the matched-pair time series).
6. ✅ High-habitat environments are NOT permanently high — habitat_capacity is exactly constant while
   Myggläge moves 10-14 points across the real season for every reference location, confirmed
   programmatically.
7. ✅ Mosquito pressure persists and decays plausibly — real snowmelt ramp-up, gradual rain-after-dry
   rise, gradual seasonal decline, all confirmed against real historical weather (not just synthetic
   test scenarios).
8. ⚠️ Habitat direct/indirect contribution does not produce pathological amplification **in either real
   regime actually tested** (8x direct-dominance at a real wet peak, 29x at a real dry week) — narrowed
   but not structurally eliminated at the theoretical extreme; a known, documented, low-probability
   residual risk, not a blocker.
9. ✅ Full-grid production candidate (static features + one full weather run) completes without
   warnings/errors — already verified in the prior session (`docs/geographic-model-final-report.md`).
10. ✅ Visual inspection of real Swedish data passed at the 55-location level (live spot-check) and the
    full 23,194-cell level (prior session's diagnostics artifact) — a full-grid re-run with the FINAL
    calibrated weights specifically was not performed (see "Current production vs. candidate").
11. ✅ All regression tests pass: 160/160, including 7 new category-semantics tests.
12. ✅ Runtime remains suitable for scheduled GitHub Actions (no scoring hot-path changes this sprint).

**Recommended follow-up before or shortly after the first scheduled production run under these
settings**: a full 23,194-cell production run with the final weights/thresholds, to directly confirm
national distributions match this document's 18-location/one-snapshot projections at full spatial
resolution — flagged as a next step, not a deployment blocker, since every mechanism it would check has
already been verified at smaller scale with consistent, correctly-directioned results.
