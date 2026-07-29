import { useEffect, useMemo, useRef } from "react";
import maplibregl, { GeoJSONSource, Map as MaplibreMap, Marker, Popup } from "maplibre-gl";
import { useI18n } from "../i18n";
import { RISK_COLOR_STOPS } from "../lib/riskModel";
import type { CellRecord, LayerKey } from "../types/forecast";

const SWEDEN_CENTER: [number, number] = [17.5, 62.5];
const SWEDEN_INITIAL_ZOOM = 4.2;

// MapLibre's free demo style requires no API key, which keeps the MVP
// operable at zero cost. It is intentionally minimal -- production
// deployments may want to swap in a richer free-tier style (e.g. from
// MapTiler or Stadia Maps) via VITE_MAP_STYLE_URL; see README.
const DEFAULT_STYLE_URL = "https://demotiles.maplibre.org/style.json";

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
        type: "circle",
        source: "cells",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 4, 8, 10, 12, 18],
          "circle-color": layer === "confidence" ? CONFIDENCE_COLOR_EXPRESSION : RISK_COLOR_EXPRESSION,
          "circle-opacity": ["case", ["<", ["get", "value"], 0], 0.12, 0.85],
          "circle-stroke-width": 0.5,
          "circle-stroke-color": "rgba(0,0,0,0.25)",
        },
      });

      map.on("click", "cells-heat", (e) => {
        const feature = e.features?.[0];
        if (feature && feature.geometry.type === "Point") {
          const [lon, lat] = feature.geometry.coordinates as [number, number];
          onSelectLocation(lat, lon);
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

  // Update layer data + colour expression when cells/values/layer change.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const source = map.getSource("cells") as GeoJSONSource | undefined;
    if (source) {
      source.setData(featureCollection);
    }
    if (map.getLayer("cells-heat")) {
      map.setPaintProperty(
        "cells-heat",
        "circle-color",
        layer === "confidence" ? CONFIDENCE_COLOR_EXPRESSION : RISK_COLOR_EXPRESSION
      );
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
