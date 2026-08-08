# Mosquito ecology evidence vs. modelling assumptions

Companion to `docs/geographic-model-audit-before.md` and `docs/geographic-benchmark-after.md`. This
document does two things for every mechanism the geographic-model redesign introduces or changes:
states what the mechanism is, and separates **literature-supported ecology** from **our modelling
assumption/simplification**. No real Swedish mosquito-count ground truth was used anywhere in this
project — nothing here should be read as validated against observed abundance. This is a sanity-check
against credible published ecology, not a calibration.

## 1. Floodwater mosquitoes (Aedes spp.)

**Literature-supported**: Many of Sweden's most numerous nuisance mosquitoes (*Aedes vexans*, *Aedes
sticticus*, and others in the "floodwater Aedes" group) lay drought-resistant eggs in floodplain soil
that hatch en masse when the site is inundated — by river flooding, snowmelt, or heavy rain — producing
large, synchronized adult emergences roughly 1–2 weeks after inundation, given sufficient warmth. This
is textbook Aedes/floodwater-mosquito biology (e.g. Becker et al., *Mosquitoes and Their Control*, 2nd
ed., 2010, covers floodwater Aedes development timing in detail) and is exactly why Sweden's Lower
Dalälven floodplain (Nedre Dalälven) is a well-known, often-cited severe-nuisance mosquito area,
studied specifically for this reason (Naturvårdsverket and Lower Dalälven-area municipalities have
funded biological *Bti* control programs targeting floodwater Aedes there for years, an operational
fact, not just an assumption).

**Our modelling assumption**: `feature_engineering.py`'s daily rain→degree-day emergence series and
`static_features.py`'s `floodplain_potential` (slope + wetland + water-proximity proxy) are a coarse,
deterministic stand-in for this real dynamic — no actual river discharge, water-level, or inundation-
extent data is used (per the new spec's "do not introduce a complicated external dependency unless it
provides meaningful value"). The model cannot distinguish an actual flood event from an equivalently
large stationary rainfall total; it treats "lots of rain over a poorly-drained, wetland-adjacent
landscape" as a proxy for flood-like inundation. This is a real, stated approximation, not a validated
flood model.

## 2. Snowmelt mosquitoes (spring Aedes)

**Literature-supported**: A second, distinct group of temperate/boreal Aedes species overwinters as eggs
that specifically require snowmelt/spring flooding of temporary pools to hatch (the "spring Aedes" or
"snowmelt-pool" guild), well documented in Nordic and North American boreal mosquito ecology (e.g.
Nordic vector-ecology literature on *Aedes communis*-group species; the general mechanism — snow-fed
temporary pools in poorly-drained forest/wetland terrain producing a large early/mid-summer emergence —
is standard boreal-zone mosquito ecology, not specific to this project). This is the literature basis
for the new spec's expectation that northern Sweden can have high summer abundance despite lower average
temperatures: what matters more than mean temperature is whether melt-fed pools formed at all and
whether enough warmth has accumulated since.

**Our modelling assumption**: `_snowmelt_daily_series` (feature_engineering.py) uses real Open-Meteo
`snow_depth` history when available (a genuine day-over-day snow decline, gated by accumulated degree-
days since) — this is a direct, defensible operationalization of the real mechanism. **The production
default weather provider (SMHI) does not expose a snow-depth parameter at all** (see README "Weather
data source" and `docs/geographic-model-audit-before.md` §1), so in current production this falls back
to `_fallback_snowmelt_day_signal`: a bell curve over day-of-year, centered on an assumed melt date that
shifts later with latitude (`FALLBACK_MELT_BASE_DAY` + `FALLBACK_MELT_LATITUDE_SHIFT_DAYS_PER_DEGREE`).
The **latitude-dependent melt-date shift itself** is literature-consistent (Swedish/Nordic climatological
records consistently show later mean snow-disappearance dates moving north and to higher elevation —
this is standard SMHI climatology, not a project-specific claim), but the specific numeric shift
(3 days per degree latitude) and window width (25 days) are round, defensible estimates, not fitted to
any specific observational melt-date dataset. **This is explicitly NOT a "Norrland bonus"**: the shift
only changes *when* the fallback signal peaks, not *how high* it can go, and the signal is still
multiplied by real per-cell `habitat_capacity` and combined with the real rain-driven series before
becoming pressure — a warm, dry, low-habitat northern cell gets no benefit from this term alone.

## 3. Wetland/forest mosquito abundance and forest/water interfaces

**Literature-supported**: The general principle that mosquito larval habitat concentrates at
vegetated, sheltered water margins (marsh/mire edges, forest pools, ditches) rather than in open,
wave-exposed water is a foundational finding across mosquito ecology broadly, not a Sweden-specific
claim (e.g. Becker et al. 2010, chapters on *Culex*/*Anopheles*/*Aedes* larval habitat selection;
also consistent with Sweden's own Nedre Dalälven Bti-control program targeting specific flooded
forest/meadow sites, not the Dalälven river channel itself). Sheltered, non-wave-exposed water with
emergent vegetation offers protection from fish/invertebrate predation and wind-driven mixing that
open water lacks — both are classic explanations in the literature for why marsh margins outproduce
open lake interiors.

**Our modelling assumption**: `static_features.py`'s `forest_water_edge_density`/
`wetland_water_edge_density`/`shoreline_density` (pixel-adjacency proxies from 10m land-cover
classification) and `small_water_density` (water not attributable to a named major lake interior) are
a raster-only operationalization of "vegetated margin vs. open water" — there is no actual vegetation-
type-at-the-shoreline classification, water depth, or predator-community data. The coastal/marine
correction (`freshwater_confidence` in `compute_habitat_capacity`) is a documented, partial fix for a
real problem found empirically (open Baltic coastline was initially scoring as high "small water"
habitat purely because it isn't one of the 47 named lakes) — but Sweden's real archipelago also
contains genuine, well-documented brackish shallow-lagoon habitat ("flador"/"glon" in Swedish coastal
ecology terminology — sheltered, semi-enclosed rocky-coast lagoons that ARE known Aedes breeding sites,
distinct from open exposed sea) that this raster-only signal cannot separate from open wave-exposed
coast. The current correction (halving water-adjacency credit in proportion to `coastal_exposure`)
likely under-credits real flador habitat in exchange for correctly suppressing open sea — a stated,
unresolved trade-off, not a validated fix.

## 4. Adult mosquito persistence/survival

**Literature-supported**: Published field estimates of daily apparent survival probability for
temperate *Culex* and *Aedes* adults commonly fall in roughly the 0.80–0.95 per-day range depending on
species, temperature, and humidity (a wide range is normal in the mosquito-ecology literature — daily
survival is one of the most-studied but most-variable parameters in vector population models, since it
depends heavily on local microclimate and predation pressure, not a single fixed constant). A daily
survival of ~0.90 implies a mean realized adult lifespan on the order of 1–1.5 weeks under field
conditions (shorter than laboratory-maximum lifespan estimates, consistent with real-world
predation/desiccation losses on top of physiological ageing).

**Our modelling assumption**: `PRESSURE_SURVIVAL_DAILY_DEFAULT = 0.90` (`model.yaml
mosquito_pressure.pressure_survival_daily`) was chosen as a defensible round mid-point of that
published range, not fitted against any Swedish-specific survival study. `docs/geographic-benchmark-
after.md` reports the decay behaviour this produces (a "wet/warm period → dry spell" persistence
example) at 0.90, and what changes at 0.85/0.93 — see that document for the sensitivity check. The
model applies a SINGLE fixed survival rate for the whole lookback window and does not vary it by
temperature (real survival is known to be temperature- and humidity-dependent, generally higher in
cooler/humid conditions and lower in hot/dry conditions) — a stated simplification, kept for
transparency/determinism rather than adding another weather-dependent sub-model.

## 5. Wind: activity vs. abundance

**Literature-supported**: Wind is very well established in the vector-ecology literature as suppressing
mosquito flight/host-seeking *activity* at fairly modest speeds (commonly cited thresholds around
3–5 m/s for substantial reduction in several *Aedes*/*Culex* field and wind-tunnel studies), without
implying anything about the underlying adult population size — a windy evening does not kill or remove
the resting/sheltering adult population, it just suppresses their flight behaviour until conditions
calm. This is the literature basis for `docs/wind-calm-investigation.md`'s calm-evening/wind-drop
correction, and for this iteration's explicit separation of `biting_activity` (wind-sensitive) from
`mosquito_pressure`/Myggläge (wind-independent, see Phase 8/§8 of `docs/geographic-model-audit-
before.md`).

**Our modelling assumption**: the specific wind-suppression curve shape/thresholds
(`activity.wind_half_suppression_ms`/`wind_full_suppression_ms` in `model.yaml`) are reasoned defaults
checked against nationwide score-distribution shape, not fitted against labelled Swedish field
observations — this is unchanged from `docs/wind-calm-investigation.md` and not re-validated here.

## 6. What remains genuinely unvalidated

- No real Swedish (or Nordic) mosquito trap-count time series was used to fit or check any weight,
  threshold, or survival rate in this model, at any point in this project's history including this
  iteration.
- `habitat_capacity`'s relative term weights (§ `static_features.py::HABITAT_CAPACITY_WEIGHTS`) were
  calibrated by checking the resulting spread/ranking against the 55-location benchmark's plausibility
  (does wetland/wet-forest outrank urban/farmland/mountain, in the expected direction and by a
  meaningful margin), not against any independent habitat-quality dataset.
- The floodplain/snowmelt/small-water proxies are all raster/DEM-only approximations of processes
  (real flooding, real snowmelt timing, real vegetated-margin extent) that in principle have better
  free data sources (e.g. SMHI hydrological forecasts, national wetland inventories with vegetation
  detail) not integrated here, per the explicit "avoid complicated external dependencies" constraint.
