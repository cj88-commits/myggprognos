# Production static-feature audit

**Placeholder cells: 0 of 23194 (0.0%)**

- Cells in current grid: 23194
- Entries found in cell_features.json: 23194
- Missing from cell_features.json (would placeholder-fallback at run time): 0
- Recorded as placeholder inside cell_features.json itself: 0
- Real GIS-derived data: 23194 of 23194

## Raster source tile presence

- forest_fraction / wetland_fraction / urban_fraction / water_fraction / distance_to_water_km: worldcover: present, nmd: present
- elevation_m / slope_deg: dem: present

## What this does NOT check

- Per-feature provenance: a cell_features.json entry is either fully real or fully placeholder (see static_features.py::StaticFeatures.is_placeholder) -- there is no record of e.g. "forest_fraction real, elevation_m placeholder" for a single cell.
- Raster tile *coverage gaps within* a present tile directory (e.g. NMD's north-of-62N rollout, see static_features.py module docstring) -- only directory/file presence is checked here, not per-cell raster hit/miss inside compute_static_features_from_rasters.
