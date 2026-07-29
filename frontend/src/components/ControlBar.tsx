import { useEffect, useRef, useState } from "react";
import { ACTIVITY_LABELS, LAYER_LABELS, type LayerKey, type Manifest, type PlaceRecord } from "../types/forecast";
import { SearchBox } from "./SearchBox";
import { useGeolocation } from "../hooks/useGeolocation";

function addDaysIso(dateIso: string, days: number): string {
  const d = new Date(dateIso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function formatDateLabel(dateIso: string): string {
  const d = new Date(dateIso + "T00:00:00Z");
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
}

export interface ControlBarProps {
  manifest: Manifest | null;
  places: PlaceRecord[];
  date: string;
  onDateChange: (date: string) => void;
  isHourlyDay: boolean;
  hour: number | null;
  onHourChange: (hour: number) => void;
  daypart: string;
  onDaypartChange: (daypart: string) => void;
  activity: string;
  onActivityChange: (activity: string) => void;
  layer: LayerKey;
  onLayerChange: (layer: LayerKey) => void;
  onSelectLocation: (lat: number, lon: number) => void;
  animating: boolean;
  onToggleAnimation: () => void;
}

const DAYPARTS = ["morning", "afternoon", "evening", "night"];

export function ControlBar({
  manifest,
  places,
  date,
  onDateChange,
  isHourlyDay,
  hour,
  onHourChange,
  daypart,
  onDaypartChange,
  activity,
  onActivityChange,
  layer,
  onLayerChange,
  onSelectLocation,
  animating,
  onToggleAnimation,
}: ControlBarProps) {
  const forecastStart = manifest?.forecast_start ?? new Date().toISOString().slice(0, 10);
  const dayOptions = Array.from({ length: 7 }, (_, i) => addDaysIso(forecastStart, i));

  const { locate, loading: locating, error: geoError } = useGeolocation(onSelectLocation);

  return (
    <div className="control-bar">
      <div className="control-group">
        <SearchBox places={places} onSelect={(lat, lon) => onSelectLocation(lat, lon)} />
      </div>

      <div className="control-group">
        <button
          type="button"
          className="icon-button"
          onClick={locate}
          aria-label="Use my current location"
          title={geoError ?? "Use my current location"}
        >
          {locating ? "…" : "📍"}
        </button>
      </div>

      <div className="control-group">
        <label htmlFor="date-select">Day</label>
        <select id="date-select" value={date} onChange={(e) => onDateChange(e.target.value)}>
          {dayOptions.map((d, i) => (
            <option key={d} value={d}>
              {i === 0 ? "Today" : formatDateLabel(d)}
            </option>
          ))}
        </select>
      </div>

      {isHourlyDay ? (
        <div className="control-group">
          <label htmlFor="hour-select">Hour (UTC)</label>
          <input
            id="hour-select"
            type="range"
            min={0}
            max={23}
            step={1}
            value={hour ?? 0}
            onChange={(e) => onHourChange(parseInt(e.target.value, 10))}
            aria-valuetext={`${hour ?? 0}:00 UTC`}
          />
          <span aria-hidden="true">{String(hour ?? 0).padStart(2, "0")}:00</span>
          <button type="button" className="icon-button" aria-pressed={animating} onClick={onToggleAnimation} title="Play/pause hourly animation">
            {animating ? "⏸" : "▶"}
          </button>
        </div>
      ) : (
        <div className="control-group">
          <label htmlFor="daypart-select">Time of day</label>
          <select id="daypart-select" value={daypart} onChange={(e) => onDaypartChange(e.target.value)}>
            {DAYPARTS.map((part) => (
              <option key={part} value={part}>
                {part[0].toUpperCase() + part.slice(1)}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="control-group">
        <label htmlFor="activity-select">Activity</label>
        <select id="activity-select" value={activity} onChange={(e) => onActivityChange(e.target.value)}>
          {Object.entries(ACTIVITY_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <div className="control-group">
        <label htmlFor="layer-select">Layer</label>
        <select id="layer-select" value={layer} onChange={(e) => onLayerChange(e.target.value as LayerKey)}>
          {Object.entries(LAYER_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
