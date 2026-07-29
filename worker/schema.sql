-- D1 schema for the mosquito reporting API.
--
-- Privacy notes:
--   * latitude_rounded/longitude_rounded are rounded to ~1km precision by
--     the client before submission (see frontend ReportForm) -- never
--     exact GPS coordinates.
--   * reporter_hash is a salted SHA-256 hash of the submitter's IP
--     address, used only for short-window spam/rate-limit checks. It is
--     never returned by any API response and cannot be reversed to an IP.
--   * No names, emails, or other direct identifiers are collected.

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
