# Spatial resolution assessment (Phase 10)

Does the ~5km forecast grid smooth away important shoreline/wetland/small-water geography? Quantified
directly against real ESA WorldCover 10m data, not assumed.

## Method

For three real lake/wetland benchmark locations, read a full ~10m-resolution WorldCover window covering
one grid cell's own footprint (2.5km radius = the cell's nominal 5km×5km area), then split it into a
5×5 grid of 1km sub-cells and compare each sub-cell's water fraction to the single cell-average value
the pipeline actually publishes.

## Result

| Location | Cell-average water fraction | 1km sub-cell water fraction: min / max / std |
|---|---|---|
| Mora (Siljan) | 0.195 | 0.000 / 0.938 / 0.276 |
| Vänern strand (Lidköping) | 0.295 | 0.000 / 1.000 / 0.404 |
| Store Mosse | 0.011 (water); 0.028 (wetland) | 0.000 / 0.280 / 0.055 |

**Confirmed: yes, real sub-cell heterogeneity is being averaged away.** At both lake-shore locations, a
single 5km cell contains 1km sub-areas ranging from 0% water (dry land) to 93.8–100% water (open lake),
averaged into one published value per cell. A cell centered near a shoreline reads as "moderately
wet" (0.2–0.3) when it's actually a sharp binary mix of "fully dry" and "fully lake" sub-areas — exactly
the kind of blurring the new spec's Phase 10 asked to check for. Store Mosse (a large, relatively
uniform bog complex rather than a sharp shoreline) shows much lower internal variance (std 0.055),
confirming the effect is specifically a *shoreline/boundary* problem, not a general flaw in the whole
static-feature pipeline.

There is a second, distinct resolution issue beyond within-cell averaging: the grid's **cell spacing**
is also ~5km, so a real user location near a shoreline can nearest-cell-match to a grid point whose
center itself sits meaningfully on the "wrong side" of a sharp water/land boundary — no amount of
smarter within-cell averaging fixes this, since it's about which cell a coordinate resolves to at all,
not what that cell's own value represents.

## What this iteration already does about it

**Phase 4's multi-scale water/wetland features already directly address the within-cell-averaging half
of this problem**, and were built for exactly this reason: `water_fraction_500m` / `_2km` / `_5km`
(and the equivalent wetland fractions, plus shoreline/forest-water/wetland-water edge density) are all
computed from a single **~50m/px** raster read per cell (`_multiscale_habitat_features`,
`static_features.py`) — five times finer than the nominal 5km cell width, and finer than the sub-cell
blocks used in the analysis above. Rather than publish one flat cell-average fraction, `habitat_capacity`
is built from a weighted combination of these different-radius fractions plus the edge-density terms,
so a cell whose center happens to sit right at a lake margin (high shoreline/edge density, moderate
water fraction at 500m, higher at 5km) reads differently from one that's genuinely uniform bog/forest
at every scale, even though both might report a similar single flat "water_fraction" under the old
single-window design. This is already a real, if partial, mitigation of the averaging problem — not a
proposal for future work.

## What is NOT done, and the realistic path if it's ever needed

**Not attempted in this iteration**: increasing forecast-grid resolution nationally (e.g. to 1-2km
cells). This is explicitly the wrong lever per the new spec's own constraints ("do not massively
increase production dataset size unless justified", "do not radically redesign the architecture") and
the README's documented cost/reliability history: cell count drives weather-fetch request volume for
the Open-Meteo fallback path (already the source of serious rate-limiting incidents at ~18.6k cells,
see README "Open-Meteo weather fetching"), drives per-run CPU scoring time (~6 minutes at 18.6k cells
today), and drives generated-JSON output volume served to the frontend. Going to 2km cells alone would
be roughly a 6x cell-count increase nationally; 1km would be ~25x — a materially different operating
regime for a project explicitly built to run on free tiers.

**The remaining, cell-spacing half of the problem** (a query coordinate near a boundary nearest-
matching to the "wrong" cell) has a genuinely cheap fix that was NOT implemented in this iteration
(out of scope per "do not radically redesign the frontend") but is worth recording as the realistic
next step if boundary artifacts are reported in practice: **inverse-distance-weighted blending of the
nearest 2-4 cells** at query time (in `frontend/src/lib/api.ts`'s `nearestCell` and
`scripts/run_benchmarks.py`'s equivalent), rather than a hard nearest-cell snap. This changes zero
stored data, adds a small, bounded amount of client-side computation per query (not per cell in the
dataset), and directly smooths the visible jump across a cell boundary without touching grid
resolution, weather-fetch volume, or output size at all.
