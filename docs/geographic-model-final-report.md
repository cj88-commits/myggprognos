# Geographic model redesign — final report

Summary of the full sprint (`docs/geographic-model-audit-before.md` → this document). Companion documents:
`docs/geographic-benchmark-before.md`, `docs/geographic-benchmark-after.md`, `docs/mosquito-ecology-
evidence.md`, `docs/spatial-resolution-assessment.md`.

## Architecture

### OLD

```
population_potential = weighted sum of 8 terms:
    temperature (0.22)   -- 14d mean temp, sigmoid
    rainfall (0.22)       -- emergence_potential (rain-lag x degree-day development)
    moisture (0.14)       -- 7d soil moisture, sigmoid
    wetland (0.13)        -- static wetland_fraction, linear x1.8
    forest (0.07)         -- static forest_fraction, linear x1.3
    season (0.07)         -- day-of-year bell curve, width narrows with latitude
    snowmelt (0.05)       -- day-of-year bell curve ONLY, identical every cell in Sweden
    standing_water (0.10) -- decayed recent rain x wetland/water/slope gate

biting_activity = product of 5 terms (temp, humidity, wind, daypart, rain-suppression) x calm-wind uplift
exposure = terrain_exposure (forest/urban) + water_proximity
final_risk = population x activity_modifier x exposure_modifier, rescaled
```

Static geography touched population_potential in exactly two unconditional places (`wetland`,
`forest`, combined weight 0.20) plus two rain-gated places (`standing_water`, `rainfall`'s
`site_persistence` factor). `urban_fraction` and `elevation_m` had **zero** effect on population
potential at all. `water_body_density` was, in the real data path, an exact duplicate of
`water_fraction` rather than an independent multi-scale signal. No persistent population state existed
— every hour/day's `population_potential` was recomputed independently from a 21-day rolling weather
window, with no adult-survival decay. See `docs/geographic-model-audit-before.md` for the full,
quantified trace.

### NEW

```
habitat_capacity (0-100, static_features.py, computed ONCE per cell) =
    weighted sum of: wetland_fraction_5km, forest-water/wetland-water edge density,
    small_water_density (major-lake-interior and marine-coastline discounted),
    floodplain_potential (slope+wetland+water-proximity proxy), shoreline_density, forest_fraction
    x urban_suppression x elevation_suppression

mosquito_pressure (0-100, feature_engineering.py, per cell/hour) =
    (1 - survival_daily) x sum_{d=0}^{20} emergence(today - d) x survival_daily^d
    where emergence(day) = habitat_capacity_fraction x (rain-driven-development-gated signal
                                                          + snowmelt-driven signal for that day)
    -- the closed-form of "pressure_today = surviving_adults(previous_pressure x survival)
                                              + recent_emergence(habitat x emergence_conditions)"

population_potential (Myggläge) = weighted sum of:
    pressure (0.50), habitat_capacity (0.35), temperature (0.08), season (0.07)
    -- revised from an initial 0.55/0.20/0.15/0.10 split after full-grid testing found the
       original weights let ordinary regional temperature differences reverse the Dalarna/
       Stockholm contrast during a real dry week; see "National diagnostics" below.

biting_activity (Myggrisk's wind/time-of-day component) = UNCHANGED from before this iteration
exposure = UNCHANGED from before this iteration
final_risk (Myggrisk) = UNCHANGED combination formula from before this iteration
```

The activity/exposure/combination layers were deliberately left untouched — this iteration's scope was
specifically the geographic/population side (per the new spec's explicit instruction not to remove the
calm-wind behaviour or radically redesign the combination). The separation the new spec asked for
(Myggläge = pressure/habitat, weather-history-driven; Myggrisk = activity, current-hour-driven) was
already structurally true for `biting_activity` before this iteration (it never touched population); what
changed is that `population_potential` no longer has any current-instant weather sensitivity at all
beyond the modest 0.08-weight `temperature` term (14-day mean, not current hour).

## New variables and their source

| Variable | Source | Computed |
|---|---|---|
| `habitat_capacity` | `static_features.py::compute_habitat_capacity`, from real ESA WorldCover 10m + `sweden_lakes.geojson` (47 named lakes) + DEM elevation | Once per cell (static layer) |
| `water_fraction_500m/2km/5km`, `wetland_fraction_500m/2km/5km` | ESA WorldCover, one ~50m/px 5km-radius raster read per cell, cropped to 3 radii | Once per cell |
| `shoreline_density`, `forest_water_edge_density`, `wetland_water_edge_density` | Pixel-adjacency proxy on the same WorldCover read | Once per cell |
| `small_water_density`, `major_lake_interior` | `water_fraction_2km` discounted by (a) STRtree lookup against the 47 named major lakes, (b) `coastal_exposure` (marine-water discount) | Once per cell |
| `floodplain_potential` | Slope (DEM) + `wetland_fraction_2km` + `distance_to_water_km` proxy | Once per cell |
| `mosquito_pressure` | `feature_engineering.py`'s daily rain/degree-day + snowmelt convolution, decayed by `pressure_survival_daily` | Per cell/hour, from the existing 21-day rolling weather window |
| `snow_depth_m` (weather field) | Open-Meteo's real `snow_depth` hourly parameter (new); `None` throughout for SMHI/synthetic | Fetched per run |
| `pressure_used_real_snow_data` | Diagnostic flag: real snow history vs. latitude-timing fallback | Per cell/hour |

All are published in generated output (`cells.json.gz` for the static ones, hourly/daily records for
`habitat_capacity`/`mosquito_pressure`) — see `output.py`/`pipeline.py` changes.

## Geographic benchmark: before vs. after

55 real Swedish locations (`forecast/benchmarks/locations.json`, up from 34), evaluated with real static
features and a live weather fetch at the same instant. Full tables: `docs/geographic-benchmark-before.md`
/ `-after.md`.

| Contrast | Before | After |
|---|---|---|
| `population_potential` national range (this benchmark) | 18.0 - 47.7 (2.65x) | 6.7 - 27.5 (4.1x) |
| Dalarna skog (Älvdalen) / Stockholm centrum | 1.10x | 1.14x |
| Österfärnebo (Lower Dalälven floodplain) / Stockholm centrum | 1.20x | **1.90x** |
| Västerbottens inland forest / Stockholm centrum | 1.03x | **1.24x** |
| Store Mosse (wetland) / farmland | n/a | 1.32x |

The live-weather snapshot used for this benchmark happened to fall during a real dry spell (median
14-day rainfall 23.5mm across the 55 locations), which mutes `mosquito_pressure` (weight 0.50, the
single largest population term) almost everywhere at once — see `docs/geographic-benchmark-after.md`'s
"Honest limitation" section. The **controlled regression scenarios** in
`forecast/tests/test_geographic_model.py` (synthetic, deliberately wet weather, isolating the mechanism
from real-world weather noise) show much larger contrasts:

- Wet forest habitat vs. urban: `habitat_capacity` 64.1 vs. 0.16 (>400x); `population_potential` 44.0
  vs. 22.8 (+21 points).
- Vegetated lake margin vs. open lake interior: `habitat_capacity` 59.2 vs. 1.55 (38x).
- Poorly-drained forest vs. dry farmland: `habitat_capacity` 39.3 vs. 2.27 (17x).
- Northern mountain: `habitat_capacity` 0.0 regardless of latitude/season.

## National diagnostics (full 23,194-cell grid, real SMHI weather)

Superseding the earlier 55-location-only benchmark: `prepare_static_features.py --real` was optimized
(removed a redundant raster read, dropped NMD's water-search — see "Performance" — and parallelized
across CPU cores) and run to completion over the full grid, followed by a full production pipeline run
(`scripts/run_forecast.py` equivalent, real SMHI weather) to a separate output directory
(`data/generated/latest_new_geo_model`, not overwriting the committed `data/generated/latest`).
`scripts/national_diagnostics.py` compares the two full datasets directly. Interactive report (all
charts, all 23,194 cells' distributions, region tables): the published diagnostics artifact linked in
the session; underlying data: `data/generated/diagnostics/national-diagnostics.json` and
`-all-cells.csv`.

**Distributions** (all 23,194 cells):

| Quantity | Min | Median | Mean | Max | Std dev |
|---|---|---|---|---|---|
| `habitat_capacity` (new) | 0.0 | 9.4 | 11.2 | 68.8 | 8.0 |
| `mosquito_pressure` (new) | 0.0 | 0.001 | 0.072 | 1.72 | 0.14 |
| `population_potential` (Myggläge) old | 12.4 | 32.6 | 31.0 | 51.7 | 7.9 |
| `population_potential` (Myggläge) new | 7.2 | 15.0 | 14.9 | 37.6 | 3.6 |
| `final_risk` (Myggrisk) old | 5.2 | 17.3 | 16.8 | 32.5 | 5.7 |
| `final_risk` (Myggrisk) new | 3.0 | 8.2 | 8.8 | 33.8 | 3.7 |

**Spatial variance, old vs. new**: absolute std dev is *lower* for the new model on both
`population_potential` (7.86 → 3.60) and `final_risk` (5.70 → 3.73) — the new distribution is not more
spread out in absolute terms, it's shifted down and somewhat compressed. Coefficient of variation (std/
mean, which normalizes for the lower mean) is essentially unchanged for `population_potential` (0.253 →
0.243) and up for `final_risk` (0.339 → 0.425) — relative spread is roughly flat to modestly higher, not
dramatically higher. **The redesign's real win is not "more national variance" — it's that the
variance that exists is now attributable to actual geography instead of incidental same-week weather**
(see the largest-change cells below).

**Region contrasts** (whole-region area averages, not hand-picked points — Stockholm/Dalarna/Lower
Dalälven/Norrland/mountain/urban/lake-margin, defined by lat-lon boxes ± elevation/urban/small-water
filters):

| Region (n cells) | mean habitat_capacity | mean Myggläge old | mean Myggläge new |
|---|---|---|---|
| Stockholm (74) | 6.8 | 35.7 | 16.1 |
| Dalarna (702) | 12.9 | 39.0 | 16.7 |
| Lower Dalälven (172) | 12.0 | 38.5 | 17.6 |
| Norrland, lat≥63.5° (10,761) | 11.8 | 25.9 | 13.3 |
| Mountain/fjällen (1,609) | 3.8 | 18.7 | 9.8 |
| Urban, urban_fraction>0.4 (17) | 2.2 | 31.7 | 14.1 |
| Lake margin, top-quartile small water (5,807) | 17.6 | 31.1 | 17.2 |

Dalarna/Stockholm: **1.040x in the new model vs. 1.092x in the old** — a *weaker* whole-county contrast
than before, even though the point-benchmark comparison in the earlier section showed 1.14x. Averaging
over an entire heterogeneous county (or the whole of Norrland, spanning fjäll to floodplain in one
10,761-cell bucket) washes out real local hotspots — Lower Dalälven specifically (a known floodplain,
not the whole surrounding county) holds a real ~10% edge over Stockholm in both models, and the
extremes (top/bottom 100 cells by `habitat_capacity`, in the diagnostics artifact) are geographically
sensible: top cells cluster in real Uppland/Närke lake-adjacent lowland and moderate-elevation Norrland
valleys; bottom cells cluster in genuine fjäll terrain near Kiruna and the Norwegian border. **The
redesign differentiates real extremes correctly; it does not yet produce dramatically different broad
regional averages**, and that's a materially more honest characterization than the point-benchmark
alone would suggest.

**Largest old→new changes**: the 100 cells with the biggest swing are dominated by a geographic cluster
in Västra Götaland (Borås/Ulricehamn area) that dropped 31-35 points, from *near the old model's
historical maximum* to a modest, habitat-consistent value (`habitat_capacity` 4-15, unremarkable). This
is the redesign doing exactly its job: the old model let one warm/wet week push ordinary terrain to
near-maximum population_potential; the new model correctly refuses to, because the underlying habitat
there isn't actually exceptional.

**Habitat double-counting — measured, not assumed**: `habitat_capacity` enters `population_potential`
directly (weight 0.35) and indirectly via `mosquito_pressure = habitat_fraction × weather_signal`
(weight 0.50). An ablation across all 23,134 non-zero-habitat cells, isolating each channel's swing from
a national-median-habitat counterfactual, found the **direct channel dominates by ~29x under this
week's real weather** (max swing 20.8 points vs. 0.71 points for the pressure channel) — because
`mosquito_pressure` itself is near-zero almost everywhere right now (dry week). `correlation(habitat_
capacity, mosquito_pressure) = 0.380` across all cells — real but moderate, not near-1. **This is not
proof the double-counting is harmless in general** — only that it's harmless *this week*. Analytically,
population_potential's total elasticity to habitat_capacity ranges from the labeled 0.35 (when the
weather-driven raw signal is ~0) up to ~0.85 (0.35 direct + 0.50 via a saturated pressure channel) during
a sustained wet spell — unverified at national scale since no such period was available to test against
in this session. Re-checking after a real wet week is a recommended follow-up, not yet done.

## Geographic differentiation: quantified

`habitat_capacity` alone (the pure geography component, no weather at all) spans **0.0 to 64.1** across
the benchmark/test locations exercised — urban centres and mountains reliably score under 5, wet
forest/wetland/floodplain terrain reliably scores 20-65. This did not exist as a standalone,
weather-independent quantity before this iteration; the closest prior equivalent (`wetland`+`forest`
terms, combined weight 0.20 of `population_potential`) could not by itself separate "dense but dry pine
forest" from "wet, water-threaded forest", since both saturate `forest_fraction` similarly (see
`docs/geographic-model-audit-before.md` §5).

## Persistence example

`forecast/tests/test_geographic_model.py::test_dry_spell_after_established_population_declines_gradually_not_instantly`
runs the same wet-forest habitat through 14 days of sustained rain (population builds up), then steps
forward through 5 additional dry days: `mosquito_pressure` declines monotonically but never in one
single step accounting for the whole decline (`biggest_single_step_drop < total_drop`), and remains
strictly positive after all 5 dry days — consistent with `pressure_survival_daily = 0.90` implying
~59% of peak pressure should still remain after 5 dry days (`0.9^5 ≈ 0.59`), not zero.

## Northern behaviour without a latitude bonus

`test_snowmelt_with_habitat_and_warmth_produces_meaningful_northern_pressure` gives a northern wetland
cell (66.9°N) a real declining snow-depth series plus accumulated warmth: `pressure_used_real_snow_data`
is `True` and `mosquito_pressure > 5`. `test_northern_mountain_stays_low_despite_same_latitude_as_wetland`
gives a mountain cell at the **same latitude and same weather** essentially zero `habitat_capacity`
(elevation suppression) and correspondingly near-zero pressure — proving the mechanism responds to real
per-cell habitat and snow/temperature history, not to latitude directly. No `if latitude > X: bonus`
exists anywhere in the new code; the only latitude-dependent term is the SMHI-fallback melt-date shift
(`_fallback_snowmelt_day_signal`), which only changes *when* the fallback signal peaks, not how high it
can reach, and is fully gated by real per-cell `habitat_capacity` regardless.

## Water behaviour

`test_large_open_lake_is_not_automatically_extreme_habitat` / `test_vegetated_lake_margin_scores_higher_than_lake_interior`:
a vegetated lake margin scores `habitat_capacity` 59.2 vs. 1.55 for the same lake's open interior — a
>38x difference from geometry alone (major-lake-interior detection via `sweden_lakes.geojson`), not a
hand-coded exception.

## Performance

- Full pipeline correctness: `python scripts/run_forecast.py --sample` (5-cell sample grid, synthetic
  weather) completes end-to-end (weather fetch → scoring → sanity checks → output) with zero warnings
  in ~1.5s.
- `compute_features` throughput (the function the new pressure/snowmelt logic lives in): microbenchmark
  of 3,850 calls (≈ 50 cells × 77 hourly+daypart calls each) → 0.53ms/call, extrapolating to **≈757s
  (~12.6 minutes)** for the full ~18,600-cell × 77-call production workload, vs. the previously
  documented "~6 minutes... on this alone" for the whole scoring pass (README). This is a real,
  measured **roughly 2x increase in `compute_features` cost**, from the new ~21-iteration daily
  rain/snowmelt series computed per call. Still far below the GitHub Actions 360-minute job ceiling, and
  consistent with the README's own prior finding that CPU was never the pipeline's bottleneck — network/
  weather-fetch time dominates total runtime, not scoring. Not optimized further in this iteration (e.g.
  caching pressure per cell/calendar-day instead of per cell/hour) since the margin to the actual
  ceiling remains large; flagged here as the first lever to pull if that ever changes.
- Static-feature regeneration (`scripts/prepare_static_features.py --real`, a manual/occasional
  maintenance step, not part of the scheduled 6-hourly pipeline): profiling found each `ds.read()` call
  costs ~15-90ms, dominated by fixed per-call overhead, not window size — and NMD's 15km water-search
  specifically cost ~88ms/cell against a non-overview-having 11.3-billion-pixel raster (`ds.overviews(1)
  == []`), the single most expensive operation in the whole pipeline. Fixed by (a) merging the redundant
  2.5km fraction read into the existing 5km multi-scale read (one fewer raster read per cell), (b)
  dropping NMD's water-search entirely in favor of the already-computed WorldCover distance-to-water
  (NMD's genuine value — forest/wetland subtype detail — is unaffected), (c) parallelizing across CPU
  cores (`ProcessPoolExecutor`, cells chunked evenly across workers rather than grouped by raster tile,
  since Sweden's real cell density varies hugely between the 22 WorldCover tiles). A full 23,194-cell run
  completed successfully afterward with zero placeholder cells.
- Full production pipeline run (new model, real SMHI weather, all 23,194 cells,
  `data/generated/latest_new_geo_model`): completed with **zero warnings**. Wall-clock time is not a
  clean data point for this particular run (it spanned an intentional multi-hour session pause), so no
  runtime regression claim is made for the full pipeline beyond the `compute_features` microbenchmark
  above.

## Tests

`cd forecast && pytest -q`: **153 passed**, 0 failed (26 pre-existing, unrelated NumPy deprecation
warnings from `rasterio`'s array-shape handling). Includes 11 new regression scenarios in
`test_geographic_model.py` covering all 12 scenarios requested (two combined into one test), plus fixes
to 2 pre-existing tests whose assumptions were tied to the old population-term breakdown
(`test_model.py::test_population_potential_between_0_and_100`,
`test_wind_calm_regression.py::test_scenario7_...`).

## Scientific limitations (explicit)

Restated from `docs/mosquito-ecology-evidence.md` — nothing here should be read as validated against
real mosquito counts:

- No real Swedish/Nordic mosquito trap-count data was used anywhere, at any point in this project.
- `habitat_capacity`'s term weights were calibrated by checking rank plausibility against the 55-
  location benchmark, not against any independent habitat-quality dataset.
- Floodplain/snowmelt/small-water are all raster/DEM-only proxies for real hydrological processes
  (actual inundation extent, actual melt timing, actual vegetated-margin extent) that were not
  integrated, per the explicit "avoid complicated external dependencies" constraint.
- `pressure_survival_daily = 0.90` is a defensible literature mid-point (see
  `docs/mosquito-ecology-evidence.md` §4), not fitted to any Swedish-specific survival study, and does
  not vary with temperature/humidity as real survival does.
- The coastal/marine-water discount in `habitat_capacity` cannot distinguish genuine brackish lagoon
  ("flador") habitat from open exposed sea — both are discounted together.
- Multi-scale/edge features use WorldCover only, not NMD-blended (documented scope reduction, see
  `docs/geographic-benchmark-after.md`).
- The 55-location "after" benchmark ran during a real dry spell, muting the demonstrated contrast
  relative to what the mechanism produces under the controlled/wetter regression-test scenarios — see
  that document's "Honest limitation" section.
- Region-level (whole-county/region) contrasts are real but modest — see "National diagnostics" above.
  The strong contrasts shown in the point-benchmark section are real for the specific named locations
  tested, not necessarily representative of broad regional averages.
- The habitat/pressure double-counting ablation was only checked against one real (dry) week; its
  behavior under a wet spell, when `mosquito_pressure` is actually large, is analytically predicted but
  not empirically verified at national scale.

## Final verdict: is this safe to commit and deploy?

**Not yet, as-is.** The architecture is sound — real geographic mechanisms, not weather-dominance, now
drive Myggläge, verified against the complete real 23,194-cell Sweden grid, not a sample. But two
concrete issues, both discovered only once the full national dataset existed, need resolving first:

1. **`model.yaml`'s `thresholds.abundance` bands (`[28, 38, 48, 58]`) are now miscalibrated, not just
   outdated.** National median `population_potential` dropped from 32.6 to 15.0 and the new maximum
   (37.6) sits below the old "high" threshold (48). Under the current bands, the live Myggläge map would
   render almost uniformly "very low" — the same visual failure this project exists to fix, from a
   different mechanism. This is evidence-based recalibration against a quantity that now means something
   different, exactly the kind of update `model.yaml`'s own documented history already does when a
   formula changes (see its `combination:` section's calibration notes) — not the cosmetic threshold-
   tuning the brief explicitly warned against. It should happen before deploy, not after.
2. **Region-level differentiation is real but weaker than the point-benchmark alone suggested** — worth
   a decision (accept as reflecting genuine regional homogeneity within e.g. "all of Dalarna," or adjust
   weights further) rather than silently shipping on the strength of the point-benchmark numbers alone.

Both are judgment calls, not something to auto-resolve. Everything else checks out: 153/153 backend
tests pass, the full pipeline runs end-to-end with zero warnings on real data, the double-counting risk
is measured (not assumed) and currently small, and every major mechanism (habitat capacity, persistent
pressure, snowmelt, water multi-scale, floodplain proxy) is backed by cited literature-vs-assumption
documentation in `docs/mosquito-ecology-evidence.md`.
