# Model output diagnostics

Generated from forecast run `2026-08-04T10:10:54Z`, 23194 cells.

## Suspicious patterns
- ⚠ 2026-08-04 (Myggrisk idag): high, very_high are completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-04 (Myggläge): very_high is completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-05 (Myggrisk idag): high, very_high are completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-05 (Myggläge): very_high is completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-06 (Myggrisk idag): moderate, high, very_high are completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-06 (Myggläge): very_high is completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-07 (Myggrisk idag): moderate, high, very_high are completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-07 (Myggläge): very_high is completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-08 (Myggrisk idag): moderate, high, very_high are completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-08 (Myggläge): very_high is completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-09 (Myggrisk idag): moderate, high, very_high are completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-09 (Myggläge): very_high is completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-10: 93% of Sweden is in a single risk category ('very_low') -- check for a model component saturating (e.g. exposure or population term pinned near 0 or 1).
- ⚠ 2026-08-10 (Myggrisk idag): moderate, high, very_high are completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).
- ⚠ 2026-08-10 (Myggläge): very_high is completely empty (0.0% of cells) -- the category threshold may be unreachable for this product; consider recalibrating against real output (see docs/model-audit-after.md).

## Cell-to-cell spatial discontinuity (today, adjacent 5km cells)

Pairs checked: 18052 -- mean 1.83, p95 5.37, max 20.48 points.

## Six-hour change distribution (single-cell risk swing)

Samples: 997342 -- mean 4.58, p95 13.68, max 25.86 points.

## Daily peak risk (Myggrisk idag) distribution (% of Sweden per category)

| Date | Mean | Median | very_low | low | moderate | high | very_high |
|---|---|---|---|---|---|---|---|
| 2026-08-04 | 21.4 | 22.9 | 37.7% | 62.2% | 0.1% | 0.0% | 0.0% |
| 2026-08-05 | 21.4 | 21.5 | 43.7% | 56.0% | 0.3% | 0.0% | 0.0% |
| 2026-08-06 | 17.6 | 18.1 | 61.9% | 38.1% | 0.0% | 0.0% | 0.0% |
| 2026-08-07 | 18.3 | 17.3 | 65.1% | 34.9% | 0.0% | 0.0% | 0.0% |
| 2026-08-08 | 24.2 | 25.5 | 23.9% | 76.1% | 0.0% | 0.0% | 0.0% |
| 2026-08-09 | 20.0 | 20.2 | 48.0% | 52.0% | 0.0% | 0.0% | 0.0% |
| 2026-08-10 | 15.0 | 15.4 | 93.3% | 6.7% | 0.0% | 0.0% | 0.0% |

## Abundance (Myggläge) distribution (% of Sweden per category)

| Date | Mean | very_low | low | moderate | high | very_high |
|---|---|---|---|---|---|---|
| 2026-08-04 | 31.8 | 24.0% | 55.0% | 20.9% | 0.1% | 0.0% |
| 2026-08-05 | 30.4 | 29.3% | 50.9% | 19.7% | 0.1% | 0.0% |
| 2026-08-06 | 32.8 | 21.8% | 52.5% | 25.6% | 0.1% | 0.0% |
| 2026-08-07 | 36.1 | 14.5% | 36.4% | 48.8% | 0.4% | 0.0% |
| 2026-08-08 | 36.2 | 14.2% | 36.5% | 48.7% | 0.6% | 0.0% |
| 2026-08-09 | 36.7 | 13.2% | 34.7% | 51.2% | 0.9% | 0.0% |
| 2026-08-10 | 38.6 | 10.4% | 25.9% | 60.7% | 3.0% | 0.0% |

## Regional mean risk by day

| Date | Gotaland | Norrland | Svealand |
|---|---|---|---|
| 2026-08-04 | 27.8 | 15.3 | 25.1 |
| 2026-08-05 | 28.5 | 14.7 | 25.7 |
| 2026-08-06 | 19.4 | 14.9 | 20.7 |
| 2026-08-07 | 22.2 | 14.3 | 21.1 |
| 2026-08-08 | 24.3 | 22.9 | 26.7 |
| 2026-08-09 | 22.6 | 17.9 | 20.6 |
| 2026-08-10 | 17.6 | 13.2 | 15.2 |

## Hourly national mean risk (diurnal variation, next ~48h)

| Hour (UTC) | Mean risk |
|---|---|
| 2026-08-04T10 | 12.0 |
| 2026-08-04T11 | 11.8 |
| 2026-08-04T12 | 11.9 |
| 2026-08-04T13 | 12.2 |
| 2026-08-04T14 | 12.7 |
| 2026-08-04T15 | 13.8 |
| 2026-08-04T16 | 15.6 |
| 2026-08-04T17 | 18.4 |
| 2026-08-04T18 | 20.9 |
| 2026-08-04T19 | 21.2 |
| 2026-08-04T20 | 20.5 |
| 2026-08-04T21 | 18.4 |
| 2026-08-04T22 | 15.5 |
| 2026-08-04T23 | 13.4 |
| 2026-08-05T00 | 13.0 |
| 2026-08-05T01 | 14.0 |
| 2026-08-05T02 | 15.0 |
| 2026-08-05T03 | 15.4 |
| 2026-08-05T04 | 15.0 |
| 2026-08-05T05 | 13.9 |
| 2026-08-05T06 | 12.7 |
| 2026-08-05T07 | 11.8 |
| 2026-08-05T08 | 11.4 |
| 2026-08-05T09 | 11.3 |
| 2026-08-05T10 | 11.3 |
| 2026-08-05T11 | 11.4 |
| 2026-08-05T12 | 11.6 |
| 2026-08-05T13 | 12.0 |
| 2026-08-05T14 | 12.8 |
| 2026-08-05T15 | 14.3 |
| 2026-08-05T16 | 16.6 |
| 2026-08-05T17 | 19.4 |
| 2026-08-05T18 | 21.2 |
| 2026-08-05T19 | 21.1 |
| 2026-08-05T20 | 20.5 |
| 2026-08-05T21 | 18.4 |
| 2026-08-05T22 | 15.6 |
| 2026-08-05T23 | 13.6 |
| 2026-08-06T00 | 13.4 |
| 2026-08-06T01 | 14.8 |
| 2026-08-06T02 | 16.1 |
| 2026-08-06T03 | 16.8 |
| 2026-08-06T04 | 16.3 |
| 2026-08-06T05 | 14.6 |
| 2026-08-06T06 | 13.0 |
| 2026-08-06T07 | 12.0 |
| 2026-08-06T08 | 11.5 |
| 2026-08-06T09 | 11.4 |
| 2026-08-06T10 | 11.4 |
