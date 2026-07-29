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
| **Population potential** | How favourable recent weeks' weather has been for mosquito development (warmth, rainfall, moisture, standing water, habitat). |
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

### Population potential factors

Population potential now combines: recent and cumulative rainfall (1/3/7/14/21-day sums), average and
current temperature, humidity, soil moisture (with a transparent rainfall/temperature-derived fallback where
direct measurements aren't available), wind, spring snowmelt, forest and wetland proximity, lake/water-body
density, and **standing-water persistence** — a decay-weighted combination of recent rainfall, terrain
drainage (slope), and nearby wetlands/lakes estimating how long rain-fed breeding pools are likely to last
(see `forecast/src/feature_engineering.py::_standing_water_persistence`).

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
- **Static data is placeholder-quality in this MVP.** Land cover, wetland/forest fraction, and water
  proximity are deterministic *placeholders* (see [Static geographic data](#static-geographic-data)) unless
  you plug in real GIS layers. The Sweden land/ocean **boundary** used to shape the grid is real (see below)
  — only the per-cell land-cover attributes are placeholders.
- **Accuracy declines with forecast horizon** — day 7 is far less reliable than hour 1.
- **User reports may be biased** (self-selected reporters, uneven geographic coverage) and are only ever
  blended in as a small, capped adjustment on top of the model — see [User reports](#user-reports-1).
- **The rule-based model is a first version**, not a validated entomological model. Weights in
  `forecast/model.yaml` are reasonable priors, not fitted/calibrated coefficients.

## Architecture

```
frontend/   React + TypeScript + Vite + MapLibre GL JS + Recharts (both lazy-loaded), deployed to GitHub Pages
forecast/   Python 3.12 pipeline (weather → features → rule-based model → generated JSON), run by GitHub Actions every 6h
worker/     Cloudflare Worker + D1, a tiny API for user mosquito reports
data/       static (grid + boundary + land-cover placeholders), samples (fixtures), generated (pipeline output)
scripts/    one-off/maintenance CLIs: prepare_grid, prepare_static_features, run_forecast
```

No persistent backend server: the frontend reads pre-computed, gzip-compressed JSON files published as
static assets, and the only dynamic API is the small Worker used for user reports. This keeps hosting cost
close to $0/month at full-Sweden traffic levels (GitHub Pages is free; Cloudflare Workers + D1 free tiers are
generous; Open-Meteo is free and keyless).

### Data flow

1. `forecast.yml` runs the Python pipeline every 6 hours: fetch weather (Open-Meteo) → compute features →
   score with the rule-based model → write compact gzip JSON under `data/generated/latest/` → commit.
2. `deploy-pages.yml` builds the frontend and bundles `data/generated/latest/` alongside it, then deploys to
   GitHub Pages.
3. The frontend fetches `manifest.json`, then only the specific `daily/*.json.gz` / `hourly/*.json.gz` /
   `series/*.json.gz` files needed for the current view (never the whole dataset at once).
4. User reports go straight from the frontend to the Cloudflare Worker → D1, independent of the forecast
   pipeline. The frontend remains fully usable (map, forecast, charts) even if the Worker is unreachable.

### Generated output format

```
data/generated/latest/
  manifest.json          # generated_at, forecast window, file listing, model version, activity multipliers,
                          # series_shard_count / series_files
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

- **Weather** — [Open-Meteo](https://open-meteo.com/) (forecast + historical archive APIs). Free, keyless,
  CC-BY-4.0 attribution required (see their terms). Behind a `WeatherProvider` protocol
  (`forecast/src/weather.py`) so another provider can be swapped in later.
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

`scripts/prepare_grid.py` generates a regular ~5km grid over `SWEDEN_BBOX`, filtered against the real
boundary polygon above (`forecast/src/grid.py::generate_grid`), yielding roughly 18,000 land cells covering
the mainland, Gotland (~100 cells) and Öland (~60 cells); ocean cells are excluded by the boundary test. The
grid and its static features (`data/static/grid.json`, `data/static/cell_features.json`) are **not committed**
to git — they're regenerable from the boundary file + `config.py`, and are cached between CI runs via
`actions/cache` in `forecast.yml` (see that workflow's "Cache static grid + features" step), not via git.

Regenerate locally with:

```bash
python scripts/prepare_grid.py --resolution-km 5
python scripts/prepare_static_features.py
```

### Static geographic data

Real GIS layers are **not** committed (large, and often license-restricted for redistribution). To use real
data:

1. Download into `data/static/` (git-ignored except the small derived JSON files):
   - Copernicus CORINE / Copernicus Land Monitoring Service land cover → `land_cover.tif`
   - A water bodies / hydrography layer (Lantmäteriet open data or OSM water polygons) → `water_bodies.gpkg`
   - A DEM, e.g. Copernicus GLO-30 → `elevation.tif`
2. `pip install geopandas rasterio` (optional extras, commented out in `forecast/requirements.txt`)
3. `python scripts/prepare_static_features.py --real`

Without `--real`, the script (and the scheduled pipeline) uses `generate_placeholder_static_features()` —
deterministic per-cell values seeded from the cell ID and rough priors (more forest/wetland inland, more
urban near known city centers). Clearly a placeholder, not measured data.

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
features, live Open-Meteo weather. Run via `python scripts/run_forecast.py` or the scheduled GitHub Action.

### Performance at full-Sweden scale

Two optimisations make the ~18k-cell grid practical to (re)compute every 6 hours in CI:

- `forecast/src/pipeline.py::merge_weather` builds a `{time: index}` lookup once per cell instead of calling
  `list.index()` repeatedly (which turns an O(n) lookup into an accidental O(n²) scan per cell — the
  single biggest hidden cost at scale before this fix).
- `forecast/src/feature_engineering.py::precompute_rolling_windows` computes numpy cumulative sums for
  temperature/precipitation/soil-moisture once per cell, so the 49 hourly + 28 daypart `compute_features`
  calls per cell become O(1) index lookups instead of re-parsing timestamps and re-scanning multi-week
  windows on every call.

With both in place, a full pipeline run over all ~18,000 cells (synthetic weather, to isolate CPU cost from
network time) completes in **about 6 minutes** — comfortably inside GitHub Actions' job limits.

### Open-Meteo rate limiting at full-Sweden scale

The first live full-grid run (~700-800 batched HTTP requests, no pacing between them) got rate-limited (HTTP
429) by Open-Meteo's free archive API on nearly every request, and ran for over 2 hours before the job died
without completing — the original short exponential backoff (1s/2s/4s...) just re-hit the same quota window
on every retry instead of ever letting it reset. Fixed in `forecast/src/weather.py::OpenMeteoProvider`:

- **Proactive pacing** (`WEATHER_REQUEST_PACING_S`, default 2s) — a fixed delay before every real (non-cached)
  request, spacing consecutive batches out so the rate limit is never tripped in the first place, rather than
  only reacting after the fact.
- **Rate-limit-specific backoff** (`WEATHER_RATE_LIMIT_BACKOFF_S`, default 30s) — HTTP 429 specifically now
  gets a much longer, linearly-scaling wait instead of the generic exponential backoff used for other
  transient errors, as a safety net for occasional bursts pacing alone doesn't prevent.

Verified against the live API with a 150-cell subset (3 batches each direction): all 6 requests succeeded on
the first attempt with zero 429s. Expect full-grid production runs (~728 requests × ~2-3s each) to take
roughly 30-45 minutes end-to-end, dominated by this deliberate pacing rather than the ~6 minute CPU cost.

## GitHub Actions setup

Three workflows in `.github/workflows/`:

- **`test.yml`** — pytest, frontend typecheck/test/build, worker typecheck/test. Runs on PRs and pushes to `main`.
- **`forecast.yml`** — runs the pipeline every 6 hours (`workflow_dispatch` also available, with a `sample`
  input for testing). Caches grid/static-feature generation, commits `data/generated/latest` only if it
  changed, uploads the full run as a 90-day workflow artifact, and triggers `deploy-pages.yml`. Uses
  `concurrency: cancel-in-progress: false` so overlapping runs queue instead of racing. **If the pipeline's
  sanity checks fail** (see `forecast/src/output.py`), the job fails before anything is committed — the
  previously published forecast stays live.
- **`deploy-pages.yml`** — builds the frontend, bundles the latest forecast data (falling back to the
  committed sample data if no full-grid forecast exists yet), and deploys to GitHub Pages via
  `actions/deploy-pages`.

To enable: in repo Settings → Pages, set source to "GitHub Actions". No secrets are required for the
default (keyless) Open-Meteo + demo-basemap configuration.

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
point at the same domain. **The canonical/OG URLs use a placeholder domain, `https://www.myggprognos.se/`**
— update `index.html`, `robots.txt`, and `sitemap.xml` if the real production domain differs. No `og:image`
is set yet (would need a real 1200×630 PNG under `frontend/public/`); see the commented-out tag in
`index.html` and [Future improvements](#future-improvements) below.

## Future improvements

- **Real static GIS layers** — swap the placeholder forest/wetland/urban/water-body generator for real
  Copernicus/Lantmäteriet data (see [Static geographic data](#static-geographic-data)); this is the single
  biggest accuracy upgrade available without changing the model's structure.
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
