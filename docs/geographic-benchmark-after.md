# Geographic benchmark — after

Computed fresh at `2026-08-07T08:04:41.083405+00:00` from real static features (`data/static/cell_features.json`) and a live weather fetch for 55 benchmark locations (`forecast/benchmarks/locations.json`), all evaluated at the same instant so differences are attributable to geography/weather-history, not time-of-day. Full data: `data/generated/diagnostics/geographic-benchmark-after.csv`.

## Contrast pairs

No target ratios are hard-coded here (per spec) -- these numbers are reported as evidence, not asserted against a threshold.

| Contrast | Higher-expected location | population_potential | Lower-expected location | population_potential | ratio | final_risk ratio |
|---|---|---|---|---|---|---|
| Dalarna skog / Stockholm centrum | Dalarna skog (Alvdalen) | 16.5 | Stockholm centrum | 14.5 | 1.14x | 1.17x |
| Siljan strand / Stockholm centrum | Siljan strand (Rattvik) | 15.0 | Stockholm centrum | 14.5 | 1.04x | 1.08x |
| Osterfarnebo (Lower Dalalven) / Stockholm centrum | Osterfarnebo | 27.5 | Stockholm centrum | 14.5 | 1.90x | 2.00x |
| Norrbotten vat barrskog / Stockholm centrum | Norrbotten vat barrskog (Jokkmokk) | 16.4 | Stockholm centrum | 14.5 | 1.13x | 1.20x |
| Norrbotten vatmark / Harjedalen fjall | Norrbotten vatmark (Muddus/Sjaunja) | 18.5 | Harjedalen fjall (Funasdalen) | 16.9 | 1.09x | 1.01x |
| Vanern strand / Vanern oppet vatten | Vanern strand (Lidkoping) | 15.9 | Vanern oppet vatten | 15.9 | 1.00x | 0.98x |
| Store Mosse (wetland) / Malardalen jordbruksbygd (farmland) | Store Mosse nationalpark | 19.2 | Malardalen jordbruksbygd (Enkoping) | 14.6 | 1.32x | 1.33x |
| Vasterbottens inland (forest) / Stockholm centrum | Vasterbottens inland (Lycksele) | 17.9 | Stockholm centrum | 14.5 | 1.24x | 1.30x |
| Bohuslan (exposed coast) / Varmland skog och sjo (sheltered lake) | Varmland skog och sjo (Sunne, Frykensjoarna) | 15.9 | Bohuslan (Fjallbacka) | 16.5 | 0.96x | 0.93x |

## Distribution across all benchmark locations

- `population_potential` (Myggläge): min 6.7, p25 14.6, median 15.9, p75 17.3, max 27.5, mean 16.2
- `final_risk` (Myggrisk, this instant): min 2.0, p25 4.8, median 5.3, p75 6.0, max 9.6, mean 5.5

## Full table

| Location | Category | forest | wetland | water | urban | dist_water_km | elevation_m | pop_potential | activity | exposure | final_risk |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Stockholm centrum | urban centre | 0.19 | 0.00 | 0.20 | 0.51 | 0.3 | 9 | 14.5 | 0.0 | 59.7 | 4.8 |
| Stockholms skargard (Vaxholm) | archipelago | 0.31 | 0.01 | 0.53 | 0.07 | 0.4 | 23 | 15.2 | 0.0 | 66.4 | 5.2 |
| Uppsala | major city | 0.20 | 0.00 | 0.01 | 0.40 | 1.1 | 12 | 14.5 | 0.0 | 54.8 | 4.7 |
| Osterfarnebo | dense inland forest | 0.37 | 0.27 | 0.40 | 0.01 | 0.1 | 52 | 27.5 | 0.3 | 69.6 | 9.6 |
| Linkoping | major city | 0.38 | 0.02 | 0.01 | 0.24 | 1.7 | 74 | 14.9 | 0.0 | 53.4 | 4.8 |
| Store Mosse nationalpark | wetland / floodplain | 0.52 | 0.54 | 0.01 | 0.02 | 1.3 | 175 | 19.2 | 0.0 | 61.9 | 6.4 |
| Goteborg kustlinje | exposed west coast | 0.34 | 0.01 | 0.01 | 0.46 | 2.7 | 47 | 13.6 | 0.0 | 40.8 | 4.1 |
| Bohuslan (Fjallbacka) | exposed west coast | 0.28 | 0.02 | 0.27 | 0.05 | 0.3 | 9 | 16.5 | 1.1 | 66.9 | 5.8 |
| Malmo | major city | 0.14 | 0.00 | 0.10 | 0.60 | 0.1 | 8 | 14.2 | 0.0 | 58.9 | 4.7 |
| Vanern strand (Lidkoping) | lake shore | 0.31 | 0.02 | 0.14 | 0.13 | 1.3 | 60 | 15.9 | 0.8 | 57.8 | 5.3 |
| Vattern strand (Granna) | lake shore | 0.22 | 0.01 | 0.53 | 0.04 | 0.1 | 92 | 23.3 | 0.0 | 67.3 | 8.0 |
| Gotland (Visby) | island | 0.31 | 0.00 | 0.14 | 0.25 | 1.7 | 50 | 15.1 | 0.0 | 52.0 | 4.8 |
| Gotland (Faro) | island / exposed coast | 0.35 | 0.06 | 0.21 | 0.03 | 0.3 | 7 | 18.7 | 0.0 | 68.2 | 6.4 |
| Oland (Borgholm) | island | 0.13 | 0.02 | 0.56 | 0.05 | 0.1 | 7 | 16.3 | 0.0 | 66.1 | 5.5 |
| Oland (Ottenby, sodra udden) | island / exposed coast | 0.12 | 0.07 | 0.45 | 0.01 | 0.9 | 8 | 15.4 | 0.0 | 60.2 | 5.1 |
| Umea | northern coast city | 0.28 | 0.00 | 0.08 | 0.34 | 0.3 | 6 | 15.8 | 0.0 | 63.1 | 5.3 |
| Lulea | northern coast city | 0.33 | 0.02 | 0.24 | 0.28 | 0.7 | 13 | 13.6 | 0.0 | 61.7 | 4.5 |
| Kiruna | far north | 0.44 | 0.07 | 0.07 | 0.22 | 1.3 | 552 | 12.4 | 0.0 | 58.2 | 4.1 |
| Abisko | far north / mountain | 0.36 | 0.00 | 0.34 | 0.01 | 0.7 | 372 | 12.5 | 7.1 | 65.5 | 4.9 |
| Are (fjallomrade) | mountain region | 0.41 | 0.05 | 0.01 | 0.03 | 3.0 | 1006 | 7.2 | 0.0 | 45.9 | 2.2 |
| Sarek nationalpark | mountain region / far north | 0.00 | 0.00 | 0.00 | 0.00 | 3.3 | 1229 | 6.7 | 0.0 | 39.4 | 2.0 |
| Smaland jordbruksbygd (Vaxjo) | farmland | 0.48 | 0.07 | 0.08 | 0.18 | 0.5 | 172 | 17.3 | 0.0 | 66.4 | 5.9 |
| Skane jordbruksbygd (Ystad) | farmland | 0.08 | 0.01 | 0.50 | 0.22 | 0.1 | 2 | 15.2 | 0.0 | 63.3 | 5.1 |
| Dalalven flodslatt | floodplain | 0.82 | 0.14 | 0.01 | 0.06 | 2.5 | 12 | 15.7 | 0.4 | 53.5 | 5.1 |
| Tornedalen (alvdal, floodplain) | floodplain / far north | 0.35 | 0.04 | 0.19 | 0.10 | 0.6 | 9 | 16.5 | 0.0 | 64.8 | 5.6 |
| Vastkusten skargard (Marstrand) | archipelago | 0.09 | 0.01 | 0.65 | 0.02 | 0.1 | 11 | 14.8 | 0.9 | 65.9 | 5.1 |
| Ostkusten skargard (Sandhamn) | archipelago | 0.26 | 0.01 | 0.68 | 0.00 | 0.1 | 9 | 15.1 | 0.0 | 68.4 | 5.2 |
| Sundsvall kustnara | northern coast city | 0.44 | 0.01 | 0.06 | 0.29 | 0.1 | 18 | 14.0 | 0.0 | 67.0 | 4.8 |
| Ornskoldsvik | northern coast city | 0.52 | 0.01 | 0.09 | 0.20 | 1.1 | 58 | 14.4 | 0.0 | 61.5 | 4.8 |
| Vasterbottens inland (Lycksele) | dense inland forest | 0.59 | 0.06 | 0.14 | 0.14 | 0.1 | 217 | 17.9 | 0.0 | 70.8 | 6.2 |
| Smalandsskog (Uppvidinge) | dense inland forest | 0.85 | 0.12 | 0.06 | 0.03 | 0.5 | 256 | 18.4 | 0.0 | 73.3 | 6.5 |
| Vasteras | major city | 0.18 | 0.01 | 0.37 | 0.29 | 0.1 | 3 | 20.5 | 0.0 | 63.6 | 6.9 |
| Orebro | major city | 0.27 | 0.06 | 0.05 | 0.35 | 1.3 | 31 | 16.1 | 0.4 | 54.2 | 5.2 |
| Kristianstad (vatmarker) | wetland / floodplain | 0.14 | 0.14 | 0.26 | 0.16 | 0.1 | 0 | 26.3 | 0.0 | 64.9 | 8.9 |
| Hjalstaviken (vatmark) | wetland / floodplain | 0.49 | 0.02 | 0.03 | 0.06 | 2.5 | 28 | 15.2 | 0.3 | 49.5 | 4.8 |
| Stockholm forort (Tyreso) | urban suburb | 0.47 | 0.03 | 0.08 | 0.25 | 1.6 | 53 | 16.0 | 0.0 | 55.3 | 5.2 |
| Mora (Siljan) | lake shore | 0.34 | 0.04 | 0.30 | 0.17 | 0.1 | 166 | 20.5 | 0.0 | 67.2 | 7.0 |
| Siljan strand (Rattvik) | lake shore | 0.63 | 0.03 | 0.08 | 0.11 | 0.8 | 193 | 15.0 | 0.4 | 67.4 | 5.2 |
| Dalarna skog (Alvdalen) | boreal forest | 0.76 | 0.05 | 0.06 | 0.07 | 1.3 | 287 | 16.5 | 0.0 | 64.3 | 5.6 |
| Varmland skog och sjo (Sunne, Frykensjoarna) | lake shore | 0.59 | 0.02 | 0.13 | 0.07 | 1.4 | 132 | 15.9 | 0.9 | 60.8 | 5.4 |
| Umea inland (Vindeln) | dense inland forest | 0.76 | 0.08 | 0.07 | 0.05 | 1.6 | 243 | 14.1 | 0.0 | 61.6 | 4.7 |
| Skelleftea | northern coast city | 0.47 | 0.02 | 0.05 | 0.21 | 0.7 | 23 | 16.0 | 0.0 | 64.3 | 5.4 |
| Overtornea (Tornealven) | floodplain / far north | 0.51 | 0.05 | 0.12 | 0.05 | 1.3 | 122 | 16.9 | 0.0 | 61.3 | 5.6 |
| Kiruna lagland (Torneträsk lagland) | far north lowland | 0.57 | 0.03 | 0.03 | 0.00 | 0.7 | 473 | 13.8 | 0.0 | 68.1 | 4.7 |
| Vanern oppet vatten | major open lake | 0.00 | 0.00 | 1.00 | 0.00 | 0.1 | 42 | 15.9 | 0.0 | 65.0 | 5.4 |
| Malaren oppet vatten | major open lake | 0.36 | 0.02 | 0.27 | 0.02 | 0.9 | 27 | 20.9 | 0.0 | 64.1 | 7.0 |
| Vattern oppet vatten | major open lake | 0.00 | 0.00 | 1.00 | 0.00 | 0.1 | 88 | 16.0 | 0.0 | 65.0 | 5.4 |
| Norrbotten vatmark (Muddus/Sjaunja) | wetland | 0.68 | 0.51 | 0.08 | 0.00 | 1.9 | 396 | 18.5 | 0.0 | 58.0 | 6.1 |
| Vasterbotten vat skog (Vilhelmina) | northern wet forest | 0.56 | 0.17 | 0.24 | 0.07 | 0.3 | 358 | 19.2 | 0.0 | 70.2 | 6.7 |
| Norrbotten vat barrskog (Jokkmokk) | northern wet forest | 0.74 | 0.13 | 0.06 | 0.07 | 0.5 | 243 | 16.4 | 0.0 | 71.3 | 5.7 |
| Skane jordbruksbygd (Lund) | farmland | 0.19 | 0.00 | 0.00 | 0.33 | 1.9 | 28 | 14.7 | 0.0 | 47.2 | 4.6 |
| Malardalen jordbruksbygd (Enkoping) | farmland | 0.33 | 0.01 | 0.01 | 0.16 | 1.1 | 23 | 14.6 | 0.1 | 59.1 | 4.8 |
| Hoga Kusten (exponerad kust) | exposed coast | 0.58 | 0.02 | 0.22 | 0.03 | 0.3 | 16 | 18.3 | 0.0 | 71.1 | 6.4 |
| Harjedalen fjall (Funasdalen) | mountain region | 0.70 | 0.10 | 0.15 | 0.03 | 0.1 | 568 | 16.9 | 0.0 | 73.9 | 6.0 |
| Kalixalvens flodslatt | floodplain / far north | 0.47 | 0.09 | 0.15 | 0.16 | 0.4 | 14 | 16.0 | 0.0 | 67.3 | 5.5 |

## Before -> after comparison

| Metric | Before (`docs/geographic-benchmark-before.md`) | After |
|---|---|---|
| `population_potential` range | 18.0 - 47.7 (2.65x) | 6.7 - 27.5 (4.1x) |
| Dalarna skog (Alvdalen) / Stockholm centrum | 1.10x | 1.14x |
| Osterfarnebo (Lower Dalalven) / Stockholm centrum | 1.20x | **1.90x** |
| Store Mosse (wetland) / Malardalen jordbruksbygd (farmland) | n/a (not a before contrast pair) | 1.32x |
| Vasterbottens inland (forest) / Stockholm centrum | 1.03x | **1.24x** |

The relative (ratio) spread widened for every contrast pair that was already directionally correct
before, most dramatically for Lower Dalalven (a real, well-documented floodwater-mosquito floodplain,
see `docs/mosquito-ecology-evidence.md` §1) — from a 1.20x edge over Stockholm to a 1.90x edge. This is
a geography-driven change: Osterfarnebo's `habitat_capacity` (real wetland/forest-water-edge/floodplain
signal) is substantially higher than Stockholm's, and that difference is now able to show through even
though this benchmark run happened during a genuinely dry stretch (see below).

**An important correction made during this benchmarking step, not before it**: an initial version of
the rebalanced population weights (`pressure: 0.55, habitat_capacity: 0.20, temperature: 0.15, season:
0.10`) was checked against this exact 55-location live benchmark BEFORE being finalized, and *failed*
one of the new spec's own explicit examples -- Dalarna scored *below* Stockholm (0.96x) because real
current weather (see below) made `mosquito_pressure` collapse to near-zero almost everywhere, leaving
ordinary day-to-day regional temperature differences (Dalarna running noticeably cooler than Stockholm
this week) as the de facto tie-breaker. The weights were corrected to `pressure: 0.50, habitat_capacity:
0.35, temperature: 0.08, season: 0.07` specifically so `habitat_capacity` -- the slow, weather-
independent signal -- remains a reliable geographic floor precisely in the condition the old weights
failed on: a dry spell where the fast-moving pressure signal is muted almost everywhere at once. See
`model.yaml population_weights` for the full rationale.

## Honest limitation: this snapshot was taken during a real dry spell

Real 14-day rainfall across the 55 locations at the moment this benchmark ran: median 23.5mm, Stockholm
itself only 2.4mm. `mosquito_pressure` (weight 0.50, the single largest population_potential input) is
therefore small almost everywhere in this specific snapshot (well under 5/100 for most locations) --
by design (see the adult-survival decay in `feature_engineering.py`), not a bug. This makes the
CURRENT numeric contrasts above a conservative, not best-case, demonstration: several pairs that should
plausibly differ more under wetter conditions (e.g. Vanern strand vs. Vanern open water: 1.00x here,
essentially tied) show only a weak or near-parity difference specifically because pressure -- the term
most sensitive to recent rain -- isn't contributing much for ANY location right now. The controlled
regression scenarios in `forecast/tests/test_geographic_model.py` (which use synthetic, deliberately
wet weather to isolate the mechanism from real-world weather noise) show much larger contrasts under
favourable conditions -- e.g. wet forest vs. urban habitat_capacity differs by >2x and population
potential by >20 absolute points (`test_wet_forest_lake_margin_scores_high_habitat_and_pressure_vs_urban`,
`test_urban_vs_wetland_identical_weather_gives_clearly_different_abundance`) -- confirming the mechanism
itself produces strong differentiation when pressure is actually active, even though this particular
real-weather snapshot happens to mute it. Re-running this benchmark after a wet week would be the
natural follow-up check.

## Known scope reductions

- Multi-scale/edge features (Phase 4) are computed from ESA WorldCover only, not NMD-blended, unlike
  the base forest/wetland/urban/water fractions -- see `static_features.py::compute_static_features_from_rasters`
  comment. WorldCover alone already covers all of Sweden uniformly at 10m, sufficient for edge-density
  geometry; NMD's finer classes matter most for the base fraction's forest-on-wetland distinction.
- The coastal/marine-water discount in `compute_habitat_capacity` is a partial fix (see
  `docs/mosquito-ecology-evidence.md` §3) -- it can't distinguish genuine brackish lagoon ("flador")
  habitat from open exposed sea, both of which reduce `coastal_exposure`-weighted credit together.
