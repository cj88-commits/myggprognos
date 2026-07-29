import { RISK_CATEGORIES } from "../lib/riskModel";
import type { LayerKey } from "../types/forecast";

const CONFIDENCE_STOPS = [
  { label: "Low", color: "#a5262c" },
  { label: "Med", color: "#d9a441" },
  { label: "High", color: "#2f6f4f" },
];

export function Legend({ layer }: { layer: LayerKey }) {
  const stops =
    layer === "confidence"
      ? CONFIDENCE_STOPS
      : RISK_CATEGORIES.map((c) => ({ label: c.label, color: c.color }));

  const title = layer === "confidence" ? "Forecast confidence" : "Mosquito risk (0–10)";

  return (
    <div className="legend" role="group" aria-label={`Map legend: ${title}`}>
      <strong>{title}</strong>
      <div className="legend-scale">
        {stops.map((stop) => (
          <div className="legend-swatch" key={stop.label}>
            <div className="chip" style={{ background: stop.color }} aria-hidden="true" />
            <span>{stop.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
