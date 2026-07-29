# Mosquito Risk — Sweden

An experimental, public-facing seven-day mosquito activity forecast for Sweden: an interactive map, hourly
detail for the next 48 hours, place search, explainable risk factors, and a simple user-reporting system.
Built to be cheap to run — a static frontend, a scheduled Python pipeline, and a tiny serverless API, all on
free tiers.

**This is not a measurement of actual mosquito counts, and it is not a public-health disease-risk system.**
It's a transparent, rule-based estimate of how favourable conditions are for mosquitoes, built from open
weather and land-cover data. See [Limitations](#limitations) below.

## What it does

For any point in Sweden, at any hour over the next week, the app answers:

- How bad are mosquitoes likely to be? (**Mosquito Risk**, 0–10)
- How will that change over the next seven days, and through the day?
- What time of day will activity peak?
- Why is the risk high or low?
- How confident is the forecast?
- Are nearby users reporting similar conditions?

## What the score means

**Mosquito Risk** is a 0–10 score combining three components, each also shown individually:

| Component | Meaning |
|---|---|
| **Population potential** | How favourable recent weeks' weather has been for mosquito development (warmth, rainfall, moisture, habitat). |
| **Biting activity** | How active mosquitoes are likely to be at the selected hour, given temperature, humidity, wind, and time of day. |
| **Exposure** | How likely a person is to encounter mosquitoes given the terrain, proximity to water, and their chosen activity. |

`risk = population_potential × biting_activity × exposure`, rescaled to 0–10.

| Score | Category |
|---|---|
| 0.0–1.9 | Very low |
| 2.0–3.9 | Low |
| 4.0–5.9 | Moderate |
| 6.0–7.9 | High |
| 8.0–10.0 | Very high |

A **confidence** score (0–1, shown as Low/Medium/High) reflects forecast horizon, weather data completeness,
static data quality, and agreement between the three components — see `forecast/src/confidence.py`.

## Limitations

- **Not a measured mosquito count.** The model estimates favourable *conditions*, not actual mosquito
  presence or density.
- **Not a disease-risk tool.** It says nothing about mosquito-borne disease risk.
- **Static data is placeholder-quality in this MVP.** Land cover, wetland/forest fraction, and water
  proximity are deterministic *placeholders* (see [Static geographic data](#static-geographic-data)) unless
  you plug in real GIS layers.
- **Accuracy declines with forecast horizon** — day 7 is far less reliable than hour 1.
- **User reports may be biased** (self-selected reporters, uneven geographic coverage) and are only ever
  blended in as a small, capped adjustment on top of the model — see [User reports](#user-reports-1).
- **The rule-based model is a first version**, not a validated entomological model. Weights in
  `forecast/model.yaml` are reasonable priors, not fitted/calibrated coefficients.

## Architecture

```
frontend/   React + TypeScript + Vite + MapLibre GL JS + Recharts, deployed to GitHub Pages
forecast/   Python 3.12 pipeline (weather → features → rule-based model → generated JSON), run by GitHub Actions every 6h
worker/     Cloudflare Worker + D1, a tiny API for user mosquito reports
data/       static (grid + land-cover placeholders), samples (fixtures), generated (pipeline output)
scripts/    one-off/maintenance CLIs: prepare_grid, prepare_static_features, run_forecast
```

No persistent backend server: the frontend reads pre-computed, gzip-compressed JSON files published as
static assets, and the only dynamic API is the small Worker used for user reports. This keeps hosting cost
close to $0/month at MVP traffic levels (GitHub Pages is free; Cloudflare Workers + D1 free tiers are
generous; Open-Meteo is free and keyless).

### Data flow

1. `forecast.yml` runs the Python pipeline every 6 hours: fetch weather (Open-Meteo) → compute features →
   score with the rule-based model → write compact gzip JSON under `data/generated/latest/` → commit.
2. `deploy-pages.yml` builds the frontend and bundles `data/generated/latest/` alongside it, then deploys to
   GitHub Pages.
3. The frontend fetches `manifest.json`, then only the specific `daily/*.json.gz` / `hourly/*.json.gz` files
   needed for the current view (never the whole dataset at once).
4. User reports go straight from the frontend to the Cloudflare Worker → D1, independent of the forecast
   pipeline. The frontend remains fully usable (map, forecast, charts) even if the Worker is unreachable.

### Generated output format

```
data/generated/latest/
  manifest.json          # generated_at, forecast window, file listing, model version, activity multipliers
  cells.json.gz          # static per-cell metadata (id, lat/lon, land-cover fractions)
  daily/YYYY-MM-DD.json.gz     # one file per forecast day, all cells, with dayparts + explanation
  hourly/YYYY-MM-DDTHH.json.gz # one file per hour for the first 48h, all cells
  locations/index.json.gz      # small place-name gazetteer for offline search fallback
```

Design choice: many small files rather than one large GeoJSON, so the frontend only downloads what the
current view needs. **Known limitation:** the location detail panel currently fetches all 7 daily + 49
hourly files to build a location's charts (bounded to 6 concurrent requests — see
`frontend/src/lib/concurrency.ts`). Fine for the sample grid; for a full-Sweden production grid, consider
adding a pre-bundled per-cell time-series file as a follow-up optimisation.

## Data sources

- **Weather** — [Open-Meteo](https://open-meteo.com/) (forecast + historical archive APIs). Free, keyless,
  CC-BY-4.0 attribution required (see their terms). Behind a `WeatherProvider` protocol
  (`forecast/src/weather.py`) so another provider can be swapped in later.
- **Place search** — local static gazetteer (`data/static/places.json`) plus live
  [Nominatim/OpenStreetMap](https://nominatim.org/) search, attributed in the UI, debounced, min 2 characters,
  max 8 results. OSM data © OpenStreetMap contributors, ODbL.
- **Static geography** — designed for Copernicus land cover, wetland/forest layers, hydrography, and a DEM
  (see [below](#static-geographic-data)); **not bundled** in this repo. A deterministic placeholder generator
  is used until real layers are configured.
- **Basemap** — MapLibre's free, keyless [demo tiles](https://demotiles.maplibre.org/) by default (simplified);
  swap in a richer free-tier style via `VITE_MAP_STYLE_URL` (e.g. MapTiler, Stadia Maps).

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
- This repository's own code has no third-party data bundled beyond the small `data/static/places.json`
  gazetteer (hand-compiled city/municipality coordinates) and MapLibre's demo style.

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

**Production mode** (default): a full ~5km Sweden grid (`scripts/prepare_grid.py`), placeholder or real
static features, live Open-Meteo weather. Run via `python scripts/run_forecast.py` or the scheduled GitHub
Action.

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

### Historical forecast archive

Chosen MVP strategy (see spec section 18): `data/generated/latest` is committed and overwritten every run
(so the working tree never grows unbounded), while the **full output of every run is retained as a 90-day
GitHub Actions artifact** via `actions/upload-artifact`. This gives cheap short-term forecast-vs-actual
comparison ability without a database. If longer retention or query-ability is needed later, the natural
upgrade is to also write evaluation-ready summaries into the Worker's D1 database.

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
activity/exposure weights, activity multipliers, confidence weights, report-adjustment tiers) — nothing is
a hard-coded magic number in the pipeline code. `forecast/src/model.py` implements the actual scoring using
bounded `clamp` / `scale_sigmoid` / `bell_curve` transforms rather than raw linear sums, to avoid false
precision and keep every sub-score naturally bounded to [0, 1] before combination.

## Testing

- `cd forecast && pytest -v` — 53 tests: unit tests for every scoring sub-function, feature engineering,
  confidence, explanation generation, weather provider (mocked HTTP, retries/backoff, validation), grid
  generation, output writing/sanity checks, and end-to-end pipeline + five-location fixture/snapshot tests.
- `cd frontend && npm test` — Vitest: risk-recombination math, URL state round-tripping, report-adjustment
  tiering.
- `cd worker && npm test` — Vitest: input validation, bbox parsing, report-weight tiering, IP hashing.

## Troubleshooting

- **`npm run dev` shows "Could not load forecast data"** — make sure `frontend/public/data/latest/`
  exists (`make sample-data` or `python scripts/run_forecast.py --sample` then copy the output there).
- **Pipeline fails sanity checks** — check the Action logs; common causes are a large cell-count drop
  (partial weather fetch failure) or an out-of-range score, both of which intentionally abort *before*
  publishing so the live site keeps the last good forecast.
- **Map basemap looks very plain** — that's the free, keyless MapLibre demo style; set
  `VITE_MAP_STYLE_URL` to a richer style for production.
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
