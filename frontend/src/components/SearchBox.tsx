import { useEffect, useRef, useState } from "react";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useI18n } from "../i18n";
import type { PlaceRecord } from "../types/forecast";

interface SearchResult {
  name: string;
  latitude: number;
  longitude: number;
  source: "local" | "osm";
}

const MIN_QUERY_LENGTH = 2;
const RESULT_LIMIT = 8;
const nominatimCache = new Map<string, SearchResult[]>();

async function searchNominatim(query: string, signal: AbortSignal): Promise<SearchResult[]> {
  const cacheKey = query.toLowerCase();
  if (nominatimCache.has(cacheKey)) return nominatimCache.get(cacheKey)!;

  const url = new URL("https://nominatim.openstreetmap.org/search");
  url.searchParams.set("q", query);
  url.searchParams.set("format", "jsonv2");
  url.searchParams.set("countrycodes", "se");
  url.searchParams.set("limit", String(RESULT_LIMIT));

  const response = await fetch(url.toString(), { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Search failed (${response.status})`);
  const body = (await response.json()) as { display_name: string; lat: string; lon: string }[];
  const results = body.map((item) => ({
    name: item.display_name,
    latitude: parseFloat(item.lat),
    longitude: parseFloat(item.lon),
    source: "osm" as const,
  }));
  nominatimCache.set(cacheKey, results);
  return results;
}

function searchLocal(query: string, places: PlaceRecord[]): SearchResult[] {
  const q = query.toLowerCase();
  return places
    .filter((p) => p.name.toLowerCase().includes(q))
    .slice(0, RESULT_LIMIT)
    .map((p) => ({ name: `${p.name}, ${p.municipality}`, latitude: p.latitude, longitude: p.longitude, source: "local" as const }));
}

function parseCoordinates(query: string): { latitude: number; longitude: number } | null {
  const match = query.match(/^\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$/);
  if (!match) return null;
  const lat = parseFloat(match[1]);
  const lon = parseFloat(match[2]);
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { latitude: lat, longitude: lon };
}

export function SearchBox({
  places,
  onSelect,
}: {
  places: PlaceRecord[];
  onSelect: (lat: number, lon: number, label: string) => void;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [remoteResults, setRemoteResults] = useState<SearchResult[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const debouncedQuery = useDebouncedValue(query, 300);
  const abortRef = useRef<AbortController | null>(null);

  const coordinateMatch = parseCoordinates(query);
  const localResults = query.length >= MIN_QUERY_LENGTH ? searchLocal(query, places) : [];

  useEffect(() => {
    if (debouncedQuery.length < MIN_QUERY_LENGTH || coordinateMatch) {
      setRemoteResults([]);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setSearchError(null);
    searchNominatim(debouncedQuery, controller.signal)
      .then(setRemoteResults)
      .catch((err: Error) => {
        if (err.name !== "AbortError") {
          setSearchError(t("search.onlineUnavailable"));
          setRemoteResults([]);
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQuery]);

  const combined = [...localResults, ...remoteResults.filter((r) => !localResults.some((l) => l.name === r.name))].slice(
    0,
    RESULT_LIMIT
  );

  return (
    <div className="search-box">
      <label htmlFor="place-search" className="sr-only">
        {t("search.ariaLabel")}
      </label>
      <input
        id="place-search"
        type="text"
        placeholder={t("search.placeholder")}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {open && (coordinateMatch || combined.length > 0 || searchError) && (
        <div className="search-results" role="listbox">
          {coordinateMatch && (
            <button
              type="button"
              className="search-result-item"
              onMouseDown={() =>
                onSelect(coordinateMatch.latitude, coordinateMatch.longitude, `${coordinateMatch.latitude.toFixed(4)}, ${coordinateMatch.longitude.toFixed(4)}`)
              }
            >
              {t("search.goToCoordinates", {
                lat: coordinateMatch.latitude.toFixed(4),
                lon: coordinateMatch.longitude.toFixed(4),
              })}
            </button>
          )}
          {combined.map((result) => (
            <button
              key={`${result.source}-${result.name}`}
              type="button"
              className="search-result-item"
              onMouseDown={() => onSelect(result.latitude, result.longitude, result.name)}
            >
              {result.name}
            </button>
          ))}
          {searchError && <div className="search-attribution">{searchError}</div>}
          {remoteResults.length > 0 && (
            <div className="search-attribution">{t("search.attribution")}</div>
          )}
        </div>
      )}
    </div>
  );
}
