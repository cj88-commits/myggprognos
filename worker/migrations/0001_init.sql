-- Initial schema migration. Apply with:
--   wrangler d1 migrations apply mosquito-reports --local   (dev)
--   wrangler d1 migrations apply mosquito-reports --remote  (production)
--
-- Kept identical to schema.sql (the source of truth for a fresh local
-- setup); future schema changes should be added as new numbered
-- migrations here rather than editing this file.

CREATE TABLE IF NOT EXISTS mosquito_reports (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    cell_id TEXT NOT NULL,
    latitude_rounded REAL NOT NULL,
    longitude_rounded REAL NOT NULL,
    severity INTEGER NOT NULL CHECK (severity BETWEEN 0 AND 4),
    terrain TEXT,
    activity TEXT,
    repellent_used INTEGER,
    comment TEXT,
    forecast_score REAL,
    model_version TEXT,
    reporter_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_reports_cell_id ON mosquito_reports (cell_id);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON mosquito_reports (created_at);
CREATE INDEX IF NOT EXISTS idx_reports_cell_created ON mosquito_reports (cell_id, created_at);
