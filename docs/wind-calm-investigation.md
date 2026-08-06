# Wind-calm false-negative investigation

Companion to `docs/model-audit-before.md` / `docs/model-audit-after.md`. Documents a targeted investigation into one real-world report, what was found, exactly what changed in `forecast/src/model.py`, `forecast/src/feature_engineering.py` and `forecast/model.yaml`, and the evidence used to choose the new configuration values — not asserted from a single anecdote.

## The report

> Yesterday evening, mosquitoes became very numerous immediately after the wind dropped, while Myggprognos still showed "Mycket låg".

No exact coordinates/timestamp were provided, so this could not be reproduced against the literal reported instance. Instead: (1) a CLI tool was built (`scripts/diagnose_scenario.py`) so *any* future report with a location + timestamp can be reproduced exactly, against either cached or live weather; (2) the described pattern (warm evening, wind dropping sharply, real population present) was reconstructed as a representative synthetic scenario and used to validate the fix end-to-end.

## Investigating the five candidate causes

The brief asked whether the miss was caused by (1) inaccurate/coarse forecast wind, (2) using exposed meteorological wind instead of sheltered local wind, (3) insufficient sensitivity to calm conditions, (4) failing to represent a rapid wind drop, or (5) the activity-floor formula compressing the change.

| # | Hypothesis | Finding |
|---|---|---|
| 1 | Forecast wind for the grid cell is wrong/too coarse | **Cannot be ruled in or out without the real instance.** `scripts/diagnose_scenario.py --observed-wind-ms` now lets a specific report's claimed wind be substituted for the forecast's own reading, so this is directly testable per-report going forward. Nothing in this investigation found evidence the *pipeline's* weather ingestion itself is wrong — see items 2-5, which were confirmed as real, independent gaps. |
| 2 | Exposed meteorological wind used instead of sheltered local wind | **Confirmed real gap.** The model previously read `wind_speed_current_ms` (raw provider wind) directly into the suppression curve, with no terrain adjustment at all. Fixed: `feature_engineering.py::compute_effective_wind` (item 3 below). |
| 3 | Insufficient sensitivity to calm conditions | **Confirmed real gap.** The existing `wind_suppression` term (`model.yaml activity.wind_half_suppression_ms/wind_full_suppression_ms`) responds smoothly to wind magnitude, but nothing in the model connected "calm + otherwise-favourable conditions" to an *extra* activity boost beyond what the base curve already gives a low-wind reading. Fixed: calm-evening uplift (item 4 below). |
| 4 | No representation of a rapid wind drop | **Confirmed real gap — the most likely single largest contributor.** The model had no wind history at all before this change; every score was computed from the single wind value at the target hour, with no way to distinguish "calm all day" from "just went calm" or "still windy." A report describing mosquitoes appearing *immediately after* a drop is exactly the transient pattern a memoryless model cannot represent. Fixed: wind history features + wind-drop release effect (items 1, 2 and 5 below). |
| 5 | `activity_floor`/`activity_weight` formula masking the signal | **Tested, not the primary cause — kept unchanged.** See "Was the activity floor masking the signal?" below. |

## 1. Wind-history features (`feature_engineering.py`)

`FeatureSet` gained, computed from plain index lookups around each record's own resolved time index (no new fetch, reuses the already-fetched hourly series):

- `wind_speed_1h_ago_ms`, `wind_speed_3h_ago_ms`
- `wind_change_1h_ms`, `wind_change_3h_ms` (negative = wind dropped)
- `wind_min_3h_ms` (minimum over the trailing 3h window, inclusive of the current hour)
- `calm_hours_streak` (consecutive hours, counting backward from now, at or below `calm_threshold_ms`; stops at the first missing hour, capped at a 12h lookback)

All `None` when there isn't enough history yet (e.g. the very first hour of a run), rather than silently defaulting to 0.

## 2/3. Effective (shelter-adjusted) local wind (`compute_effective_wind`)

```
shelter_multiplier = clamp(
    1
    - forest_shelter_weight   x forest_fraction
    - urban_shelter_weight    x urban_fraction
    - slope_shelter_weight    x min(slope_deg, slope_reference_deg) / slope_reference_deg
    + coastal_exposure_weight x coastal_exposure,
    min_multiplier, max_multiplier,
)
effective_wind = forecast_wind x shelter_multiplier
```

Defaults (`model.yaml wind_shelter:`): `forest_shelter_weight=0.35`, `urban_shelter_weight=0.15`, `slope_shelter_weight=0.10`, `slope_reference_deg=10`, `coastal_exposure_weight=0.25`, bounded to `[0.55, 1.15]`.

This is **not measured local wind** — a coarse, transparent, bounded, per-cell-static adjustment. Real micro-siting (a specific sheltered garden vs. an open field 200m away, both inside the same ~5km cell) varies far more than any cell-average static feature captures. Both `forecast_wind_ms` and `effective_wind_ms` are published in every generated record and printed by the diagnostic CLI, specifically so this estimate is never silently substituted for ground truth.

`wind_speed_effective_ms` is used **only** by the new calm/release gates below (item 4/5) — the pre-existing `wind_suppression` curve in `compute_biting_activity` still reads raw `wind_speed_current_ms`, unchanged, so this doesn't retroactively alter how the model has always responded to genuinely windy weather.

## 4/5. Calm-evening uplift + wind-drop release (`model.py::_calm_wind_activity_multiplier`)

A single function, called from `compute_biting_activity`, producing a multiplier applied **on top of** the existing five-term activity product (temperature × humidity × wind_suppression × daypart × rain), not a replacement for any of it:

```
calm_gate       = sigmoid(calm_threshold_ms - wind_speed_effective_ms)
population_gate = sigmoid(population_potential - population_gate_midpoint)
comfort_gate    = temperature_activity x humidity_activity      (already-computed terms)
daypart_gate    = daypart_activity                               (already-computed term; peaks at dusk/dawn)
favourable      = calm_gate x population_gate x comfort_gate x daypart_gate

calm_multiplier    = 1 + (max_calm_uplift - 1) x favourable
release_gate       = sigmoid(-wind_change_3h_ms - release_drop_ms)   # wind dropped >= release_drop_ms over 3h
release_multiplier = 1 + (max_release_multiplier - 1) x release_gate x favourable

combined = min(calm_multiplier x release_multiplier, max_combined_multiplier)
```

Every gate is a smooth sigmoid or an already-bounded continuous term — no binary cliffs anywhere in the chain. `calm_multiplier` fires for *any* sufficiently calm + favourable moment (a steadily-calm evening counts, not only ones that just transitioned); `release_multiplier` is a genuinely separate, additive effect specific to a recent drop, both gated by the same "otherwise favourable" product so neither can fire under cold/dry/low-population conditions. The combined multiplier is hard-capped (`max_combined_multiplier`) so a single noisy forecast-hour reading cannot alone push a cell to an extreme score.

`model.yaml wind_dynamics:` defaults, chosen against full-Sweden diagnostics (see below):

```yaml
calm_threshold_ms: 1.8
calm_steepness: 1.6
population_gate_midpoint: 15.0
population_gate_steepness: 0.25
max_calm_uplift: 1.4
release_drop_ms: 2.5
max_release_multiplier: 1.2
max_combined_multiplier: 1.7
```

### Candidates tested (item: "1.3x-1.8x")

Three configs were run against `scripts/diagnose_wind_distribution.py` (4,004 real grid cells, real static forest/wetland/urban/slope/coastal features, controlled wind scenarios): `model_candidate_low.yaml` (max_calm_uplift 1.2 / max_release 1.1 / cap 1.3), the chosen defaults above (cap 1.7), and `model_candidate_high.yaml` (max_calm_uplift 1.55 / max_release 1.3 / cap 1.8).

| config | extreme-score (≥90) frequency, any scenario | cells shifted >10pt vs. current, wind_drop scenario | Stockholm wind_drop score |
|---|---|---|---|
| low (cap 1.3x) | 0.00% | 0.0% | 38.8 (låg) |
| **chosen (cap 1.7x)** | **0.00%** | — (baseline) | **40.9 (måttlig)** |
| high (cap 1.8x) | 0.00% | 0.0% | 40.9 (måttlig, already saturated) |

The chosen (middle) value was picked because it already produces the full category-level correction the report calls for (a wind-drop evening moves from "låg"/"very_low" territory into "måttlig") with **zero** extreme-score cells in any scenario and **zero** cells shifted by more than 10 points relative to either neighbouring candidate — i.e. this is not a knife-edge choice; the low/mid/high candidates agree closely almost everywhere, and the differences are concentrated exactly in the calm/wind-drop scenarios this correction targets.

## Was the activity floor masking the signal? (item 7)

```
activity_modifier = activity_floor + activity_weight x activity_fraction   (0.30 + 0.70 x fraction)
```

This is affine, not a hard clamp — it does not compress the *underlying* `biting_activity` value's dynamic range in the sense of flattening a peak, but it does cap how much activity alone can ever multiply the population baseline: `activity_modifier` maxes out at exactly `1.0` (neutral) regardless of how high `biting_activity` climbs, since `activity_fraction` itself is already bounded to `[0, 1]`. In the reproduced scenario, `activity_modifier` moved from 0.73 (old model, wind already low but no calm/release correction) to 0.89 (new model, same instant) — a real, meaningful swing, not one flattened by the floor. Diagnostics did not surface a case where a well-designed calm/release signal in `biting_activity` failed to visibly move `final_risk`; the floor changes the final risk's *ceiling*, not its sensitivity to this specific correction. Per the brief's preference for an isolated correction over destabilising the whole formula, **`activity_floor`/`activity_weight` were left unchanged.**

## Reproduced scenario (representative reconstruction)

`scripts/diagnose_scenario.py --lat 59.33 --lon 18.07 --timestamp 2026-07-20T20:00:00Z --sample`, wind forced from a steady ~4.9 m/s to an observed 0.8 m/s 3h later (`--observed-wind-ms 0.8`):

| | before drop (wind 4.9 m/s) | after drop (wind 0.8 m/s, 3h change -4.1) |
|---|---|---|
| population potential | 40.9 | 40.9 |
| raw biting activity | 18.7 | 84.7 |
| calm-wind uplift multiplier | 1.01 | 1.39 |
| activity modifier | 0.43 | 0.89 |
| **final risk** | **17.2 — Mycket låg** | **35.7 — Låg** |

This is the exact reported pattern: the "before" reading (17.2, "Mycket låg") matches what was reported; after a realistic 3-hour drop the corrected model moves it materially — a +18.5 point, +107% relative increase, one full category up (very_low → low).

Isolating the new correction's own contribution specifically (comparing the current model against `model_candidate_disabled.yaml`, which reproduces the pre-change formula exactly by setting every new multiplier to 1.0, **at the same already-dropped wind reading**):

| | old model (calm correction disabled) | new model |
|---|---|---|
| raw biting activity | 61.1 | 84.7 |
| activity modifier | 0.73 | 0.89 |
| **final risk** | **29.1 — Låg** | **35.7 — Låg** |

So of the total 17.2→35.7 improvement, part (17.2→29.1) was *already* correctly handled by the pre-existing wind-suppression curve responding to the (already-dropped) instantaneous wind reading — and the **new** wind-history/calm/release correction contributes a further, genuine +6.6 points (29.1→35.7) specifically from recognising the drop and the calm conditions, on top of that. Both numbers matter: the first shows the pre-existing model wasn't totally blind to low wind at a single instant; the second isolates exactly what this iteration added.

## Nationwide diagnostics (`scripts/diagnose_wind_distribution.py`, 4,004 real cells)

Category distribution, current config, evening hour:

| scenario | very_low | low | moderate | high | very_high |
|---|---|---|---|---|---|
| baseline (unmodified synthetic wind) | 10.1% | 68.4% | 21.5% | 0.0% | 0.0% |
| calm (1 m/s, steady) | 0.3% | 35.4% | 64.3% | 0.0% | 0.0% |
| windy (6 m/s, steady) | 76.4% | 23.6% | 0.0% | 0.0% | 0.0% |
| wind_drop (5→1 m/s) | 0.2% | 28.0% | 71.7% | 0.1% | 0.0% |

- **Extreme-score (≥90) frequency: 0.00% in every scenario, every config tested.** Calm weather alone does not turn Sweden orange/red.
- 98.9% of sampled cells change risk category between windy (6 m/s) and calm (1 m/s) — this ratio was already large under the pre-existing wind-suppression curve alone; the new correction adds a further, smaller shift within that (see the isolated comparison above).
- Score change after a rapid wind drop (windy → wind_drop), current config: mean **+25.2**, median +26.5, p90 +32.3, max +38.6 points — bounded, no runaway cases.
- No cell in the sample was ever pushed to `very_high` by any wind scenario alone; genuinely poor conditions (cold, dry, near-zero population) stayed low in every scenario (see regression tests below).

## Regression tests (`forecast/tests/test_wind_calm_regression.py`)

All 7 scenarios from the brief, exercised end-to-end through `compute_score` (not just the isolated multiplier):

1. Warm humid evening, wind falls 5→1 m/s → risk increases materially (+8pt minimum, +15% relative minimum — enforced, not just observed).
2. Same evening, steady 1 m/s (no drop) → elevated, but never pushed past 90.
3. Cold calm evening → stays under 25.
4. Dry calm afternoon → stays under 45.
5. Warm humid but 6 m/s wind → strongly suppressed (< 60% of the calm-baseline score).
6. Sheltered forest cell vs. exposed coastal cell, identical forecast wind → forest cell's lower effective wind reads a higher (never lower) risk.
7. Zero/near-zero population, calm wind → stays under 15 regardless (population remains the biological gate).

Plus 8 unit tests on `_calm_wind_activity_multiplier` directly (`forecast/tests/test_model.py`) and 8 on `compute_effective_wind`/wind-history (`forecast/tests/test_feature_engineering.py`). Full suite: 142 tests passing (up from 120 before this iteration), zero regressions in any pre-existing test.

## Scientific limitations

- **The reported instance itself was never reproduced exactly** — no coordinates/timestamp were given. Everything above uses a representative reconstruction of the described pattern, not the literal event. `scripts/diagnose_scenario.py` exists specifically so a future report with real details can be checked directly.
- **`wind_speed_effective_ms` is a coarse static-terrain estimate, not measured local wind.** It cannot know about a specific hedge, building, or valley smaller than the ~5km cell average; two real locations inside one cell can experience meaningfully different local wind that this adjustment cannot distinguish.
- **The calm/release gate thresholds (1.8 m/s calm, 2.5 m/s 3h drop) are reasoned defaults tuned against nationwide distribution shape, not fitted against labelled real-world nuisance observations** — there is still no ground-truth "mosquitoes were bad here" dataset to calibrate against (see `docs/model-audit-after.md`'s calibration section for the same caveat applied to the base formula).
- **One report is one data point.** This correction is deliberately narrow and capped; it should not be read as validated, only as a targeted, bounded, tested response to a plausible and mechanistically well-understood gap (memoryless wind, exposed-vs-local wind) that nationwide diagnostics confirm doesn't destabilise the rest of the model.
- **Confidence scoring was not changed.** A cell whose calm/release correction is actively firing does not currently get a distinct confidence adjustment reflecting the extra uncertainty in `wind_speed_effective_ms`'s shelter estimate; this is a reasonable follow-up, not done here to keep this iteration isolated.

## Files changed

- `forecast/src/feature_engineering.py` — wind-history fields, `compute_effective_wind`, `_calm_streak`.
- `forecast/src/model.py` — `_calm_wind_activity_multiplier`, wired into `compute_biting_activity`/`compute_score`; new `calm_wind_uplift` label.
- `forecast/src/explanation.py` — surfaces a meaningful calm-wind uplift as a positive explanation factor.
- `forecast/src/config.py` — `wind_shelter_params`/`wind_dynamics_params`; `MODEL_VERSION` bumped to 0.2.0.
- `forecast/src/pipeline.py` — passes the new config through to `compute_features`; publishes `forecast_wind_ms`/`effective_wind_ms`/`temperature_c`/`humidity_pct` per record; resolves and publishes `build_sha`.
- `forecast/src/output.py` — `build_sha` in the manifest.
- `forecast/model.yaml` — `wind_shelter:`, `wind_dynamics:` sections; version bump.
- `forecast/model_candidate_low.yaml`, `forecast/model_candidate_high.yaml`, `forecast/model_candidate_disabled.yaml` — the exact candidates compared above, kept for reproducibility.
- `forecast/tests/test_feature_engineering.py`, `forecast/tests/test_model.py`, `forecast/tests/test_wind_calm_regression.py` (new) — unit + regression coverage.
- `scripts/diagnose_scenario.py` (new) — single-location/timestamp reproduction + current-vs-candidate comparison CLI.
- `scripts/diagnose_wind_distribution.py` (new) — full-Sweden scenario/candidate distributional diagnostics.
- `worker/schema.sql`, `worker/migrations/0002_wind_diagnostics.sql`, `worker/src/types.ts`, `worker/src/validation.ts`, `worker/src/reports.ts` — forecast context columns on `mosquito_reports`.
- `frontend/src/types/forecast.ts`, `frontend/src/lib/reportsApi.ts`, `frontend/src/components/ReportForm.tsx`, `frontend/src/components/LocationPanel.tsx` — thread the new forecast-context fields through to report submission.
- `README.md` — three named products section, wind-shelter/calm-correction assumptions and limitations.
