# Model audit — after this iteration's formula/exposure changes

Companion to `docs/model-audit-before.md`. Documents exactly what changed in `forecast/src/model.py` and `forecast/model.yaml`, why, and the empirical evidence used to pick the new configuration values — not asserted from the spec's suggested ranges blindly.

## 1. Habitat double-counting: what was found and what changed

Audited every static feature's use across `compute_population_potential` and `compute_exposure`:

| static feature | used in population_potential? | used in exposure (before)? | used in exposure (after) |
|---|---|---|---|
| `wetland_fraction` | yes — `wetland` term (weight 0.13) | yes — `terrain_exposure` (+0.35) | **removed** |
| `water_body_density` | yes — inside `standing_water_persistence` | yes — `water_term` (×0.5) | **removed** |
| `forest_fraction` | yes — `forest` term (weight 0.07) | yes — `terrain_exposure` (+0.25) | **kept**, different meaning (see below) |
| `urban_fraction` | no | yes — `terrain_exposure` (−0.15) | kept, unchanged role |
| `distance_to_water_km` | no | yes — `water_proximity` | kept, unchanged role |

Two double-counts existed, not just the one described in the original spec:

1. **`wetland_fraction`** — a cell's wetland coverage pushed `population_potential` up (more breeding habitat exists) *and* pushed `exposure` up again (as if wetland coverage were also independent evidence you'd personally encounter mosquitoes there). Removed from exposure entirely.
2. **`water_body_density`** — same pattern via `standing_water_persistence` (population) and `water_term` (exposure, previously). Removed from exposure entirely.

`forest_fraction` is **kept** in exposure, but its meaning changed: in `population_potential` it means "forest offers breeding-site shelter" (habitat); in `exposure` it now means "forest blocks wind, making it easier for mosquitoes already present to reach you" (encounter conditions). These are genuinely different claims even though they read the same static raster value, so keeping it in both is not the same category of bug as the wetland/water-density cases — a forested cell really is both more likely to host mosquitoes *and* a place where wind isn't chasing them off you.

`distance_to_water_km` and `urban_fraction` were never used in `population_potential`, so no change was needed there — they were already encounter-specific.

## 2. New `compute_exposure`

```
water_proximity  = sigmoid(distance_to_water_km, midpoint=1.5km)          # unchanged
terrain_exposure = clamp(0.55 + 0.20·forest_fraction − 0.20·urban_fraction)  # wetland term removed, weights re-tuned
base_exposure    = clamp(0.65·terrain_exposure + 0.35·water_proximity)    # water_body_density term removed
exposure         = clamp(base_exposure × activity_profile_multiplier) × 100
```

`base_exposure_fraction` (0–1, pre-activity-profile) is still stored per record, now representing only shelter/urban-context/water-proximity — nothing that already appears in `population_potential`.

## 3. New combination formula (`compute_score`)

Replaces the plain `population × activity × exposure` product (see audit-before's Examples B/C for why that collapsed real population signals to near-zero) with population as a gate and activity/exposure as modifiers around a neutral midpoint:

```
population_fraction = population_potential / 100
activity_fraction    = biting_activity / 100
exposure_fraction    = base_exposure_fraction   (pre-profile-multiplier)

activity_modifier = activity_floor + activity_weight · activity_fraction
exposure_modifier = (exposure_floor + exposure_weight · exposure_fraction) × activity_profile_multiplier

risk = clamp(population_fraction × activity_modifier × exposure_modifier × scale, 0, 100)
```

All five constants (`activity_floor/weight`, `exposure_floor/weight`, `scale`) live in `model.yaml`'s new `combination:` section, not hardcoded.

## 4. Calibration: what was actually tried, against real data

The spec's suggested starting ranges (activity modifier 0.25–1.00, exposure modifier 0.75–1.25) were **not** accepted as-is. Instead, four candidate configs were evaluated offline against the real, currently-published full-Sweden dataset (`data/generated/latest`, 23,194 cells, Aug 2026): each cell's already-computed `population_potential`/`biting_activity` (both formulas unchanged by this iteration) were combined with a freshly-recomputed exposure fraction from that cell's real static features (`cells.json.gz`, via the actual new `compute_exposure` code, not a reimplementation), under each candidate's floor/weight/scale.

| config | today (peak) mean/median | midday mean | evening mean | high+very_high % | 90+ % |
|---|---|---|---|---|---|
| spec-suggested (0.25–1.00 / 0.75–1.25, scale 85) | 28.1 / 24.9 | 22.1 | 27.6 | 0.0% | 0.0% |
| **chosen: 0.30–1.00 / 0.75–1.25, scale 105** | 35.2 / 31.2 | 28.4 | 34.6 | 2.0% | 0.0% |
| 0.35–1.00 / 0.75–1.25, scale 100 | 33.9 / 30.1 | 28.0 | 33.4 | 0.5% | 0.0% |
| 0.35–1.00 / 0.75–1.25, scale 95 | 32.2 / 28.6 | 26.6 | 31.7 | 0.1% | 0.0% |

The spec-suggested config produced **zero** cells in high/very_high on this real week's data — every candidate turned out conservative relative to how rarely population, activity, and exposure are all simultaneously near-maximal in practice, but the spec-suggested one flattened the top of the distribution entirely. The chosen config (`activity_floor=0.30, activity_weight=0.70, exposure_floor=0.75, exposure_weight=0.50, scale=105`) was the only one that preserved a visible (if small) high-risk tail while still meeting every other criterion:

- **No collapse-to-zero**: `zero_pct` (cells reading <1) was 0.0% for every config, at every hour tested, including midday.
- **Midday vs evening still distinguished**: chosen config gives midday mean 28.4 vs evening mean 34.6 (~22% relative difference) — a real, visible contrast, not flattened away.
- **Regional variation preserved**: Götaland 47.5 vs Norrland 24.4 (roughly 2×) under the chosen config, for the daily/peak product.
- **No saturation**: 0.0% of cells reach 90+ under any candidate, on this week's real data — population_potential itself tops out at 69 (never near 100) for this dataset/week, so the "avoid saturating Sweden at 100" criterion is trivially met; this is a property of the actual current weather, not evidence the formula can't reach high values when population genuinely is high.

**Direct before/after on real cells matching the reported problem** (highest population-to-midday-activity mismatch in the real dataset, `hourly/2026-08-04T13.json.gz`):

| cell | population | midday activity | OLD risk | NEW risk |
|---|---|---|---|---|
| SE_0239_0045 | 25.5 | 10.0 | 2.2 | 10.4 |
| SE_0237_0045 | 27.3 | 10.7 | 2.0 | 10.0 |
| SE_0238_0045 | 27.5 | 11.3 | 2.5 | 11.2 |
| SE_ISLE_0059_0000_3946 | 29.4 | 13.1 | 3.6 | 13.0 |

These are the real cells with the worst midday activity/population mismatch this particular week — population here is only moderate (~25–30, not the audit doc's illustrative 60–80), so the swing is a ~4–5× increase rather than the dramatic ~18→93 the constructed Example C implied, but the direction and mechanism are confirmed on real production data: the old formula crushed these to near-zero (2–4) regardless of a real, moderate population signal; the new one keeps them proportionate (10–13, still correctly "very_low" — moderate population midday genuinely is lower risk, just not *erased*).

## 5. Honest limitations of this calibration

- This was checked against **one week's real weather** (early August 2026). It has not been checked across a full season, so behaviour in, say, a cold rainy July or a hot dry September is unverified against real data — only against the formula's mathematical bounds (unit tests).
- `population_potential` in the current dataset never exceeds ~69; the "no saturation" result is real but untested at the top of the population range, since no real cell this week reaches it. A future run with more extreme conditions should be re-checked against the same criteria.
- `activity_floor`/`weight` and `exposure_floor`/`weight` were tuned together as a small grid of hand-picked candidates (4 tried), not a systematic sweep — a wider search might find a better-fitting combination, but this was judged sufficient to fix the specific reported failure mode without over-fitting to one week of data.
- No real mosquito-abundance observations were used anywhere in this calibration — see the top-level final report for the same caveat stated explicitly.
