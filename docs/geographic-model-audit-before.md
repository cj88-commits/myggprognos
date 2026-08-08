# Geographic model audit — before this iteration

Companion to `docs/model-audit-before.md` (which covered the population×activity×exposure
*combination* bug) and `docs/model-audit-after.md`/`docs/wind-calm-investigation.md` (which fixed
that combination and added shelter-adjusted wind). This document is scoped narrowly to **geography**:
exactly how static/GIS inputs currently reach the final score, and why the live map reads as "a
weather map with a modest habitat correction" rather than a mosquito-population map. Read-only —
no code changed while writing this.

Sources read: `forecast/src/{model,feature_engineering,static_features,config,pipeline,confidence}.py`,
`forecast/model.yaml`, `data/static/` contents, `scripts/{download_static_gis_data,prepare_static_features,
prepare_cell_geometry,static_data_audit}.py`.

## 1. Inventory: every static/geographic input that exists on disk

Computed once by `static_features.py::compute_static_features_from_rasters`, cached in
`data/static/cell_features.json` (committed, ~18.6k cells, real data — confirmed present locally with
worldcover/, dem/, nmd/ raster tiles and `is_placeholder: false`).

| field | source | spatial scale | notes |
|---|---|---|---|
| `forest_fraction` | WorldCover class 10, NMD-overridden south of ~62°N | 2.5km radius window (`_FRACTION_RADIUS_KM`), ~50m/px | |
| `wetland_fraction` | WorldCover 90/95, NMD-overridden | 2.5km radius window | NMD adds tree-covered wetland (sumpskog/tallmossar) south of 62°N only — see README limitations |
| `urban_fraction` | WorldCover 50, NMD-overridden | 2.5km radius window | |
| `water_fraction` | WorldCover 80, NMD-overridden | 2.5km radius window | **stored in `StaticFeatures` but never copied into `FeatureSet` — see §4.1** |
| `distance_to_water_km` | nearest WorldCover/NMD water pixel | 15km radius search, capped at 15km if none found | single nearest-distance value; no notion of shoreline density or margin habitat |
| `elevation_m` | Copernicus DEM GLO-30 | 0.5km radius window, ~30m/px | **computed, published to `cells.json`, never read by `model.py` — see §4.2** |
| `slope_deg` | DEM gradient over the same window | 0.5km radius window | used only in 2 places, see §2 |
| `coastal_exposure` | distance to `sweden_boundary.geojson` coastline | point-to-nearest-segment, decays over 10km | used only inside wind shelter, see §2 |
| `water_body_density` | **literally `round(water_fraction, 3)` again** in the real path | 2.5km window (same as `water_fraction`) | **not an independent signal — see §4.3, this is a bug** |

Additionally present on disk but **entirely unused by the pipeline**:

- `data/static/sweden_lakes.geojson` — 47 real, named individual lake polygons (Vänern, Vättern,
  Mälaren, Siljan, etc., used today only by `scripts/prepare_cell_geometry.py` to clip cell polygons
  for the frontend's paintable-land rendering). No code anywhere derives shoreline proximity,
  lake-margin-vs-open-water, or lake size from this file for the *model* — it is purely a rendering
  asset today, despite being exactly the kind of source Phase 4/5 need (open lake interior vs.
  vegetated shoreline requires per-lake geometry, not a pixel classification alone).
- Raw NMD 54-class raster (`data/static/nmd/NMD2023bas_v2_1.tif`) is collapsed into the same four
  forest/wetland/urban/water buckets as WorldCover before it ever reaches the model — its ~15 mire/
  wetland subtypes (open bog vs. tree-covered mire vs. floodplain wet meadow, etc., see
  `static_features.py` class-code comments) and its forest-on-wetland vs. forest-on-firm split are
  used only to *decide* forest/wetland fraction membership, then discarded. None of that finer
  structure (e.g. "how much of this cell's wetland is a mire complex vs. floodplain") survives into
  any model input.
- Snow: **no snow parameter is fetched from any weather provider at all.** `SMHI_FORECAST_BASE_URL`
  contains the substring `snow1g`, but that is SMHI's *model product name* (a short-range forecast
  model), not a snow-depth/snow-water-equivalent parameter — `smhi_weather.py`'s parameter map
  (`PARAMETER_MAP` region, confirmed by reading the file) only requests temperature/precipitation/
  wind/humidity, the same as `OpenMeteoProvider`. There is no snow accumulation, snow-cover, or
  snowmelt-timing data anywhere in the codebase today.

## 2. Where each geographic input actually flows into scoring

Traced through `model.py` and `feature_engineering.py`, weight/effect noted from `model.yaml`:

| input | population_potential | emergence/standing_water | biting_activity | exposure | confidence |
|---|---|---|---|---|---|
| `forest_fraction` | `forest` term, weight **0.07**, linear ×1.3 clamped | inside `_site_persistence_factor` (`0.4+0.6·wetland`, forest not included) — no | via `compute_effective_wind` (shelter −0.35 weight) → only feeds the **calm-wind uplift multiplier**, not the base wind-suppression curve | `terrain_exposure` **+0.20** | no |
| `wetland_fraction` | `wetland` term, weight **0.13**, linear ×1.8 clamped | **yes** — inside `_site_persistence_factor` (`0.4+0.6·wetland`), which multiplies both `standing_water` (weight 0.10) and `emergence_potential` (= the `rainfall` term, weight **0.22**) | no | removed (see `docs/model-audit-after.md` §1) | no |
| `urban_fraction` | **not used anywhere in population_potential** | no | via `compute_effective_wind` (shelter −0.15 weight, small) | `terrain_exposure` **−0.20** | no |
| `water_fraction` | **not used — field isn't even copied into `FeatureSet`** | no | no | no | no |
| `water_body_density` (≡ `water_fraction`, see §4.3) | inside `_site_persistence_factor` (`0.5+0.5·water_density`), feeding `standing_water` (0.10) and `emergence_potential`/`rainfall` (0.22) | — | no | removed | no |
| `distance_to_water_km` | not used | not used | not used | `water_proximity`, weight **0.35** of `base_exposure` | no |
| `slope_deg` | inside `_site_persistence_factor` (drainage, `1 − slope/15`) → same 0.10 + 0.22 paths as wetland | — | via `compute_effective_wind` (slope shelter, small, weight 0.10, capped at 10°) | no | no |
| `coastal_exposure` | not used | not used | via `compute_effective_wind` only (weight 0.25) | not used | no |
| `elevation_m` | **not used anywhere** | — | not used | not used | not used |
| `latitude` | `season` term width narrows with latitude (peak day fixed at 190 regardless of latitude); also used by `daylight_hours()`, whose output (`FeatureSet.daylight_hours`) is **computed and stored but never read by `model.py`** | — | not used | not used | not used |
| snow / snowmelt timing | `snowmelt` term (weight 0.05) is `bell_curve(day_of_year, optimum=135, width=40)` — **identical for every cell in Sweden on a given day**, no geographic or accumulated-snow input at all | — | not used | not used | not used |

## 3. Quantified: how much of `population_potential` (≈ Myggläge) is geography vs. weather/date?

Summing `model.yaml population_weights`:

```
temperature  0.22   weather (14-day mean temp) — same shape everywhere, no geographic gate
rainfall     0.22   weather × site_persistence gate (site_persistence includes wetland/water/slope,
                    but the gate gets closer to 1.0, i.e. "no penalty", for ANY cell with decent
                    wetland+water+drainage — it doesn't distinguish "how much better than average")
moisture     0.14   weather (soil moisture 7d mean) — no geographic gate at all
wetland      0.13   geography (direct)
forest       0.07   geography (direct)
season       0.07   date, weakly latitude-adjusted (width only, not peak timing)
snowmelt     0.05   date ONLY — zero geographic variation
standing_water 0.10 weather (recent rain) × geography (wetland/water/slope gate)
------
geography (direct, unconditional): 0.13 + 0.07                       = 0.20
weather/date terms with NO geographic gate at all:                     0.22+0.14+0.07+0.05 = 0.48
weather terms geography only *gates* (multiplicatively, not additively): 0.22 + 0.10        = 0.32
```

Even generously counting every geography-*gated* weather term as "geography," at most **0.52** of the
population-potential weight has any geographic sensitivity, and only **0.20** is unconditionally
geographic (i.e. would still separate Stockholm from Dalarna in a week of *identical* weather).
`urban_fraction`, `elevation_m`, `coastal_exposure`, and any real snow signal contribute **zero**
weight to population_potential. This is the direct, quantified mechanism behind "the current model
appears to let current/recent weather dominate geography too much": under identical weather, a
Stockholm cell and a Dalarna forest cell differ only by their `wetland`/`forest` term values (weight
0.20 combined) and by how much the `rainfall`/`standing_water` gates happen to differ (weight up to
0.32, but the gate saturates quickly — see §5) — nothing else in the formula can tell them apart.

## 4. Bugs / structural problems found

### 4.1 — `water_fraction` is computed but discarded

`static_features.py::StaticFeatures.water_fraction` is real, raster-derived, and written to
`data/static/cell_features.json`. `feature_engineering.py::FeatureSet` has no `water_fraction` field
and `compute_features` never reads `static.water_fraction` — it reads `static.water_body_density`
instead (see 4.3). The real per-cell open-water fraction is silently dropped between the static-data
layer and the model.

### 4.2 — `elevation_m` and `daylight_hours` are dead model inputs

Both are computed (from real DEM data / real astronomical calculation respectively), stored in their
dataclasses, and even published to the frontend (`elevation_m` via `cells.json.gz`) — but neither is
read by any function in `model.py`. Nothing today suppresses population/activity for a high-elevation
mountain cell (Sarek, Abisko highlands) except whatever incidental effect temperature/freezing have —
a warm, wet mountain-valley week with locally elevated wetland_fraction can currently score
identically to lowland terrain at the same weather. This is the direct mechanism behind the "high
mountains must not automatically become high mosquito areas" *risk*, but currently it's addressed by
omission (elevation does nothing) rather than by design — there's no explicit high-elevation
suppression at all, real or otherwise, it just happens that mountain cells are also usually cold/dry
enough that the (unrelated) temperature/moisture terms suppress them incidentally.

### 4.3 — `water_body_density` is not an independent signal from `water_fraction`

The docstring in `static_features.py`'s results loop says: *"water_body_density: water coverage over
the same wide window used for the distance search, i.e. 'how much open water is in this area' as
distinct from 'is there any water immediately in this cell' (water fraction above)"* — describing an
intent to compute it over the wider `_WATER_SEARCH_RADIUS_KM` (15km) window, distinct from the 2.5km
`water_fraction` window. The actual code does not do this:

```python
results.append(StaticFeatures(
    ...
    water_body_density=round(water, 3),   # `water` here is the SAME 2.5km-window value as water_fraction
))
```

`water` in that line comes from `_land_cover_features`'s 2.5km-window tuple, not from the 15km search
array used for `dist_water`. So `water_body_density == water_fraction` exactly, always, in the real
data path (confirmed: both round the identical float). Every place that claims to use "water body
density" as a broader-context signal (`_site_persistence_factor`, i.e. both the `standing_water` and
`rainfall`/emergence population terms) is actually just reusing the narrow local water-pixel fraction
a second time. This directly contradicts the new spec's water-modelling requirement for genuinely
multi-scale features (Phase 4) — today there is only one scale (2.5km) for any water-adjacent
static input, dressed up as two differently-named fields.

Note this is separate from (and in the *opposite* direction of) the placeholder generator
(`generate_placeholder_static_features`), which *does* compute a distinct
`water_body_density = 0.5·water_fraction + 0.5·random`. So placeholder-mode and real-mode data have
different (and both wrong, for different reasons) relationships between these two fields — another
argument for replacing `water_body_density` with genuinely multi-scale, well-defined features rather
than patching this one function.

### 4.4 — `wetland_fraction` (and, via `water_body_density`, `water_fraction`) is reused across three
of `population_potential`'s eight weighted terms

Not literally double-counted the way exposure's old wetland term was (`docs/model-audit-before.md`
#5, already fixed) — the three uses are structurally different (a direct linear term; a multiplicative
gate inside `emergence_potential`/`rainfall`; a multiplicative gate inside `standing_water`) — but all
three read the *same single 2.5km-window raster value* with no decorrelation, and there is currently
no single, once-computed "how good is this landscape at making mosquitoes" quantity that they all
derive from. This is exactly the gap Phase 3 (`habitat_capacity`) exists to fill: right now, "habitat
quality" is implicitly smeared across `wetland` (0.13), `forest` (0.07), and the two
`site_persistence`-gated terms (rainfall 0.22, standing_water 0.10) — tuning any one of those weights
in isolation doesn't behave like tuning "how much habitat matters" as a whole, because the same
underlying raster keeps reappearing with different multipliers and different co-factors (rain amount
in one case, slope+water_density in another) alongside it.

### 4.5 — `urban_fraction` never suppresses `population_potential`

The single strongest "this location structurally can't support many mosquitoes" real-world
signal — built-up/paved/sealed urban land — is read in exactly one place: `compute_exposure`'s
`terrain_exposure` term (weight −0.20 of a 0.55 base, i.e. a mild human-encounter deduction), and
weakly inside `compute_effective_wind`'s shelter multiplier (weight 0.15, only affects the calm-wind
activity bonus). It has **zero direct effect on `population_potential`/Myggläge.** Concretely: given
identical 21 days of weather history, a fully built-up central-Stockholm cell (`urban_fraction≈1`)
and an adjacent semi-rural cell with the same weather history but `urban_fraction≈0` currently produce
population_potential differing *only* by whatever `forest`/`wetland`/`site_persistence` values happen
to differ between them — urban land cover itself contributes nothing. This is the single most direct
explanation, among everything audited here, for why "Stockholm and other urban/exposed environments
should often have substantially lower baseline mosquito abundance... under otherwise similar current
weather" currently fails: nothing in `population_potential` encodes "urban" as a *negative* habitat
signal at all, only as a weak downstream exposure discount that only matters after a population signal
already (incorrectly) exists.

### 4.6 — snowmelt has no geographic variation at all

`snowmelt_term = bell_curve(day_of_year, optimum=135, width=40) * (0.35 if freezing_recently else 1.0)`
— a pure function of calendar day (and a same-cell "has it been below 0°C in the last 24h" flag). On
any given day in spring, Kiruna (typical snow well into April/May) and Malmö (rarely meaningful snow
by March) get the *identical* snowmelt_term unless one of them happens to be currently freezing. There
is no accumulated-snow, no melt-date, and (per §1) no snow data fetched at all. This is the direct
cause of the "Norrland can have very high summer abundance, but the current temperature/season
treatment may unintentionally suppress it" risk flagged in the new spec — not because northern
latitude is explicitly penalized (it isn't, directly), but because the one term that's supposed to
represent snowmelt-driven emergence contributes the same modest, fixed bump everywhere, so a real
northern snowmelt-driven population boom has no mechanism to register at all beyond what temperature/
rainfall alone would already produce for any location.

## 5. Why the geography that *does* exist reads as "modest habitat correction"

Even the two unconditionally-geographic population terms are individually weak in practice:

- `wetland_term = clamp(wetland_fraction × 1.8, 0, 1)`, weight 0.13 → a cell needs `wetland_fraction`
  ≥ 0.56 just to *saturate* this term at 1.0; most of Sweden (per the README's own NMD/WorldCover
  caveats, most of Sweden's real mire terrain is tree-covered and reads as forest, not
  `wetland_fraction`) sits well under that, so in practice this term rarely contributes anywhere near
  its full 0.13 weight even at genuinely marshy sites.
- `forest_term = clamp(forest_fraction × 1.3, 0, 1)`, weight 0.07 → saturates at `forest_fraction`
  ≥ 0.77, which the *majority* of forested Sweden clears — meaning this term is close to *maxed out*
  almost everywhere forested, i.e. it can't discriminate "dense mosquito-favourable wet forest" from
  "dry pine heath" at all; both read as forest_fraction ≈ 0.8–0.95 and both score ≈ 0.07 regardless.
- `_site_persistence_factor`'s wetland/water terms (`0.4+0.6·wetland`, `0.5+0.5·water_density`) both
  have a **high floor** (0.4 and 0.5 respectively) — even `wetland_fraction=0` and
  `water_body_density=0` still yields a site_persistence multiplier around `0.4 × 0.5 × drainage ≈
  0.2 × drainage`, not zero. Combined with drainage's own floor (`max(0.15, ...)`), a completely dry,
  waterless, wetland-free cell still passes roughly 15–20% of whatever rain-based signal reaches it,
  while a maximally wet/wetland/water cell only reaches 3–5× that, not an order of magnitude more. The
  gate compresses the geographic *range* of its own multiplier far more than the spec's target of
  "areas around lakes/wetlands/poorly drained forest should often stand out" implies.

## 6. Summary of findings carried into this iteration

1. `population_potential`/Myggläge has at most 0.20 of its weight unconditionally geographic, 0.32
   more only as a *gate* on weather terms that itself compresses toward a shared floor — addressed by
   Phase 3 (`habitat_capacity`) and Phase 4 (multi-scale water).
2. `urban_fraction` has zero effect on population_potential — the single biggest lever for "Stockholm
   should read as lower baseline abundance than wet inland/forest" is currently unused where it
   matters — addressed by Phase 3 (urban suppression as a `habitat_capacity` input).
3. `elevation_m` and `daylight_hours` are computed from real data and then never read — addressed by
   Phase 3/7 (elevation → habitat_capacity/mountain suppression).
4. `water_body_density` is a bug, not a feature — it duplicates `water_fraction` exactly rather than
   representing a wider-scale water signal — addressed by Phase 4 (genuine multi-scale water/wetland
   features, replacing this field rather than patching it).
5. `water_fraction` itself is computed and then dropped before reaching `FeatureSet` — addressed by
   Phase 4.
6. No snow/snowmelt-timing data exists anywhere in the pipeline; the `snowmelt` term is calendar-only
   and geographically uniform — addressed by Phase 7.
7. `wetland_fraction` recurs across three population terms with no shared, once-computed "habitat"
   concept behind it, and forest/wetland saturate too easily to discriminate real habitat quality
   within "forested" or "wetland" Sweden — addressed by Phase 3.
8. `sweden_lakes.geojson` (47 real named lake polygons) and NMD's fine-grained wetland/forest subtypes
   exist on disk and are discarded before reaching the model — addressed by Phase 4.
9. No persistent population/pressure state exists — `population_potential` is recomputed independently
   from a 21-day rolling weather window at every hour/daypart, with no explicit adult-survival/decay
   model — addressed by Phase 6.
