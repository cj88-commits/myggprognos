"""One-off validation of the corrected full-grid production run (run #2).

Reuses the categorize() pattern fixed during the previous validation pass
(risk_bounds must NOT have a leading 0 prepended a second time).
"""
import gzip
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "data" / "generated" / "latest"


def load_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def categorize(score, bounds, labels):
    cat = labels[0]
    for bound, label in zip(bounds, labels[1:]):
        if score >= bound:
            cat = label
    return cat


ABUNDANCE_LABELS = ["very_low", "low", "moderate", "high", "very_high"]
RISK_LABELS = ["very_low", "low", "moderate", "high", "very_high"]

manifest = json.loads((LATEST / "manifest.json").read_text(encoding="utf-8"))
abundance_bounds = [5.0, 12.0, 20.0, 30.0]
risk_bounds = [4, 8, 14, 22]

cells = load_gz(LATEST / "cells.json.gz")
print(f"cell_count manifest={manifest['cell_count']} cells.json.gz={len(cells)}")

today = manifest["daily_files"][0]
daily = load_gz(LATEST / today)
print(f"daily records: {len(daily)} (file: {today})")

# Build lookup from cell_id -> static features
cell_by_id = {c["cell_id"]: c for c in cells}

abundance_counts = {l: 0 for l in ABUNDANCE_LABELS}
risk_counts = {l: 0 for l in RISK_LABELS}
nan_count = 0
invalid_count = 0
scores = []
records = []

for rec in daily:
    pop = rec.get("population_potential")
    risk = rec.get("risk")
    if pop is None or risk is None or (isinstance(pop, float) and math.isnan(pop)) or (isinstance(risk, float) and math.isnan(risk)):
        nan_count += 1
        continue
    if not (0 <= pop <= 100) or not (0 <= risk <= 100):
        invalid_count += 1
        continue
    a_cat = categorize(pop, abundance_bounds, ABUNDANCE_LABELS)
    r_cat = categorize(risk, risk_bounds, RISK_LABELS)
    abundance_counts[a_cat] += 1
    risk_counts[r_cat] += 1
    scores.append((rec["cell_id"], pop, risk, rec.get("habitat_capacity"), rec.get("mosquito_pressure")))
    records.append(rec)

n = len(scores)
print(f"\nvalid records: {n}, nan_or_missing: {nan_count}, out_of_range: {invalid_count}")

print("\n=== Myggläge (abundance / population_potential) distribution ===")
for l in ABUNDANCE_LABELS:
    c = abundance_counts[l]
    print(f"  {l:12s} {c:6d}  {100*c/n:5.1f}%")

print("\n=== Myggrisk (final_risk) distribution ===")
for l in RISK_LABELS:
    c = risk_counts[l]
    print(f"  {l:12s} {c:6d}  {100*c/n:5.1f}%")

pop_vals = sorted(s[1] for s in scores)
risk_vals = sorted(s[2] for s in scores)
print(f"\npopulation_potential: min={pop_vals[0]:.2f} p50={pop_vals[n//2]:.2f} p90={pop_vals[int(n*0.9)]:.2f} max={pop_vals[-1]:.2f}")
print(f"final_risk:           min={risk_vals[0]:.2f} p50={risk_vals[n//2]:.2f} p90={risk_vals[int(n*0.9)]:.2f} max={risk_vals[-1]:.2f}")

# Top/bottom 100 by population_potential
by_pop = sorted(scores, key=lambda s: -s[1])
print("\n=== Top 10 by population_potential (of top 100 computed) ===")
for cid, pop, risk, hab, pres in by_pop[:10]:
    cell = cell_by_id.get(cid, {})
    print(f"  {cid} pop={pop:.1f} risk={risk:.1f} habitat={hab:.1f} pressure={pres:.1f} lat={cell.get('latitude'):.2f} lon={cell.get('longitude'):.2f}")

print("\n=== Bottom 10 by population_potential (of bottom 100 computed) ===")
for cid, pop, risk, hab, pres in by_pop[-10:]:
    cell = cell_by_id.get(cid, {})
    print(f"  {cid} pop={pop:.1f} risk={risk:.1f} habitat={hab:.1f} pressure={pres:.1f} lat={cell.get('latitude'):.2f} lon={cell.get('longitude'):.2f}")

# Check: extreme habitat with negligible pressure never reaches very_high
extreme_habitat_bad = [s for s in scores if s[3] is not None and s[3] > 50 and s[4] is not None and s[4] < 1.0 and s[1] >= 30.0]
print(f"\nExtreme-habitat(>50)+negligible-pressure(<1.0) reaching very_high(>=30): {len(extreme_habitat_bad)}")
for cid, pop, risk, hab, pres in extreme_habitat_bad[:10]:
    print(f"  {cid} pop={pop:.1f} habitat={hab:.1f} pressure={pres:.1f}")

# Named locations
locations = {
    "Stockholm centrum": (59.3293, 18.0686),
    "Dalarna skog (Alvdalen)": (61.2333, 14.05),
    "Lower Dalalven (Osterfarnebo)": (60.5167, 16.85),
    "Norrland wetland (Muddus)": (66.9, 20.6),
    "Northern mountain (Sarek)": (67.55, 17.75),
    "Lake margin (Vanern strand)": (58.9, 13.35),
    "Lake open water (Vanern)": (58.9, 13.15),
}


def nearest(lat, lon):
    best = None
    best_d = None
    for rec in records:
        cell = cell_by_id.get(rec["cell_id"])
        if not cell:
            continue
        d = (cell["latitude"] - lat) ** 2 + (cell["longitude"] - lon) ** 2
        if best_d is None or d < best_d:
            best_d = d
            best = rec
    return best


print("\n=== Named location sanity checks ===")
for name, (lat, lon) in locations.items():
    rec = nearest(lat, lon)
    if rec is None:
        print(f"  {name}: NOT FOUND")
        continue
    cell = cell_by_id.get(rec["cell_id"], {})
    pop = rec["population_potential"]
    risk = rec["risk"]
    a_cat = categorize(pop, abundance_bounds, ABUNDANCE_LABELS)
    r_cat = categorize(risk, risk_bounds, RISK_LABELS)
    print(f"  {name:32s} pop={pop:5.1f} ({a_cat:10s}) risk={risk:5.1f} ({r_cat:10s}) habitat={rec.get('habitat_capacity',0):.1f} pressure={rec.get('mosquito_pressure',0):.1f} major_lake={cell.get('major_lake_interior')}")

print("\nDONE")
