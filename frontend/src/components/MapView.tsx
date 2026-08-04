import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { GeoJSONSource, Map as MaplibreMap, Marker, Popup } from "maplibre-gl";
import { fetchJsonGz } from "../lib/fetchJsonGz";
import { useI18n } from "../i18n";
import { abundanceColorStops, DATA_QUALITY_CATEGORIES, DEFAULT_ABUNDANCE_THRESHOLDS, RISK_COLOR_STOPS } from "../lib/riskModel";
import type { CellRecord, LayerKey } from "../types/forecast";

const SWEDEN_CENTER: [number, number] = [17.5, 62.5];
const SWEDEN_INITIAL_ZOOM = 4.2;

// CARTO's free, keyless "Positron" style: a neutral light basemap (roads,
// place labels, muted land/water) meant specifically for data overlays.
// MapLibre's own demotiles.maplibre.org style was used previously, but its
// "countries" layer fills each country with a distinct, fully-saturated
// flat colour (Sweden purple, Norway green, Finland orange, ...) for demo
// purposes -- easily mistaken for graded risk data. Positron has no such
// per-country fills. Override via VITE_MAP_STYLE_URL for a richer style
// (e.g. MapTiler, Stadia Maps) if desired; see README.
const DEFAULT_STYLE_URL = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

// Smooth 0-100 green -> yellow-green -> yellow -> orange -> red ramp (see
// lib/riskModel.ts::RISK_COLOR_STOPS, shared with any other continuous risk
// display), rather than the old 0-10 banded scale.
const RISK_COLOR_EXPRESSION: maplibregl.ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["get", "value"],
  ...RISK_COLOR_STOPS.flatMap((stop) => [stop.value, stop.color] as [number, string]),
];

// Matches riskModel.ts::DATA_QUALITY_CATEGORIES (low/limited/good/very_good)
// so the map, legend and location panel all agree on what "good data
// quality" looks like -- this used to be its own independent 4-stop ramp.
const CONFIDENCE_COLOR_EXPRESSION: maplibregl.ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["get", "value"],
  ...DATA_QUALITY_CATEGORIES.flatMap((c) => [c.min, c.color] as [number, string]),
];

// Myggläge (population_potential) needed its own ramp -- reusing the
// standard 0/20/40/60/80/100 risk stops meant the map could visually never
// reach orange/red, since real abundance tops out well short of 100 (see
// docs/model-audit-after.md). Built per-render from manifest.thresholds
// (falls back to DEFAULT_ABUNDANCE_THRESHOLDS for an older manifest) rather
// than a fixed module-level constant, since the edges are backend-owned.
function colorExpressionForLayer(
  layer: LayerKey,
  abundanceThresholds: number[] | undefined
): maplibregl.ExpressionSpecification {
  if (layer === "confidence") return CONFIDENCE_COLOR_EXPRESSION;
  if (layer === "population_potential") {
    const stops = abundanceColorStops(abundanceThresholds ?? DEFAULT_ABUNDANCE_THRESHOLDS);
    return ["interpolate", ["linear"], ["get", "value"], ...stops.flatMap((s) => [s.value, s.color] as [number, string])];
  }
  return RISK_COLOR_EXPRESSION;
}

// Precomputed once by scripts/prepare_cell_geometry.py: each grid cell's
// actual ~5km square, clipped to (Sweden's real land shape minus its
// lakes) using the true, detailed boundary/lake polygons. This is
// deliberately NOT a heatmap or a fixed-size shape approximated with blur
// -- every rendered polygon *is* real land, by construction, so there is
// no coastline to "reach" and no water to accidentally paint over. Two
// earlier approaches were tried and rejected: tiled squares with no water
// awareness (coloured lakes, blocky look) and a blurred heatmap masked by
// the basemap's water layer (still bled onto the sea/lakes wherever the
// blur radius outran the mask, and never looked like literal coloured
// land in the first place -- the actual ask).
const CELL_GEOMETRY_URL = "data/static/cell_geometry.json.gz";

interface CellGeometryEntry {
  cell_id: string;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
}

function buildFeatureCollection(
  cellGeometry: CellGeometryEntry[],
  valuesByCellId: Record<string, number> | null
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: cellGeometry.map((entry) => ({
      type: "Feature",
      geometry: entry.geometry,
      properties: {
        cell_id: entry.cell_id,
        // -1 is a "no data" sentinel (kept numeric so it works inside
        // interpolate/case expressions, which don't type-check against
        // null literals).
        value: valuesByCellId?.[entry.cell_id] ?? -1,
      },
    })),
  };
}

export interface MapViewProps {
  cells: CellRecord[];
  valuesByCellId: Record<string, number> | null;
  layer: LayerKey;
  selectedLat: number;
  selectedLon: number;
  selectedCellId: string | null;
  abundanceThresholds?: number[];
  onSelectLocation: (lat: number, lon: number) => void;
  userLocation: { lat: number; lon: number } | null;
  reportMarkers?: { lat: number; lon: number; severity: number }[];
  // Fired only when a click hits no grid cell (open sea, outside coverage,
  // gaps between cells) -- distinct from a normal cell selection. Used to
  // collapse the mobile bottom sheet so the map is unobstructed (item 5:
  // "tapping empty map should collapse the sheet"); a tap that DOES select
  // a forecast cell should keep/expand the sheet, since that's the whole
  // point of tapping it.
  onBackgroundTap?: () => void;
}

const EMPTY_FEATURE_COLLECTION: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export function MapView({
  valuesByCellId,
  layer,
  selectedLat,
  selectedLon,
  selectedCellId,
  abundanceThresholds,
  onSelectLocation,
  userLocation,
  reportMarkers = [],
  onBackgroundTap,
}: MapViewProps) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const readyRef = useRef(false);
  const selectedMarkerRef = useRef<Marker | null>(null);
  const userMarkerRef = useRef<Marker | null>(null);
  const reportMarkersRef = useRef<Marker[]>([]);
  const hoveredIdRef = useRef<string | number | null>(null);
  const [cellGeometry, setCellGeometry] = useState<CellGeometryEntry[]>([]);

  // Static (doesn't change per forecast run) -- fetched once, independent
  // of the cells/values props.
  useEffect(() => {
    let cancelled = false;
    fetchJsonGz<CellGeometryEntry[]>(CELL_GEOMETRY_URL)
      .then((data) => {
        if (!cancelled) setCellGeometry(data);
      })
      .catch(() => {
        // Non-fatal: the map still functions (basemap + selection), just
        // without the risk colouring, and the location panel's own data
        // fetches are unaffected.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Rebuilding an ~18k-feature collection on every render (rather than only
  // when geometry/values actually change) would be wasteful GC churn at
  // full-Sweden scale.
  const featureCollection = useMemo(
    () => buildFeatureCollection(cellGeometry, valuesByCellId),
    [cellGeometry, valuesByCellId]
  );

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const styleUrl = (import.meta.env.VITE_MAP_STYLE_URL as string | undefined) || DEFAULT_STYLE_URL;

    // Attribution comes from the style's own vector source (its tilejson
    // carries "© OpenStreetMap contributors © CARTO"), picked up
    // automatically by AttributionControl. `compact: true` gets us the
    // small round "i" icon button (only rendered at all when the control
    // has the "maplibregl-compact" class -- confirmed in maplibre-gl's own
    // CSS) -- but MapLibre's *own* show/hide bookkeeping for the attribution
    // text (an "open" attribute + "maplibregl-compact-show" class, toggled
    // on a schedule tied to map "resize"/"idle" events) turned out
    // unreliable to force into starting collapsed from outside: attempts to
    // override it raced with MapLibre's own updates and could leave the
    // control permanently empty ("maplibregl-attrib-empty") depending on
    // timing (confirmed live).
    //
    // So we leave MapLibre's own open/compact-show bookkeeping alone
    // entirely and layer independent, !important-forced visibility on top
    // via our own class, which its code never touches -- see
    // "maplibregl-ctrl-attrib" rules in global.css.
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: styleUrl,
      center: SWEDEN_CENTER,
      zoom: SWEDEN_INITIAL_ZOOM,
      // Omitting this auto-adds MapLibre's own default AttributionControl
      // *in addition to* the explicit compact one below -- two separate
      // controls, which is what was actually causing every odd visibility
      // symptom while diagnosing this (confirmed live: two
      // ".maplibregl-ctrl-attrib" elements in the DOM).
      attributionControl: false,
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true }));
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      // Wired here (not right after construction) so the control's DOM is
      // guaranteed to exist -- AttributionControl is added internally by
      // the Map constructor, but not necessarily synchronously enough to
      // querySelector for it immediately after `new maplibregl.Map(...)`.
      const attribButton = map.getContainer().querySelector(".maplibregl-ctrl-attrib-button");
      attribButton?.addEventListener("click", (event) => {
        event.preventDefault(); // don't fight MapLibre's own "open" bookkeeping
        attribButton.closest(".maplibregl-ctrl-attrib")?.classList.toggle("myggprognos-attrib-expanded");
      });

      // promoteId lets MapLibre use each feature's own cell_id as its
      // feature-state id (cell_ids are unique strings) instead of requiring
      // a separate numeric `id` on every one of the ~18-23k features --
      // feature-state is how the hover highlight below is driven without
      // rebuilding/restyling the whole layer on every mousemove.
      map.addSource("cells", { type: "geojson", data: featureCollection, promoteId: "cell_id" });
      map.addSource("selected-cell", { type: "geojson", data: EMPTY_FEATURE_COLLECTION });

      // Insert below water so any real map labels/road lines that sit on
      // top of water (rare, but the style declares them later) still
      // render correctly -- our polygons never actually overlap water
      // themselves (that's the whole point of the precomputed geometry),
      // this is purely about staying under roads/place labels for
      // legibility, same as any other data overlay. Falls back to adding
      // on top if the style doesn't have this layer (e.g. a custom
      // VITE_MAP_STYLE_URL override) rather than throwing.
      const beforeId = map.getLayer("water") ? "water" : undefined;
      map.addLayer(
        {
          id: "cells-heat",
          type: "fill",
          source: "cells",
          paint: {
            "fill-color": colorExpressionForLayer(layer, abundanceThresholds),
            "fill-opacity": [
              "case",
              ["<", ["get", "value"], 0],
              0.15,
              ["boolean", ["feature-state", "hover"], false],
              0.95,
              0.8,
            ],
          },
        },
        beforeId
      );

      // Hovered-cell outline (item 8: "hover feedback") -- width is 0 for
      // every feature except whichever one currently has feature-state
      // hover=true, so this is a single always-present layer rather than
      // one added/removed per mouse move.
      map.addLayer(
        {
          id: "cells-hover-outline",
          type: "line",
          source: "cells",
          paint: {
            "line-color": "#ffffff",
            "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 2, 0],
            "line-opacity": 0.9,
          },
        },
        beforeId
      );

      // Selected-cell outline (item 8: "the selected forecast cell should
      // be obvious") -- the exact ~5km polygon the shown numbers describe,
      // not just a point marker at the click location.
      map.addLayer({
        id: "selected-cell-outline",
        type: "line",
        source: "selected-cell",
        paint: {
          "line-color": "#2b6fd6",
          "line-width": 3,
          "line-opacity": 0.95,
        },
      });

      map.on("click", "cells-heat", (e) => {
        const feature = e.features?.[0];
        if (feature) {
          onSelectLocation(e.lngLat.lat, e.lngLat.lng);
        }
      });
      map.on("click", (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: ["cells-heat"] });
        if (features.length === 0) {
          onSelectLocation(e.lngLat.lat, e.lngLat.lng);
          onBackgroundTap?.();
        }
      });
      map.on("mousemove", "cells-heat", (e) => {
        map.getCanvas().style.cursor = "pointer";
        const feature = e.features?.[0];
        const nextId = feature?.id ?? null;
        if (hoveredIdRef.current === nextId) return;
        if (hoveredIdRef.current !== null) {
          map.setFeatureState({ source: "cells", id: hoveredIdRef.current }, { hover: false });
        }
        if (nextId !== null) {
          map.setFeatureState({ source: "cells", id: nextId }, { hover: true });
        }
        hoveredIdRef.current = nextId;
      });
      map.on("mouseleave", "cells-heat", () => {
        map.getCanvas().style.cursor = "";
        if (hoveredIdRef.current !== null) {
          map.setFeatureState({ source: "cells", id: hoveredIdRef.current }, { hover: false });
          hoveredIdRef.current = null;
        }
      });

      readyRef.current = true;
    });

    return () => {
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update layer data + colour expression when geometry/values/layer change.
  //
  // The real cell geometry/values and the map style (CARTO style.json +
  // sprite + glyphs + vector tiles) load in parallel with no guaranteed
  // order. If this effect runs *before* the map's "load" event -- e.g. the
  // style takes longer than the data fetch, which is common at full-Sweden
  // scale (~18k features) -- it used to bail out via the `!readyRef.current`
  // guard and never retry, permanently leaving the source's initial empty
  // FeatureCollection (captured at mount, before data existed) on screen.
  // Deferring the same update via `map.once` when not yet ready guarantees
  // it's applied exactly once "load" fires.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const applyUpdate = () => {
      const source = map.getSource("cells") as GeoJSONSource | undefined;
      if (source) {
        source.setData(featureCollection);
      }
      if (map.getLayer("cells-heat")) {
        map.setPaintProperty("cells-heat", "fill-color", colorExpressionForLayer(layer, abundanceThresholds));
      }
    };
    if (readyRef.current) {
      applyUpdate();
    } else {
      map.once("load", applyUpdate);
    }
  }, [featureCollection, layer, abundanceThresholds]);

  // Selected-cell outline: the single real grid-cell polygon the panel's
  // numbers actually describe (item 8), redrawn on a dedicated 1-feature
  // source whenever the selection or geometry changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const entry = selectedCellId ? cellGeometry.find((c) => c.cell_id === selectedCellId) : undefined;
    const data: GeoJSON.FeatureCollection = entry
      ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: entry.geometry, properties: {} }] }
      : EMPTY_FEATURE_COLLECTION;
    const applyUpdate = () => {
      const source = map.getSource("selected-cell") as GeoJSONSource | undefined;
      source?.setData(data);
    };
    if (readyRef.current) applyUpdate();
    else map.once("load", applyUpdate);
  }, [selectedCellId, cellGeometry]);

  // Selected-location marker + fly-to. The marker also plays a brief "ping"
  // (item 8: visible tap/click feedback, useful on mobile where there's no
  // hover state to rely on) -- a transient ring appended and removed around
  // the persistent marker dot rather than replaying a CSS animation on the
  // dot itself, so the marker's own box-shadow/position never flickers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    function playPing(dot: HTMLElement) {
      const ring = document.createElement("div");
      ring.className = "marker-ping-ring";
      dot.appendChild(ring);
      window.setTimeout(() => ring.remove(), 700);
    }

    if (!selectedMarkerRef.current) {
      const el = document.createElement("div");
      el.className = "marker-dot";
      el.style.width = "16px";
      el.style.height = "16px";
      el.style.borderRadius = "50%";
      el.style.border = "3px solid white";
      el.style.background = "#2b6fd6";
      el.style.boxShadow = "0 0 0 2px rgba(0,0,0,0.35)";
      el.style.position = "relative";
      selectedMarkerRef.current = new maplibregl.Marker({ element: el }).setLngLat([selectedLon, selectedLat]);
      if (readyRef.current) selectedMarkerRef.current.addTo(map);
      else map.once("load", () => selectedMarkerRef.current?.addTo(map));
      playPing(el);
    } else {
      selectedMarkerRef.current.setLngLat([selectedLon, selectedLat]);
      playPing(selectedMarkerRef.current.getElement());
    }
  }, [selectedLat, selectedLon]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const fly = () => map.flyTo({ center: [selectedLon, selectedLat], zoom: Math.max(map.getZoom(), 8), speed: 1.2 });
    if (readyRef.current) fly();
    else map.once("load", fly);
    // Only fly when the selection changes, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLat, selectedLon]);

  // User location marker.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (userMarkerRef.current) {
      userMarkerRef.current.remove();
      userMarkerRef.current = null;
    }
    if (userLocation) {
      const el = document.createElement("div");
      el.style.width = "14px";
      el.style.height = "14px";
      el.style.borderRadius = "50%";
      el.style.background = "#4fae6b";
      el.style.border = "2px solid white";
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([userLocation.lon, userLocation.lat])
        .setPopup(new Popup({ closeButton: false }).setText(t("search.myLocation")));
      if (readyRef.current) marker.addTo(map);
      else map.once("load", () => marker.addTo(map));
      userMarkerRef.current = marker;
    }
  }, [userLocation, t]);

  // Report markers (clustered visually via simple offset dots; a full
  // clustering implementation would use a GeoJSON source with
  // cluster:true, kept simple here since report volume is expected to be
  // low in the MVP).
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    reportMarkersRef.current.forEach((m) => m.remove());
    reportMarkersRef.current = [];
    reportMarkers.forEach((report) => {
      const el = document.createElement("div");
      el.style.width = "10px";
      el.style.height = "10px";
      el.style.borderRadius = "50%";
      el.style.background = "#e8c14a";
      el.style.border = "1px solid rgba(0,0,0,0.4)";
      const marker = new maplibregl.Marker({ element: el }).setLngLat([report.lon, report.lat]);
      if (readyRef.current) marker.addTo(map);
      else map.once("load", () => marker.addTo(map));
      reportMarkersRef.current.push(marker);
    });
  }, [reportMarkers]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} role="application" aria-label={t("map.ariaLabel")} />;
}
