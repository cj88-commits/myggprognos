# Model audit — before this iteration

Traces the complete score path from raw features to the public map colour, as it exists on `main` before any changes in this iteration. Read-only: nothing in this document reflects a change, only current behaviour.

Sources read: `forecast/src/{model,feature_engineering,config,pipeline,confidence,explanation,output,static_features,weather}.py`, `frontend/src/lib/riskModel.ts`, `frontend/src/components/MapView.tsx`, `frontend/src/App.tsx`.

## 1. Population potential (`model.py::compute_population_potential`)

Weighted sum (not product) of eight bounded 0–1 terms, normalized by total weight:

| term | shape | driven by |
|---|---|---|
| `temperature` (0.22) | sigmoid, midpoint = `development_base_temperature_c + 3` (≈13°C) | 14-day mean temp; ×0.5 if froze recently |
| `rainfall` (0.22) | bell curve, optimum 40mm/14d, width 35 | 14-day precipitation; ×0.4 if >18 days dry |
| `moisture` (0.14) | sigmoid, midpoint 0.28 | 7-day soil moisture mean (or fallback) |
| `wetland` (0.13) | linear ×1.8, clamped | static `wetland_fraction` |
| `forest` (0.07) | linear ×1.3, clamped | static `forest_fraction` |
| `season` (0.07) | bell curve, peak day 190 (~July 9), width narrows with latitude | day-of-year, latitude |
| `snowmelt` (0.05) | bell curve around day 135 (~May 15), ×0.35 if froze recently | day-of-year |
| `standing_water` (0.10) | see below | recent rainfall + slope + wetland + water density |

`standing_water_persistence` (`feature_engineering.py`) itself is `(0.5·rain₃d + 0.3·(rain₇d−rain₃d) + 0.1·(rain₁₄d−rain₇d)) / 40 × (0.4+0.6·wetland) × (0.5+0.5·water_density) × drainage_factor` — this is the only place recent rainfall is deliberately *lagged and decayed* rather than used at face value. It has no temperature dependence (a 5mm rain event contributes the same whether it's 2°C or 20°C).

**Result**: `population_potential` (0–100) is a smooth, slow-moving value — nothing here reacts to the *current* hour's weather. This is already close to what the spec calls "Myggläge."

## 2. Biting activity (`model.py::compute_biting_activity`)

**Plain product** (not weighted sum) of five 0–1 terms:

```
activity = temp_activity × humidity_activity × wind_suppression × daypart_activity × rain_suppression
```

- `temp_activity`: bell curve, optimum 23°C, width 10 — ×0.15 if ≤5°C
- `humidity_activity`: sigmoid, midpoint 40%
- `wind_suppression`: 1 − sigmoid(wind, midpoint 3.5 m/s) — full suppression by ~9 m/s
- `daypart_activity` (`_daypart_activity_curve`): crepuscular bell curve, dusk optimum hour=21, dawn optimum hour=5, with a midday dip at hour=13 — **fixed clock hours**, not solar-relative. Takes `features.hour_of_day`, which `feature_engineering.py` already sets from `local_time.hour` (Stockholm-local) — see bug #1 below for why this doesn't save the daily/daypart path.
- `rain_suppression`: 1 − sigmoid(current mm/h, midpoint 1.0)

A code comment explicitly documents *why* this is a plain product rather than a geometric mean: a geometric mean let mediocre-but-not-terrible conditions (15°C + light breeze) read as ~80% activity against field observations that contradicted it. That reasoning is sound for *activity itself* — the problem (see §4) is that this already-conservative 0–100 activity score is then multiplied a second time against population and exposure in `compute_score`, compounding suppression rather than modifying a population baseline.

## 3. Exposure (`model.py::compute_exposure`)

```
terrain_exposure = clamp(0.5 + 0.35·wetland_fraction + 0.25·forest_fraction − 0.15·urban_fraction)
water_term        = clamp(0.25·water_proximity + 0.5·water_body_density)
base_exposure     = 0.5·terrain_exposure + 0.5·water_term
exposure          = clamp(base_exposure × activity_multiplier, 0, 1.5) × 100
```

**Bug found — habitat double-counting (relevant to §5 of the new spec)**: `wetland_fraction` and `forest_fraction` are the *same* static inputs already weighted into `population_potential` (terms `wetland` and `forest` above). Exposure re-uses them again as if they were independent "human encounter" information, so a highly wetland/forested cell gets pushed up twice — once for "more mosquitoes are biologically plausible here" and again for "you are more exposed to them here," even though both claims come from one raster value. `activity_profile` (e.g. camping ×1.35, running ×0.75) is folded in here as a multiplier on the whole exposure term, before ever reaching `compute_score`.

## 4. Final risk (`model.py::compute_score`)

```python
combined_fraction = (population_potential/100) × (biting_activity/100) × clamp(exposure/100, 0, 1)
final_risk = clamp(combined_fraction × 100 × 2.6, 0, 100)
```

Three independent 0–1 fractions multiplied together, rescaled by a flat ×2.6 (chosen so three simultaneously-high components saturate near 100; it is not derived from any external calibration). **This is the mechanism behind the reported problem**: any single near-zero component drives the whole product toward zero regardless of how favourable the other two are. See worked examples below.

## 5. Category thresholds & map colour (duplicated, not shared)

- **Backend** `config.py::RISK_CATEGORIES`: fixed 20-point bands — `(0,19,very_low) (20,39,low) (40,59,moderate) (60,79,high) (80,100,very_high)`. Used by `model.py::risk_category` to generate the Swedish `explanation.summary` text.
- **Frontend** `riskModel.ts::RISK_CATEGORIES`: an **independently hand-copied duplicate** of the same five bands/colours, plus a separate continuous `RISK_COLOR_STOPS` ramp (0/20/40/60/80/100 → green…red) used by the map's `interpolate` expression. Nothing derives the frontend copy from the backend's config at build or runtime — a threshold change on one side silently doesn't propagate to the other. This is exactly the "backend/frontend threshold drift" risk the new spec's §9 warns about; it hasn't drifted *yet*, but the two are structurally independent today.

## 6. Daily summary & "peak" selection (`pipeline.py`, daily loop)

For each cell/day, `DAYPART_REPRESENTATIVE_HOUR = {morning: 8, afternoon: 14, evening: 20, night: 23}` is scored, and:

```python
peak_part = max(dayparts, key=lambda p: dayparts[p]["risk"])
```

The **daily record's own** `risk`/`population_potential`/`biting_activity`/`exposure`/`explanation` fields are simply the peak daypart's values — i.e. the daily JSON already *is* "today's peak," in current-formula terms. `peak_period` is stored and shown in the UI ("Högst risk väntas ...").

**Bug found #1 — daypart representative hours are constructed in UTC, not local (relevant to §7 of the new spec)**:

```python
target = datetime(target_date.year, target_date.month, target_date.day, hour, tzinfo=timezone.utc)
```

`hour` (8/14/20/23) is intended to mean Swedish clock time ("evening ≈ 20:00") but is attached with `tzinfo=timezone.utc`, i.e. it's actually 20:00 **UTC**. In CEST (summer, UTC+2) that instant is 22:00 local — already deep dusk/night, not "evening." "Night" (23 UTC) becomes 01:00 local **the next calendar day** in summer. "Morning" (8 UTC) becomes 10:00 CEST. `compute_features` does correctly convert `target_time.astimezone(SWEDEN_TZ)` internally for `hour_of_day`/`daypart`/`day_of_year` — but by then the *wrong instant* has already been chosen, so both the weather lookup (temperature/wind/humidity at that hour) and the crepuscular activity curve are evaluated ~1–2 hours off from the intended local daypart, worse in summer (CEST) than winter. This affects every daily/daypart record and therefore `peak_period` selection and the day's summary explanation. The separate **hourly** (first 48h) series is *not* affected — it walks forward in real wall-clock UTC instants one by one, and `compute_features`'s local-time conversion correctly labels each one; nothing in the hourly path assumes a UTC integer is a local hour.

**Bug found #2 — a single global placeholder flag hides per-cell fallbacks**:

```python
is_placeholder = static_placeholder if static_placeholder is not None else True
...
missing = [c.cell_id for c in cells if c.cell_id not in static_map]
if missing:
    logger.warning(...)
    for cell in cells:
        if cell.cell_id not in static_map:
            static_map[cell.cell_id] = generate_placeholder_static_features(cell)
```

`is_placeholder` is one boolean for the *entire run*, passed unchanged into `compute_confidence(..., static_data_is_placeholder=is_placeholder)` for every cell. A cell that individually falls back to `generate_placeholder_static_features` (e.g. missing from `cell_features.json`, outside a downloaded raster tile) still inherits the run's real-data confidence bonus (`static_quality = 0.95` instead of `0.55`) as long as most other cells had real data. Those cells are silently presented as equally reliable. This is precisely what the new spec's §11 asks to fix.

## 7. Where UTC/local conversions happen — full inventory

| location | UTC or local? | correct? |
|---|---|---|
| `pipeline.py` hourly loop (`hour_start + timedelta(hours=h)`) | UTC instant, walked forward | ✅ correct — real distinct instants, later locale-converted for activity curve |
| `pipeline.py` daily/daypart loop (`DAYPART_REPRESENTATIVE_HOUR`) | UTC hour used as if local | ❌ bug #1 above |
| `feature_engineering.py::compute_features` (`local_time = target_time.astimezone(SWEDEN_TZ)`) | converts to Stockholm local for `hour_of_day`/`daypart`/`day_of_year`/evening-window lookups | ✅ correct, but operates on whatever instant it's handed |
| `model.py::_daypart_activity_curve` | takes `features.hour_of_day` (already local) | ✅ correct input, fixed-clock curve (dawn=5, dusk=21) not solar-relative — see new spec §6 |
| `output.py` hourly filenames (`hourly/<date>T<UTC-hour>.json.gz`) | UTC-labelled | intentional (matches fetch/index scheme); frontend must never surface this raw |
| `frontend/src/lib/time.ts` (this session's earlier work) | converts UTC hour-bucket labels to Stockholm-local for all display | ✅ correct, added in the prior polish iteration |
| `frontend/src/App.tsx` default `hourOfDay` (`new Date().getUTCHours()`) | UTC hour used to index into `manifest.hourly_files` | ✅ correct — the array is UTC-indexed by construction |

## 8. Which values are written to JSON vs recomputed in TypeScript

Written by `output.py` per cell/day and per cell/hour: `risk, population_potential, biting_activity, exposure, base_exposure_fraction, confidence`. Daily records additionally carry `peak_period, dayparts{...}, explanation{...}, explanation_text[]`.

`frontend/src/lib/riskModel.ts::finalRiskForActivity` **re-implements** `compute_score`'s combination step client-side (`(population/100)×(activity/100)×clamp(exposure/100,0,1)×100×2.6`) so the UI can re-derive risk for a different `activity_profile` without refetching — this exactly mirrors the current (soon to change) formula and must be updated in lockstep with any backend formula change, or the two will diverge silently. `exposureForActivity` similarly reimplements the `base_exposure_fraction × activity_multiplier` step.

## Worked examples — why multiplication compresses toward zero

All use `final_risk = clamp(population/100 × activity/100 × clamp(exposure/100,0,1) × 100 × 2.6, 0, 100)`.

**Example A — favourable evening (baseline, all components reasonably high)**
population=70, activity=85, exposure=60
→ `0.70×0.85×0.60 = 0.357` → `35.7×2.6 = 92.8` → **very_high**. Sensible: warm, calm, humid dusk over decent habitat reads as high risk.

**Example B — the reported problem: good habitat, midday suppression**
population=60 (real habitat, moderate), activity=25 (cool + breezy midday), exposure=45 (moderate)
→ `0.60×0.25×0.45 = 0.0675` → `6.75×2.6 = 17.55` → **very_low** (band is 0–19).
A cell with genuinely substantial mosquito populations reads as "very low risk" purely because it's midday — even though the same cell in Example A's evening conditions would read >90. Population=60 and exposure=45 are both "moderate," yet the single suppressed factor (activity=25) drags the *product* below even the lowest non-trivial category.

**Example C — excellent habitat, still crushed by one weak factor**
population=80 (lots of standing water/wetland), activity=15 (cold + windy), exposure=80 (forested, near water)
→ `0.80×0.15×0.80 = 0.096` → `9.6×2.6 = 24.96` → **low**, barely above very_low, despite population and exposure both being high. This is the case that most concretely motivates §4 of the new spec: activity should *modify* an already-high population signal, not gate it down to "low."

**Example D — poor habitat, very favourable weather**
population=20 (dry area, little wetland), activity=80 (warm, humid, calm dusk), exposure=70
→ `0.20×0.80×0.70 = 0.112` → `11.2×2.6 = 29.12` → **low**.
Shows the compression cuts both ways: a genuinely low-population area can't read above "low" even under ideal weather, which is arguably correct (no mosquitoes to activate) — the asymmetry is that population *should* behave like a gate (no mosquitoes → no risk, regardless of weather), while activity currently behaves the same way population does (multiplicative gate) when it should behave more like a modifier around a population baseline.

## Summary of findings carried into this iteration

1. Multiplicative `population × activity × exposure` lets any single weak component collapse the score (Examples B, C) — addressed in §4/task "Redesign final nuisance formula."
2. Daypart representative hours are UTC-mislabelled-as-local (bug #1) — addressed in §7/"Fix local-time bucket construction," and makes solar-relative timing (§6) meaningless until fixed first.
3. A single global `is_placeholder` flag hides per-cell static-data fallbacks from confidence (bug #2) — addressed in §11/"Production static-feature audit."
4. Wetland/forest fractions are double-counted between population and exposure — addressed in §5/"Habitat double-counting."
5. Category thresholds are duplicated (not shared) between backend and frontend — addressed in §9/"Recalibrate category thresholds," which requires the frontend to consume backend-emitted thresholds.
6. Rainfall feeds population mostly at face value (`rainfall` term) with only `standing_water_persistence` genuinely lagged, and that term has no temperature-dependent development rate — addressed in §8/"Rainfall-to-population emergence lag."
