import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { GeoJSONSource, Map as MaplibreMap, Marker, Popup } from "maplibre-gl";
import { fetchJsonGz } from "../lib/fetchJsonGz";
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

const CONFIDENCE_COLOR_EXPRESSION: maplibregl.ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["get", "value"],
  0, "#d9432e",
  40, "#f2c94c",
  70, "#2e8b4f",
  100, "#1c4a32",
];

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
  onSelectLocation: (lat: number, lon: number) => void;
  userLocation: { lat: number; lon: number } | null;
  reportMarkers?: { lat: number; lon: number; severity: number }[];
}

export function MapView({
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
            "fill-color": layer === "confidence" ? CONFIDENCE_COLOR_EXPRESSION : RISK_COLOR_EXPRESSION,
            "fill-opacity": ["case", ["<", ["get", "value"], 0], 0.15, 0.8],
          },
        },
        beforeId
      );

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
        }
      });
      map.on("mouseenter", "cells-heat", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "cells-heat", () => (map.getCanvas().style.cursor = ""));

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
        map.setPaintProperty(
          "cells-heat",
          "fill-color",
          layer === "confidence" ? CONFIDENCE_COLOR_EXPRESSION : RISK_COLOR_EXPRESSION
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
