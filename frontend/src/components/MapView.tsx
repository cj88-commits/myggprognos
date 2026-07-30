import { useEffect, useMemo, useRef } from "react";
import maplibregl, { GeoJSONSource, Map as MaplibreMap, Marker, Popup } from "maplibre-gl";
import { useI18n } from "../i18n";
import { RISK_COLOR_STOPS } from "../lib/riskModel";
import type { CellRecord, LayerKey } from "../types/forecast";

const SWEDEN_CENTER: [number, number] = [17.5, 62.5];
const SWEDEN_INITIAL_ZOOM = 4.2;

// CARTO's free, keyless "Positron" style: a neutral light basemap (roads,
// place labels, muted land/water) meant specifically for data overlays.
// MapLibre's own demotiles.maplibre.org style was used previously, but its
// "countries" layer fills each country with a distinct, fully-saturated
// flat colour (Sweden purple, Norway green, Finland orange, ...) for demo
// purposes -- easily mistaken for graded risk data, and it visually
// drowned out the sparse sample-mode risk circles entirely. Positron has
// no such per-country fills. Override via VITE_MAP_STYLE_URL for a richer
// style (e.g. MapTiler, Stadia Maps) if desired; see README.
const DEFAULT_STYLE_URL = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

// Both squares (tiled grid -- hard-edged, "Minecraft blocks") and
// individually-visible blurred circles ("weird", separate blobs) were
// tried and rejected live: the ask is a genuinely continuous coloured
// *area*, not any per-cell shape. MapLibre's "heatmap" layer type renders
// from the same point data as a single blended density surface with no
// per-feature outline at all, which is the right primitive for that.
//
// heatmap-color is keyed on the synthetic ["heatmap-density"] axis (0-1,
// relative local concentration of nearby weighted points), not the raw
// "value" property directly -- that's a hard requirement of the paint
// property, not a stylistic choice.
const RISK_HEATMAP_COLOR_EXPRESSION: maplibregl.ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["heatmap-density"],
  0, "rgba(0,0,0,0)",
  ...RISK_COLOR_STOPS.flatMap((stop) => [Math.max(stop.value / 100, 0.001), stop.color] as [number, string]),
];

const CONFIDENCE_HEATMAP_COLOR_EXPRESSION: maplibregl.ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["heatmap-density"],
  0, "rgba(0,0,0,0)",
  0.001, "#d9432e",
  0.4, "#f2c94c",
  0.7, "#2e8b4f",
  1, "#1c4a32",
];

// heatmap-weight: 0-100 risk -> 0-1 density contribution. -1 (no-data
// sentinel) contributes nothing (stays transparent, correctly showing
// "no data" rather than fabricating a value). A real value of 0 still
// gets a small non-zero floor (0.25, not 0) so a genuinely-covered
// very-low-risk area reads as pale green, not gaps of transparency --
// otherwise the (currently nationwide-low-risk) live data would render as
// almost nothing at all.
const HEATMAP_WEIGHT_EXPRESSION: maplibregl.ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["get", "value"],
  -1, 0,
  0, 0.25,
  100, 1,
];

// Must match forecast/src/config.py::GRID_RESOLUTION_KM -- sized so each
// point's blend radius comfortably overlaps its neighbours at the grid's
// real ~5km spacing, using the standard Web Mercator ground-resolution
// formula to keep that overlap consistent at every zoom level (a fixed
// pixel radius doesn't scale with zoom, and was the root cause of the very
// first version of this layer showing gaps between dots).
//
// Tile size is 512px, not the classic 256px XYZ raster convention -- that's
// MapLibre GL's own default for vector styles, confirmed against this map
// instance via map.project() on two known-adjacent grid points.
const GRID_CELL_SIZE_KM = 5.0;
const CELL_OVERLAP_FACTOR = 2.2;
const SWEDEN_BBOX_MID_LAT_DEG = (55.2 + 69.1) / 2;
const EARTH_CIRCUMFERENCE_M = 40075016.686;
const TILE_SIZE_PX = 512;

function metersPerPixelAtZoom(zoom: number, latRad: number): number {
  return (EARTH_CIRCUMFERENCE_M * Math.cos(latRad)) / (TILE_SIZE_PX * Math.pow(2, zoom));
}

function heatmapRadiusPxAtZoom(zoom: number): number {
  const latRad = (SWEDEN_BBOX_MID_LAT_DEG * Math.PI) / 180;
  const metersPerPixel = metersPerPixelAtZoom(zoom, latRad);
  const halfSpacingM = (GRID_CELL_SIZE_KM * 1000) / 2;
  return (halfSpacingM * CELL_OVERLAP_FACTOR) / metersPerPixel;
}

const HEATMAP_RADIUS_ZOOM_STOPS = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
const HEATMAP_RADIUS_EXPRESSION: maplibregl.ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["zoom"],
  ...HEATMAP_RADIUS_ZOOM_STOPS.flatMap((z) => [z, heatmapRadiusPxAtZoom(z)] as [number, number]),
];

function buildFeatureCollection(
  cells: CellRecord[],
  valuesByCellId: Record<string, number> | null
): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: cells.map((cell) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [cell.longitude, cell.latitude] },
      properties: {
        cell_id: cell.cell_id,
        lat: cell.latitude,
        lon: cell.longitude,
        // -1 is a "no data" sentinel (kept numeric so it works inside
        // interpolate/case expressions, which don't type-check against
        // null literals).
        value: valuesByCellId?.[cell.cell_id] ?? -1,
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
  onSelectLocation: (lat: number, lon: number) => void;
  userLocation: { lat: number; lon: number } | null;
  reportMarkers?: { lat: number; lon: number; severity: number }[];
}

export function MapView({
  cells,
  valuesByCellId,
  layer,
  selectedLat,
  selectedLon,
  onSelectLocation,
  userLocation,
  reportMarkers = [],
}: MapViewProps) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const readyRef = useRef(false);
  const selectedMarkerRef = useRef<Marker | null>(null);
  const userMarkerRef = useRef<Marker | null>(null);
  const reportMarkersRef = useRef<Marker[]>([]);

  // Rebuilding a ~18k-feature collection on every render (rather than only
  // when cells/values actually change) would be wasteful GC churn at
  // full-Sweden scale.
  const featureCollection = useMemo(() => buildFeatureCollection(cells, valuesByCellId), [cells, valuesByCellId]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const styleUrl = (import.meta.env.VITE_MAP_STYLE_URL as string | undefined) || DEFAULT_STYLE_URL;

    // Attribution comes from the style's own vector source (its tilejson
    // carries "© OpenStreetMap contributors © CARTO"), picked up
    // automatically by the default AttributionControl -- no manual
    // attribution string needed here.
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: styleUrl,
      center: SWEDEN_CENTER,
      zoom: SWEDEN_INITIAL_ZOOM,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      map.addSource("cells", { type: "geojson", data: featureCollection });
      map.addLayer({
        id: "cells-heat",
        type: "heatmap",
        source: "cells",
        paint: {
          "heatmap-weight": HEATMAP_WEIGHT_EXPRESSION,
          "heatmap-intensity": 1,
          "heatmap-radius": HEATMAP_RADIUS_EXPRESSION,
          "heatmap-color": layer === "confidence" ? CONFIDENCE_HEATMAP_COLOR_EXPRESSION : RISK_HEATMAP_COLOR_EXPRESSION,
          "heatmap-opacity": 0.85,
        },
      });

      // A heatmap layer is a single blended density surface, not discrete
      // per-feature shapes, so there's no individual "cell" to hit-test
      // against on click -- selecting the exact clicked point and letting
      // the app's existing nearestCell() lookup resolve the closest real
      // grid cell (already how every other selection path works) is both
      // simpler and more correct than trying to query a feature here.
      map.on("click", (e) => onSelectLocation(e.lngLat.lat, e.lngLat.lng));

      readyRef.current = true;
    });

    return () => {
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update layer data + colour expression when cells/values/layer change.
  //
  // The real cells/daily/hourly data and the map style (CARTO style.json +
  // sprite + glyphs + vector tiles) load in parallel with no guaranteed
  // order. If this effect runs *before* the map's "load" event -- e.g. the
  // style takes longer than the data fetch, which is common at full-Sweden
  // scale (~18k features) -- it used to bail out via the `!readyRef.current`
  // guard and never retry, permanently leaving the source's initial empty
  // FeatureCollection (captured at mount, before data existed) on screen:
  // the map would render with zero visible risk circles even though every
  // fetch had actually succeeded. Deferring the same update via `map.once`
  // when not yet ready guarantees it's applied exactly once "load" fires.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const applyUpdate = () => {
      const source = map.getSource("cells") as GeoJSONSource | undefined;
      if (source) {
        source.setData(featureCollection);
      }
      if (map.getLayer("cells-heat")) {
        map.setPaintProperty(
          "cells-heat",
          "heatmap-color",
          layer === "confidence" ? CONFIDENCE_HEATMAP_COLOR_EXPRESSION : RISK_HEATMAP_COLOR_EXPRESSION
        );
      }
    };
    if (readyRef.current) {
      applyUpdate();
    } else {
      map.once("load", applyUpdate);
    }
  }, [featureCollection, layer]);

  // Selected-location marker + fly-to.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (!selectedMarkerRef.current) {
      const el = document.createElement("div");
      el.style.width = "16px";
      el.style.height = "16px";
      el.style.borderRadius = "50%";
      el.style.border = "3px solid white";
      el.style.background = "#2b6fd6";
      el.style.boxShadow = "0 0 0 2px rgba(0,0,0,0.35)";
      selectedMarkerRef.current = new maplibregl.Marker({ element: el }).setLngLat([selectedLon, selectedLat]);
      if (readyRef.current) selectedMarkerRef.current.addTo(map);
      else map.once("load", () => selectedMarkerRef.current?.addTo(map));
    } else {
      selectedMarkerRef.current.setLngLat([selectedLon, selectedLat]);
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
