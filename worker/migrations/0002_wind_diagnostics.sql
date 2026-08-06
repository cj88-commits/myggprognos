-- Adds forecast-context columns to mosquito_reports (see schema.sql for
-- the full up-to-date schema and field notes). Nullable, additive-only --
-- safe to run against a table that already has rows.
ALTER TABLE mosquito_reports ADD COLUMN forecast_wind_ms REAL;
ALTER TABLE mosquito_reports ADD COLUMN effective_wind_ms REAL;
ALTER TABLE mosquito_reports ADD COLUMN temperature_c REAL;
ALTER TABLE mosquito_reports ADD COLUMN humidity_pct REAL;
ALTER TABLE mosquito_reports ADD COLUMN population_potential REAL;
ALTER TABLE mosquito_reports ADD COLUMN biting_activity REAL;
ALTER TABLE mosquito_reports ADD COLUMN target_timestamp TEXT;
