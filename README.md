# Myggprognos — Mosquito Risk in Sweden

A public beta of an experimental, Swedish-first seven-day mosquito activity forecast covering the whole of
Sweden (mainland, Gotland, Öland): an interactive map, hourly detail for the next 48 hours, municipality
search, explainable risk factors with a plain-language "why" narrative, and a simple user-reporting system.
Built to be cheap to run — a static frontend, a scheduled Python pipeline, and a tiny serverless API, all on
free tiers.

**This is not a measurement of actual mosquito counts, and it is not a public-health disease-risk system.**
It's a transparent, rule-based estimate of how favourable conditions are for mosquitoes, built from open
weather and land-cover data. See [Limitations](#limitations) below.

## What it does

For any point in Sweden, at any hour over the next week, the app answers (in Swedish by default; see
[Localisation](#localisation)):

- How bad are mosquitoes likely to be? (**Myggrisk**, 0–100)
- How will that change over the next seven days, and through the day?
- What time of day will activity peak?
- Why is the risk high or low, in a real sentence — not just a number?
- How confident is the forecast?
- Are nearby users reporting similar conditions?

## What the score means

**Myggrisk** is a 0–100 score combining three components, each also shown individually:

| Component | Meaning |
|---|---|
| **Population potential** | How many mosquitoes are probably around, independent of the current hour's weather — driven mainly by `habitat_capacity` (static geography: wetland/water/forest habitat quality, see below) and `mosquito_pressure` (a persistent, decay-weighted accumulation of recent rain/snowmelt-driven emergence — see [Habitat capacity and mosquito pressure](#habitat-capacity-and-persistent-mosquito-pressure)). |
| **Biting activity** | How active mosquitoes are likely to be at the selected hour, given temperature, humidity, wind, and time of day. |
| **Exposure** | How likely a person is to encounter mosquitoes given the terrain, proximity to water, and their chosen activity. |

`risk = population_potential × biting_activity × exposure`, rescaled to 0–100.

| Score | Category (sv) |
|---|---|
| 0–19 | Mycket låg (Very low) |
| 20–39 | Låg (Low) |
| 40–59 | Måttlig (Moderate) |
| 60–79 | Hög (High) |
| 80–100 | Mycket hög (Very high) |

The map uses a smooth green → yellow-green → yellow → orange → red interpolation over the same 0–100 range
rather than hard colour bands, so nearby cells with similar scores don't jump between visually distinct
colours (see `frontend/src/lib/riskModel.ts::RISK_COLOR_STOPS`).

A **confidence** score (0–100, shown as Låg/Medel/Hög) reflects forecast horizon, weather data completeness,
static data quality, and agreement between the three components — see `forecast/src/confidence.py`.

### Three named products

The frontend switches the map between three named products (all published per cell/hour/day; see
[Generated output format](#generated-output-format)), not just the single "Myggrisk" combined score above:

| Product (sv) | Field | Meaning |
|---|---|---|
| **Myggläge** | `population_potential` | How favourable conditions have been for mosquitoes to be present at all, independent of the current hour's weather — built from recent rainfall/temperature/moisture/habitat, not wind or time of day. Uses its own category thresholds (`thresholds.abundance` in the manifest), not the risk bands above — see "What the score means" and `docs/model-audit-after.md`. |
| **Myggrisk idag** | `daily_peak_risk` | The day's *highest* expected nuisance risk, regardless of which hour the page happens to be loaded — the default product. |
| **Myggrisk just nu** | `current_risk` | The risk at whichever hour/daypart is currently selected — the same 0–100 scale and category bands as "Myggrisk idag", just evaluated at a specific moment instead of the day's peak. |

Two further layers (`biting_activity`, `confidence`) are available under "Fler inställningar"/the settings sheet for anyone who wants the raw activity component or the data-quality score directly, rather than as one of the three primary products above.

### Habitat capacity and persistent mosquito pressure

Following a geographic-model redesign (see `docs/geographic-model-audit-before.md`,
`docs/geographic-benchmark-after.md`, `docs/mosquito-ecology-evidence.md`), population potential
("Myggläge") is built from two explicitly separated concepts rather than one flat weighted sum of
weather terms:

- **`habitat_capacity`** (0–100, `forecast/src/static_features.py::compute_habitat_capacity`) — a
  slow-changing, weather-independent score for "how capable is this landscape of supporting large
  mosquito populations if weather is favourable", from multi-scale wetland/water fractions (500m/2km/
  5km), forest-water/wetland-water edge density, small-water density (discounting both deep lake
  interior and open marine coastline, since neither is real breeding habitat), a static
  slope/wetland/water-proximity floodplain-potential proxy, and urban/elevation suppression. Computed
  once per cell (like other static features), not recomputed per hour.
- **`mosquito_pressure`** (0–100, `forecast/src/feature_engineering.py`, "Persistent mosquito
  pressure" section) — a persistent, decay-weighted accumulation of daily rain- and snowmelt-driven
  emergence, gated by `habitat_capacity`, with a configurable adult-survival rate
  (`model.yaml mosquito_pressure.pressure_survival_daily`, default 0.90/day). Deterministically
  re-derived from the available weather-history window every run (no separate persisted "yesterday's
  pressure" state) — an established population in good habitat that stops raining for several days
  declines gradually, not instantly, and one warm rainy day in poor habitat doesn't spike it either.
  Snowmelt-driven emergence uses real snow-depth history where the weather provider exposes it (Open-
  Meteo), and a latitude-shifted seasonal-timing fallback where it doesn't (SMHI — see
  `docs/geographic-model-audit-before.md` and "Weather data source" below).

`population_potential` itself is a weighted combination of mostly `mosquito_pressure` and
`habitat_capacity`, plus modest `temperature`/`season` suitability terms — see
`forecast/src/model.py::compute_population_potential` and `model.yaml population_weights`. Both
`habitat_capacity` and `mosquito_pressure` are published per record for explainability (e.g. a future
"lots of mosquitoes here, but wind is keeping activity down right now" narrative — already partially
implemented, see `explanation.py::_abundance_vs_activity_clause`).

### Wind: forecast wind, effective (shelter-adjusted) wind, and the calm-evening/wind-drop correction

Biting activity's wind response has two layers (see `docs/wind-calm-investigation.md` for the full
investigation this came from):

1. **Base suppression** (unchanged from earlier versions): a smooth curve on the provider's own raw
   forecast wind — more wind means less biting activity, `model.yaml activity.wind_half_suppression_ms` /
   `wind_full_suppression_ms`.
2. **A targeted calm-evening / wind-drop correction** on top of that, gated by `wind_speed_effective_ms`
   (`forecast/src/feature_engineering.py::compute_effective_wind` — the forecast wind adjusted by a bounded,
   configurable multiplier from static terrain shelter: forest/urban cover reduce it, coastal exposure
   increases it) rather than the raw forecast value, plus 1h/3h wind history. This specifically addresses two
   real gaps: exposed meteorological wind isn't what a person in a sheltered spot actually feels, and a
   memoryless model can't distinguish "calm all day" from mosquitoes emerging right after a gust dies down.
   Both `forecast_wind_ms` and `effective_wind_ms` are published per record (never presented as measured
   local wind) — see `model.yaml wind_shelter:` / `wind_dynamics:` for the exact formula and configurable
   thresholds/caps.

### Explainability

Every forecast record exposes both a structured explanation (positive/negative factors with labels and
approximate contribution weights, used for the UI's +/- list) and a flat, spec-literal array of formatted
strings (`explanation_text`, e.g. `"Hög temperatur (+18)"`), plus a narrative `summary` sentence built from
the same underlying feature values, e.g.:

> Myggrisken är hög idag eftersom det har regnat mycket den senaste veckan (32 mm), temperaturen ligger runt
> 22 °C och vinden är svag.

All of this is generated deterministically from the same contribution values used to compute the score (see
`forecast/src/explanation.py`) — no external language model is involved, so the explanation is always
faithful to the actual calculation, not a plausible-sounding guess.

## Limitations

- **Not a measured mosquito count.** The model estimates favourable *conditions*, not actual mosquito
  presence or density.
- **Not a disease-risk tool.** It says nothing about mosquito-borne disease risk.
- **Static land-cover data is real, but land-cover classification only approximates mosquito habitat.**
  Forest/wetland/urban/water fraction and elevation come from real satellite/DEM sources (see
  [Static geographic data](#static-geographic-data)), not placeholders. ESA WorldCover's "herbaceous
  wetland" class requires *open, non-forested* wetland to register — a lot of Sweden's real mire/bog
  terrain (myrmark) is tree-covered and reads as forest, not wetland, in a plain WorldCover snapshot. Where
  it's available, NMD2023 (Naturvårdsverket's national land-cover product) overrides this with a proper
  forest/wetland split, but as of NMD2023 v2.1 its rollout is south-to-north and not yet complete: under 1%
  of southern Sweden is uncovered, but roughly 19% north of ~62°N and ~46% in the far-north mountains
  (fjällen/Norrbotten) still falls back to the plain WorldCover value. The highest wetland_fraction cells
  nationally do correctly cluster in Norrbotten's fjäll/mire region and known bog complexes like Store
  Mosse, but a province like Dalarna won't show elevated wetland *on average* just from this feature alone —
  real seasonal flooding/standing-water dynamics are captured separately, by the weather-derived features,
  not by this static snapshot.
- **Accuracy declines with forecast horizon** — day 7 is far less reliable than hour 1.
- **User reports may be biased** (self-selected reporters, uneven geographic coverage) and are only ever
  blended in as a small, capped adjustment on top of the model — see [User reports](#user-reports-1).
- **The rule-based model is a first version**, not a validated entomological model. Weights in
  `forecast/model.yaml` are reasonable priors, not fitted/calibrated coefficients.
- **"Effective wind" is a coarse static-terrain estimate, not measured local wind**, and the calm-evening/
  wind-drop correction's thresholds are reasoned defaults checked against nationwide score distribution
  shape, not fitted against labelled real-world nuisance observations — see
  `docs/wind-calm-investigation.md` for the full investigation, evidence, and stated limitations.

## Architecture

```
frontend/   React + TypeScript + Vite + MapLibre GL JS + Recharts (both lazy-loaded), deployed to Netlify (GitHub Pages kept as a legacy fallback, see deploy-pages.yml)
forecast/   Python 3.12 pipeline (weather → features → rule-based model → generated JSON), run by GitHub Actions every 6h
worker/     Cloudflare Worker + D1, a tiny API for user mosquito reports
data/       static (grid + boundary + real land-cover/elevation features), samples (fixtures), generated (pipeline output)
scripts/    one-off/maintenance CLIs: prepare_grid, download_static_gis_data, download_nmd_data, prepare_static_features, run_forecast
```

No persistent backend server: the frontend reads pre-computed, gzip-compressed JSON files published as
static assets, and the only dynamic API is the small Worker used for user reports. This keeps hosting cost
close to $0/month at full-Sweden traffic levels (Netlify's and GitHub Pages' free tiers both cover this;
Cloudflare Workers + D1 free tiers are generous; both weather sources are free and keyless).

### Data flow

1. `forecast.yml` runs the Python pipeline every 6 hours: fetch weather (SMHI, see "Weather data source"
   below) → compute features →
   score with the rule-based model → write compact gzip JSON under `data/generated/latest/` → commit to
   `main` (using the default `GITHUB_TOKEN`, so pushes always target whatever repo the workflow runs in --
   no hardcoded owner/repo).
2. Netlify (`netlify.toml`, base directory `frontend/`) auto-builds on every push to `main`. Its build
   command runs the normal `npm run build`, then bundles `data/generated/latest/` into `dist/data/latest`
   the same way `deploy-pages.yml` does for GitHub Pages -- `data/generated/latest/` lives outside
   `frontend/`, so without this step Netlify would only ever ship the small sample dataset committed at
   `frontend/public/data/latest/`. `deploy-pages.yml` also still runs on the same trigger as a legacy
   fallback publish target (see the note at the top of that workflow); it does not feed Netlify anything.
3. The frontend fetches `manifest.json`, then only the specific `daily/*.json.gz` / `hourly/*.json.gz` /
   `series/*.json.gz` files needed for the current view (never the whole dataset at once).
4. User reports go straight from the frontend to the Cloudflare Worker → D1, independent of the forecast
   pipeline. The frontend remains fully usable (map, forecast, charts) even if the Worker is unreachable.

### Generated output format

```
data/generated/latest/
  manifest.json          # generated_at, forecast window, file listing, model version, build_sha,
                          # activity multipliers, series_shard_count / series_files
  cells.json.gz          # static per-cell metadata (id, lat/lon, land-cover fractions)
  daily/YYYY-MM-DD.json.gz     # one file per forecast day, all cells, with dayparts + explanation + explanation_text
  hourly/YYYY-MM-DDTHH.json.gz # one file per hour for the first 48h, all cells
  series/<shard>.json.gz       # 128 shards, {cell_id: {daily: [...], hourly: [...]}} -- see below
  locations/index.json.gz      # municipality gazetteer for offline search fallback
```

Design choice: many small files rather than one large GeoJSON, so the frontend only downloads what the
current view needs. The location detail panel used to fetch all 7 daily + 49 hourly files (56 requests) just
to chart one cell's history — fine for a 5-cell sample grid, but at full-Sweden scale (~18k cells) those
files are large enough that this would mean 50-150MB downloaded per click. Instead, the pipeline additionally
writes small **sharded per-cell series files**: every cell is assigned one of 128 shards via a stable djb2
hash of its `cell_id` (`forecast/src/output.py::shard_for_cell_id`, ported to
`frontend/src/lib/sharding.ts::shardForCellId` — kept in sync, cross-checked in tests), and each shard file
holds that shard's ~140 cells' full daily+hourly series. The location panel fetches exactly one shard file
per selection instead of 56 files.

## Data sources

- **Weather** — [SMHI Open Data](https://opendata.smhi.se/) (default; CC BY 4.0) with
  [Open-Meteo](https://open-meteo.com/) kept as a fallback (CC-BY-4.0 attribution required, see their terms).
  Both sit behind a `WeatherProvider` protocol (`forecast/src/weather.py`) — see "Weather data source" below
  for why SMHI is the default and what's involved in falling back.
- **Place search** — local static gazetteer (`data/static/places.json`, ~300 Swedish municipalities compiled
  from [Wikidata](https://www.wikidata.org/) municipality/administrative-seat data, ODbL/CC0-style open data)
  plus live [Nominatim/OpenStreetMap](https://nominatim.org/) search, attributed in the UI, debounced, min 2
  characters, max 8 results. OSM data © OpenStreetMap contributors, ODbL.
- **Sweden boundary** — `data/static/sweden_boundary.geojson`, a Sweden `MultiPolygon` (mainland + islands,
  including Gotland and Öland) derived from Natural-Earth-based country boundary data
  ([datasets/geo-countries](https://github.com/datasets/geo-countries), public-domain-style attribution),
  used by `forecast/src/grid.py` to filter the generated grid to actual land, not just a bounding box.
- **Static geography (land cover)** — designed for Copernicus land cover, wetland/forest layers, hydrography,
  and a DEM (see [below](#static-geographic-data)); **not bundled** in this repo. A deterministic placeholder
  generator is used until real layers are configured. (The *boundary* used for land/ocean filtering is real;
  only per-cell land-cover attributes like forest/wetland fraction are placeholders.)
- **Basemap** — [CARTO Positron](https://github.com/CartoDB/basemap-styles) by default: a free, keyless, neutral
  light style (roads, place labels, muted land/water) meant for data overlays like the risk layer. (MapLibre's
  own `demotiles.maplibre.org` demo style was used earlier in development, but its "countries" layer fills
  every country with a distinct, fully-saturated flat colour for demo purposes — easily mistaken for graded
  risk data, and it visually drowned out the sample-mode risk circles. Positron has no such per-country
  fills.) Swap in a richer free-tier style via `VITE_MAP_STYLE_URL` (e.g. MapTiler, Stadia Maps) if desired.

### Full Sweden grid

`scripts/prepare_grid.py` generates a ~5km grid over `SWEDEN_BBOX`, filtered against the real boundary
polygon above and densified along every coastline/lakeshore to close gaps a fixed-phase lattice alone would
miss (`forecast/src/grid.py::generate_grid`), yielding ~23,000 land cells covering the mainland, Gotland and
Öland; ocean cells are excluded by the boundary test. `data/static/grid.json` is **not committed** to git —
it's regenerable from the boundary file + `config.py`, and cached between CI runs via `actions/cache` in
`forecast.yml` (see that workflow's "Cache grid" step). `data/static/cell_features.json` (see below) **is**
committed, since — unlike grid.json — there's nothing in CI to regenerate it *from*.

Regenerate the grid locally with:

```bash
python scripts/prepare_grid.py --resolution-km 5
```

### Static geographic data

Real GIS source data, all free/no-login:
  - [ESA WorldCover 10m 2021](https://esa-worldcover.org/) (Cloud-Optimized GeoTIFF on AWS S3) — land cover
    (forest, herbaceous wetland, built-up, permanent water bodies among its 11 classes) →
    `forest_fraction`, `wetland_fraction`, `urban_fraction`, `water_fraction`, `distance_to_water_km`.
    Covers all of Sweden; used everywhere as the baseline/fallback.
  - [NMD2023](https://geodata.naturvardsverket.se/nedladdning/marktacke/NMD2023/) (Naturvårdsverket's
    Nationella marktäckedata, single national GeoTIFF, CC0) — 10m land cover with 54 classes, crucially
    splitting forest into on-wetland vs on-firm-ground (by species) and open wetland into ~15 mire/non-mire
    types. Overrides the WorldCover-derived fraction wherever NMD has real coverage; see
    [Limitations](#limitations) for its current south-to-north rollout status. Delivered in SWEREF99 TM
    (EPSG:3006), reprojected per-cell on read.
  - [Copernicus DEM GLO-30](https://registry.opendata.aws/copernicus-dem/) — 30m elevation →
    `elevation_m`, `slope_deg`.
  - `coastal_exposure` is derived directly from the already-committed `sweden_boundary.geojson`, not a
    separate download.

To (re)compute `data/static/cell_features.json` after a `grid.json` change:

```bash
python scripts/download_static_gis_data.py   # ~4-5GB, only the tiles the current grid actually needs
python scripts/download_nmd_data.py          # optional, ~1.2GB download / ~10.85GB on disk
pip install rasterio geopandas pyproj        # optional extras, commented out in forecast/requirements.txt
python scripts/prepare_static_features.py --real
```

`data/static/worldcover/`, `data/static/dem/`, and `data/static/nmd/` (the downloaded source rasters) are
git-ignored — only the small derived `cell_features.json` (a few MB) is committed. Without `--real`, the
script (and the scheduled pipeline, only as a fallback if `cell_features.json` is ever missing outright)
uses `generate_placeholder_static_features()` — deterministic per-cell values seeded from the cell ID and
rough priors. Clearly a placeholder, not measured data; the committed file is real.

## Licence considerations

- Open-Meteo: free for non-commercial and most commercial use; attribute per their terms if you scale this up.
- OpenStreetMap/Nominatim: ODbL — attribution shown in the UI; respect their [usage policy](https://operations.osmfoundation.org/policies/nominatim/) if traffic grows (consider self-hosting Nominatim or a paid geocoder at scale).
- Copernicus data: free and open under the Copernicus licence; check specific dataset terms before redistribution.
- Wikidata (`data/static/places.json` municipality coordinates): CC0 — no attribution legally required, but
  see [Wikidata's data reuse guidance](https://www.wikidata.org/wiki/Wikidata:Licensing).
- `datasets/geo-countries` (`data/static/sweden_boundary.geojson`): public-domain-style, Natural-Earth-derived.
- CARTO Positron basemap: free, attribution ("© OpenStreetMap contributors © CARTO") shown automatically via
  MapLibre's attribution control, sourced from the style itself.
- This repository's own code has no other third-party data bundled.

## Local setup

Requires Python 3.12, Node 20, and (optionally) `make`.

```bash
# Everything (Python + frontend + worker deps)
make setup
make test
make sample-data      # generates data/generated/latest + copies into frontend/public/data/latest
make dev              # frontend at http://localhost:5173
```

Without `make`:

```bash
pip install -r forecast/requirements.txt
cd frontend && npm install && cd ..
cd worker && npm install && cd ..

cd forecast && pytest -v && cd ..
cd frontend && npm run typecheck && npm test && npm run build && cd ..
cd worker && npm run typecheck && npm test && cd ..

python scripts/run_forecast.py --sample --verbose
# copy data/generated/latest -> frontend/public/data/latest, then:
cd frontend && npm run dev
```

The repo ships with a small sample dataset already committed under `frontend/public/data/latest/` (5
representative cells: central Stockholm, a forested inland location, a wetland location, a coastal
location, and a northern Sweden location), so `npm run dev` works immediately even without running the
pipeline first.

## Sample mode vs. production mode

**Sample mode** (`--sample` flag): a 5-cell grid, synthetic (non-network) weather, placeholder static
features. Fast, deterministic, no external calls — used for local dev and CI.

**Production mode** (default): the full ~5km, ~18,000-cell Sweden grid (`scripts/prepare_grid.py`, filtered
against the real boundary polygon — see [Full Sweden grid](#full-sweden-grid)), placeholder or real static
features, live weather from SMHI by default (see "Weather data source" below for the fallback option). Run
via `python scripts/run_forecast.py` or the scheduled GitHub Action.

### Performance at full-Sweden scale

`forecast/src/feature_engineering.py::precompute_rolling_windows` computes numpy cumulative sums for
temperature/precipitation/soil-moisture once per cell, so the 49 hourly + 28 daypart `compute_features`
calls per cell become O(1) index lookups instead of re-parsing timestamps and re-scanning multi-week
windows on every call. A full pipeline run over all ~18,000 cells (synthetic weather, to isolate CPU cost
from network time) completes in **about 6 minutes** on this alone — CPU cost was never the bottleneck at
scale, network/API behaviour was (see below).

### Open-Meteo weather fetching (fallback provider): history caching, one combined request, connection reuse

This section documents `OpenMeteoProvider`'s design and history -- kept as the fallback provider (see
"Weather data source" below for why SMHI is now the default and what prompted the switch). `history_cache.py`
itself is provider-agnostic and used by both.

Three real production incidents shaped how `forecast/src/weather.py::OpenMeteoProvider` and
`forecast/src/history_cache.py` fetch weather, roughly in the order they were found:

1. **Refetching a full 21-day history window on every single run was the root problem.** The model genuinely
   needs `HISTORY_DAYS_BACK = 21` days of past weather (`forecast/src/model.py`'s `standing_water` term --
   10% weight on population potential -- is driven by 21-day accumulated rainfall and "days since meaningful
   rain"), but a given *past* hour's observed weather never changes once it's in the past, unlike the
   forward-looking forecast, which must always be refetched fresh. Re-requesting the same ~20 days of already-
   known history every 6 hours was pure waste and the single biggest driver of both runtime and rate-limiting.
   `history_cache.py` now persists a rolling 21-day-per-cell history cache (`data/generated/weather_history_cache.json.gz`,
   committed like `data/generated/latest`, but deliberately *not* inside it so it never ships to the public
   frontend build). Each run fetches only `INCREMENTAL_PAST_DAYS = 2` days (a small gap-filling window, plus
   safety margin) if the cache is warm (updated within `CACHE_FRESH_THRESHOLD_HOURS = 48`), or the full 21-day
   window if the cache is missing or stale -- the same code path handles both the very first "backfill" run and
   any future recovery from a lapse, with no special-cased bootstrap logic. This cuts the per-request hourly
   payload from 672 hours (21 history + 7 forecast) down to roughly 216 hours on a routine run.
2. **History and forecast used to be two separate API calls per batch** (one to Open-Meteo's archive API, one
   to its forecast API). `OpenMeteoProvider.fetch_combined()` now makes one request per batch using the
   forecast endpoint's `past_days` parameter, which natively returns recent history immediately followed by
   the forward forecast as a single continuous, sorted, non-overlapping series -- no separate archive call, no
   client-side merge/de-dup step. Combined with (1), routine runs need roughly 373 requests total instead of
   the ~1,500+ a naive "21-day history + 7-day forecast, two calls, every run" design would need.
3. **A fresh TCP+TLS connection was being opened and closed for every single batch request.** At ~370
   sequential batches that's ~370 handshakes instead of one persistent connection reused throughout, and it
   turned out to be a major source of `"_ssl.c:993: The handshake operation timed out"` failures in production
   (one live run saw 136/373 batches need at least one retry). `fetch_combined()` now opens one `httpx.Client`
   for the whole call and reuses it for every batch.

**Known open question, not yet fully resolved:** an earlier live full-grid run still got HTTP 429 (rate
limited) by Open-Meteo on a large fraction of batches even after connection reuse -- proactive pacing
(`WEATHER_REQUEST_PACING_S`, default 2s, a fixed delay before every real request) and rate-limit-specific
backoff (`WEATHER_RATE_LIMIT_BACKOFF_S`, default 30s, linearly scaling instead of the generic exponential
backoff used for other transient errors) both help individual batches recover, but whether Open-Meteo's real
limit is closer to "per-request complexity" (which the history-cache/merge changes above directly reduce) or
"total requests per IP per hour/day" (which they don't) is still an open question -- local testing to
disambiguate this got confounded by the local test machine's own IP having made many requests earlier the same
day. The history-cache change is a real win regardless (roughly 70% less data fetched per routine run, and
correspondingly less total time spent exposed to any time-windowed quota), but if 429s are still frequent on a
live run after this change, the next lever to pull is `WEATHER_REQUEST_PACING_S`, not batch payload size.

GitHub-hosted runners also have a **hard 6-hour job execution ceiling that `timeout-minutes` cannot exceed**
(confirmed empirically: setting it to 480 didn't help, the job was still killed at exactly 360 minutes) --
`forecast.yml`'s `timeout-minutes: 360` is set to the platform max explicitly, as documentation that this
isn't an oversight, not as a working mitigation. The real mitigation is keeping the pipeline reliably well
under that ceiling via the fetch-volume reductions above.

## GitHub Actions setup

Three workflows in `.github/workflows/`:

- **`test.yml`** — pytest, frontend typecheck/test/build, worker typecheck/test. Runs on PRs and pushes to `main`.
- **`forecast.yml`** — runs the pipeline every 6 hours (`workflow_dispatch` also available, with a `sample`
  input for testing). Caches grid/static-feature generation, commits `data/generated/latest` only if it
  changed, uploads the full run as a 90-day workflow artifact, and triggers `deploy-pages.yml`. Uses
  `concurrency: cancel-in-progress: false` so overlapping runs queue instead of racing. **If the pipeline's
  sanity checks fail** (see `forecast/src/output.py`), the job fails before anything is committed — the
  previously published forecast stays live.
- **`deploy-pages.yml`** — legacy/fallback (see the note at the top of the file). Builds the frontend,
  bundles the latest forecast data (falling back to the committed sample data if no full-grid forecast
  exists yet), and deploys to GitHub Pages via `actions/deploy-pages`. Netlify is the production deploy
  target and does not depend on this workflow.

To enable Pages as a fallback: in repo Settings → Pages, set source to "GitHub Actions". No secrets are
required for the default (keyless) Open-Meteo + demo-basemap configuration.

### Netlify setup (production)

Site settings (Netlify UI, or equivalently `netlify.toml` at the repo root, which takes precedence once
present):

- **Branch:** `main`
- **Base directory:** `frontend`
- **Build command:** see `netlify.toml` -- runs `npm run build`, then bundles `data/generated/latest/`
  into `dist/data/latest` (same data `deploy-pages.yml` bundles for Pages)
- **Publish directory:** `dist` (resolves to `frontend/dist`)

No new secrets are required -- the forecast pipeline pushes to `main` with the built-in `GITHUB_TOKEN`,
and Netlify's own "auto-deploy on push to `main`" setting picks that commit up without any build hook or
API token. Netlify auto-detects `netlify.toml`; no manual dashboard change is needed unless the site's
existing UI-configured base/publish directories differ from the values above.

**Custom domain:** `https://myggprognos.se` is configured in Netlify as the site's custom domain (apex),
with `https://www.myggprognos.se` set to redirect to it. The underlying `https://myggprognos.netlify.app`
subdomain still resolves and is kept as a fallback/testing origin in the Worker's `ALLOWED_ORIGINS` (see
"Cloudflare setup" below).

### Historical forecast archive & automatic cleanup

Chosen MVP strategy (see spec section 18): `data/generated/latest` is committed and **overwritten in place**
every run — it is never versioned by date in git, so the working tree never grows unbounded and no manual
cleanup step is needed. The **full output of every run is separately retained as a 90-day GitHub Actions
artifact** via `actions/upload-artifact`, which GitHub itself expires automatically (also no manual step).
The pipeline's on-disk weather cache (`data/cache/weather`, see `forecast/src/weather.py::DiskCache`) only
ever exists within a single ephemeral CI job — it isn't persisted or restored between runs, so it can't grow
unbounded either. Net effect: daily/6-hourly forecast publishing, and all of its cleanup, is fully automatic
end-to-end with zero manual steps. If longer retention or query-ability is needed later, the natural upgrade
is to also write evaluation-ready summaries into the Worker's D1 database.

## Cloudflare setup

```bash
cd worker
npm install
npx wrangler login
npx wrangler d1 create mosquito-reports          # copy the returned database_id into wrangler.toml
npm run db:migrate:local                          # local dev database
npm run db:migrate:remote                          # production database
npx wrangler secret put REPORT_HASH_SALT           # random string, used only to hash IPs for rate limiting
npm run deploy
```

Then set `ALLOWED_ORIGINS` in `wrangler.toml` to your deployed frontend origin(s), and set
`VITE_REPORT_API_URL` (frontend env, see `.env.example`) to the deployed Worker URL
(`https://mosquito-risk-reports.<subdomain>.workers.dev`).

### D1 migrations

Schema lives in `worker/schema.sql` (source of truth for a fresh local setup) and
`worker/migrations/0001_init.sql` (applied via `wrangler d1 migrations apply`). Add new numbered migration
files for future schema changes rather than editing the existing one.

### API

```
GET  /api/health                                  liveness + DB check
POST /api/reports                                  submit a report (validated, rate-limited)
GET  /api/reports?bbox=minLon,minLat,maxLon,maxLat&since=ISO8601   recent reports in an area
GET  /api/reports/summary?cell_id=SE_...&since_hours=12            aggregate + recommended report weight
```

## User reports

**"How bad are mosquitoes here right now?"** — None / A few / Noticeable / Many / Unbearable, plus optional
terrain, activity, repellent-used, and a short comment. The app stores only a rounded (~1km) location and
forecast cell — never exact GPS, names, or emails — and rejects comments that look like they contain an
email or phone number (checked client- and server-side).

Reports never dominate the forecast: the Worker returns a `recommended_report_weight` capped by sample size
(0 below 3 reports, up to 0.3 above 15 — see `forecast/model.yaml` → `report_adjustment`, mirrored in
`worker/src/reports.ts` and `frontend/src/lib/reportAdjustment.ts`). The UI shows both the raw model
estimate and the report-adjusted figure when an adjustment applies.

Every report also stores the forecast context the client had on screen at submission time — forecast wind,
effective (shelter-adjusted) wind, temperature, humidity, population potential, biting activity, model
version, and target timestamp (`worker/schema.sql`, migration `0002_wind_diagnostics.sql`) — so a future
false-negative analysis (e.g. "did calm-wind reports actually coincide with what the model predicted?") can
be done directly against stored reports instead of needing forecast archives that may no longer be retained.
See `docs/wind-calm-investigation.md` for the investigation this was added for.

## Model configuration

All tunable weights/thresholds live in `forecast/model.yaml` (development base temperature, population/
activity/exposure weights — including `standing_water`, the decay-weighted rainfall/drainage/wetland term —
activity multipliers, confidence weights, report-adjustment tiers) — nothing is a hard-coded magic number in
the pipeline code. `forecast/src/model.py` implements the actual scoring using bounded `clamp` /
`scale_sigmoid` / `bell_curve` transforms rather than raw linear sums, to avoid false precision and keep
every sub-score naturally bounded to [0, 1] before the final 0–100 rescale.

## Localisation

The UI is Swedish by default with a proper i18n structure so other locales can be added later without
touching component code: `frontend/src/i18n/{sv,en,types,index}.tsx` — a flat, dot-path string dictionary
(`sv.ts`, fully populated; `en.ts`, a partial proof-of-structure) behind a `LocaleProvider` + `useI18n()`
hook (`const { t } = useI18n(); t('legend.title')`), persisted to `localStorage`. Deliberately hand-rolled
rather than a library like `react-i18next`: the string set is modest (~100-150 keys, no plurals/namespaces
needed) and this keeps the bundle small, in line with the performance goals below.

Forecast *content* — risk category labels ("Hög", "Måttlig", ...), confidence labels, and the explanation
text/narrative — is generated directly in Swedish by the Python pipeline (`forecast/src/config.py`,
`explanation.py`) and displayed as-is; it deliberately bypasses the frontend dictionary, since it's data, not
UI chrome. Adding true multi-language *forecast* text later would mean having the pipeline emit parallel
per-locale explanation arrays — a natural follow-up, not implemented here.

## Performance

- **Lazy-loaded heavy libraries**: `maplibre-gl` (map) and `recharts` (charts) are dynamically imported via
  `React.lazy` + `Suspense` (`App.tsx`, `LocationPanel.tsx`) rather than bundled into the initial chunk, so
  the app shell renders and becomes interactive before either library downloads. Confirmed via
  `npm run build`: the main bundle is ~37KB (12.9KB gzipped); `maplibre-gl` (~800KB) and `recharts` (~535KB)
  ship as separate chunks fetched only when the map/charts are actually about to render.
- **Skeleton loading states**: the map area and location panel show pulsing skeleton placeholders (not a
  blank screen or bare "Loading…" text) while the manifest/forecast/chart data loads — see `.skeleton*`
  classes in `frontend/src/styles/global.css` and `PanelSkeleton`/`MapSkeleton` in the respective components.
- **Mobile**: touch targets are ≥44px, the control bar scrolls horizontally on narrow viewports instead of
  wrapping awkwardly, and the legend is a native `<details>` disclosure so it can be collapsed on small
  screens.

## Weather data source: SMHI (default), Open-Meteo (fallback)

**SMHI Open Data is the default weather provider** as of this migration. Open-Meteo (the original source)
hit a hard scaling wall at full-Sweden scale: its per-cell-batch request design means total request count
scales with grid size (~373 batches for our ~18.6k cells), and a live full-history backfill got rate-limited
into the ground — 705 HTTP 429s in one 6-hour run, with throughput collapsing to near-zero after the first
~30 minutes, and a subsequent run went a full 6 hours with **zero** net progress. [SMHI Open
Data](https://opendata.smhi.se/) (the Swedish met service's own free, open API), implemented in
`forecast/src/smhi_weather.py`, structurally avoids this: a live full-grid run completed in ~16 minutes with
zero rate-limiting.

**Why it's structurally different (and better) for our request-volume problem**: SMHI's MultiPoint endpoint
returns one value per grid point across its *entire* ~1,014,481-point domain (all of Scandinavia and
beyond) for a single `(time, parameter)` pair, in one request — confirmed live. So instead of looping over
batches of our own cells, `SMHIProvider` loops over the `(time, parameter)` pairs it needs (one whole-domain
fetch each) and picks out our cells' values via a precomputed nearest-neighbor index
(`scripts/prepare_smhi_grid_index.py`, run once, cached to `data/static/smhi_grid_index.json`, rebuilt
automatically in CI whenever `data/static/grid.json` changes). Total request count is therefore
**independent of grid size**.

Getting this working live surfaced (and fixed) two serious bugs beyond the initial design, worth knowing
about since they're easy to reintroduce if this code is touched again:
- **Redundant whole-domain fetching**: `pipeline.py`'s 1000-cell checkpoint chunking (designed for
  Open-Meteo's very different scaling, see below) made SMHI's provider repeat its whole-domain fetch ~19x
  for the full grid. `run_forecast.py` passes a large `cache_checkpoint_chunk_cells` for the SMHI path so
  the whole grid is fetched in one pass.
- **An OOM bug**: the first working version collected all ~600 whole-domain arrays (~1M elements each) into
  memory before extracting any cell's value from them — tens of GB of boxed Python floats, which SIGTERM-
  killed a live run. Fixed by extracting each cell's value immediately after each fetch and discarding the
  whole-domain array right away, so only one such array is ever in memory at a time.

**Two permanent, known limitations versus Open-Meteo** (not bugs — structural, confirmed against the live
API):
- **No soil moisture parameter** on either SMHI product (forecast `snow1g` or analysis `mesan2g`). Left as
  `None` throughout, same fallback path `HourlyWeather` already supports for missing fields.
- **No bulk historical backfill.** SMHI's MESAN analysis API only exposes a rolling ~24h window
  (`times.json` never lists more than a day of history) — there's no "give me the last 21 days" call. Cells
  that already had a full 21-day history from Open-Meteo before the migration keep it (the production
  history cache carried over unchanged); cells that didn't will accumulate the full window gradually over
  ~3 weeks of daily runs via the same self-healing bootstrap `history_cache.py` already implements for a
  cold cache, rather than getting it in one backfill.

SMHI's own forecast time steps also coarsen with lead time (1h out to 48h, 2h to 72h, 6h to 132h, 12h
beyond) rather than staying hourly. Since `feature_engineering.py`'s rolling-window precompute assumes a
uniformly hourly series (each array index = 1 hour), `SMHIProvider` forward-fills onto a synthetic hourly
grid before returning, keeping its output contract identical to `OpenMeteoProvider`'s.

**Falling back to Open-Meteo**: `python scripts/run_forecast.py --provider open-meteo` (both providers write
to the same `data/generated/latest` / `weather_history_cache.json.gz` production paths — only one is ever
"the" production source at a time). `OpenMeteoProvider` and its persistent history-cache/checkpointing
machinery (see `forecast.yml`'s 360-minute timeout and periodic background cache push) are kept in place
specifically so this fallback stays viable if SMHI's API ever becomes unavailable, without needing to
resurrect any of this.

## Testing

- `cd forecast && pytest -v` — unit tests for every scoring sub-function (incl. the standing-water term),
  feature engineering (incl. the rolling-window fast path against the original per-call path), confidence,
  explanation generation (structured factors + flat `explanation_text` + narrative summary), weather provider
  (mocked HTTP, retries/backoff, validation), grid generation, output writing/sanity checks/series sharding,
  and end-to-end pipeline + five-location fixture/snapshot tests.
- `cd frontend && npm test` — Vitest: risk-recombination math (0–100 scale), URL state round-tripping,
  report-adjustment tiering.
- `cd worker && npm test` — Vitest: input validation (0–100 `forecast_score` bound), bbox parsing,
  report-weight tiering, IP hashing.

## Troubleshooting

- **`npm run dev` shows "Could not load forecast data"** — make sure `frontend/public/data/latest/`
  exists (`make sample-data` or `python scripts/run_forecast.py --sample` then copy the output there).
- **Pipeline fails sanity checks** — check the Action logs; common causes are a large cell-count drop
  (partial weather fetch failure) or an out-of-range score, both of which intentionally abort *before*
  publishing so the live site keeps the last good forecast.
- **Map basemap looks very plain** — that's the free, keyless CARTO Positron style, chosen deliberately as a
  neutral canvas for the risk overlay; set `VITE_MAP_STYLE_URL` to a richer style if desired.
- **Map shows only ~5 scattered dots, or a banner says "showing example data"** — the site is serving the
  bundled 5-cell sample dataset, not the full ~18k-cell production grid. This happens if `forecast.yml`
  hasn't run yet (or its last run failed) — trigger it manually from the Actions tab, or wait for its next
  6-hourly run.
- **Reporting form says "offline demo mode"** — `VITE_REPORT_API_URL` isn't set; the rest of the app still
  works normally.
- **D1 migration errors locally** — delete `worker/.wrangler/state` and re-run
  `npm run db:migrate:local` to reset the local database.

## Security limitations (read before scaling up)

- Cell-ID validation in the Worker is format + Sweden-bounding-box only, not exact grid-membership (the
  full grid isn't bundled into the Worker to keep it small) — see `worker/src/validation.ts`.
- Rate limiting is a simple per-hashed-IP window in D1 (30s between reports, 30/day), not a full
  anti-abuse system — sufficient for MVP traffic, not for adversarial abuse at scale.
- No authentication anywhere by design (per spec) — reports are anonymous and unauthenticated.

## Swedish SEO

`frontend/index.html` ships Swedish `<title>`/meta description, OpenGraph (`og:*`, `og:locale=sv_SE`),
Twitter card meta, `<html lang="sv">`, and a canonical link; `frontend/public/robots.txt` and `sitemap.xml`
point at the same domain. **The canonical/OG/sitemap URLs use the real production domain,
`https://myggprognos.se/`** (the apex domain; `https://www.myggprognos.se` redirects to it, confirmed live
2026-08-25) — update `index.html`, `robots.txt`, and `sitemap.xml` if the production domain ever changes
again. No `og:image` is set yet (would need a real 1200×630 PNG under `frontend/public/`); see the
commented-out tag in `index.html` and [Future improvements](#future-improvements) below.

## Future improvements

- **Complete the NMD2023 rollout coverage** — the NMD override (see [Static geographic data](#static-geographic-data))
  already fixes WorldCover's tree-covered-wetland blind spot wherever it has data, but Naturvårdsverket's
  production is still rolling out north of ~62°N (see [Limitations](#limitations)). Re-running
  `scripts/download_nmd_data.py` + `prepare_static_features.py --real` periodically will pick up more
  coverage for free as new NMD versions are published, with no code changes needed.
- **Bilingual UI completion** — `frontend/src/i18n/en.ts` currently covers only a representative subset of
  keys as a proof of the locale structure; filling it in fully (plus a visible language switcher in the UI)
  would make English a real second locale rather than a partial fallback.
- **Per-locale forecast explanations** — the pipeline currently generates Swedish-only explanation text; a
  future version could emit parallel per-locale explanation arrays for true multi-language forecast content.
- **A real OpenGraph share image** and a non-emoji favicon/app icon set (192/512px PNGs, `apple-touch-icon`).
- **Disease-risk-adjacent caveats** — if this project is ever extended toward anything disease-relevant, that
  would need a fundamentally different validation/accuracy bar than this rule-based conditions model
  provides; see [Limitations](#limitations).
- **Evaluation against real observations** — the 90-day forecast-artifact retention (see
  [Historical forecast archive](#historical-forecast-archive--automatic-cleanup)) enables short-term
  forecast-vs-actual comparison; a longer-term evaluation pipeline (e.g. against citizen-science mosquito
  trap data) would meaningfully validate or recalibrate `model.yaml`'s weights.
