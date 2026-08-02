from __future__ import annotations

import time as _time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from grid import GridCell
from smhi_weather import SMHIProvider, _to_smhi_time_str


class _MockSMHITransport(httpx.BaseTransport):
    """Routes by URL (SMHI's request shape isn't a queue of sequential
    calls like Open-Meteo's batches -- each request targets a specific
    resource: a times list, or one (time, parameter) whole-domain array).

    `times_by_base` values are real ISO-with-separators strings, matching
    what /times.json actually returns. `values_by_time_param` is keyed by
    the SAME ISO strings for test-authoring convenience; the mock converts
    to SMHI's compact URL-path format internally to match incoming
    requests, exactly mirroring what the real client is expected to do."""

    def __init__(self, times_by_base: dict[str, list[str]], values_by_time_param: dict[tuple[str, str], list]):
        self.times_by_base = times_by_base
        self.values_by_compact_time_param = {
            (_to_smhi_time_str(datetime.fromisoformat(t)), p): v for (t, p), v in values_by_time_param.items()
        }
        self.calls: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.split('/geotype')[0].split('/times.json')[0]}"

        if parsed.path.endswith("times.json"):
            return httpx.Response(200, json={"time": self.times_by_base[base]}, request=request)

        # .../geotype/multipoint/time/{compact_time}/parameter/{p}/data.json
        parts = parsed.path.split("/")
        compact_time = parts[parts.index("time") + 1]
        p = parts[parts.index("parameter") + 1]
        values = self.values_by_compact_time_param.get((compact_time, p))
        if values is None:
            return httpx.Response(404, request=request)
        return httpx.Response(
            200,
            json={
                "referenceTime": "2026-08-02T00:00:00Z",
                "createdTime": "2026-08-02T00:00:00Z",
                "timeSeries": [{"time": compact_time, "data": {p: values}}],
            },
            request=request,
        )


FORECAST_BASE = "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1"
ANALYSIS_BASE = "https://opendata-download-metanalys.smhi.se/api/category/mesan2g/version/3"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_provider(transport, grid_index, now, max_retries=0, backoff_base_s=0.0):
    client = httpx.Client(transport=transport)
    return SMHIProvider(
        forecast_base_url=FORECAST_BASE,
        analysis_base_url=ANALYSIS_BASE,
        grid_index=grid_index,
        client=client,
        now=now,
        max_retries=max_retries,
        backoff_base_s=backoff_base_s,
    )


def test_fetch_combined_maps_domain_wide_values_to_our_cells():
    now = datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc)
    cells = [
        GridCell(cell_id="A", latitude=59.3, longitude=18.0),
        GridCell(cell_id="B", latitude=57.7, longitude=11.9),
    ]
    # Our cells map to domain indices 2 and 5 (arbitrary, in a much larger
    # domain array) -- the point is the provider must pick out the RIGHT
    # index per cell, not just the first N values.
    grid_index = {"A": 2, "B": 5}

    analysis_time = _iso(datetime(2026, 8, 2, 7, 0, tzinfo=timezone.utc))
    forecast_time = _iso(datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc))
    times_by_base = {FORECAST_BASE: [forecast_time], ANALYSIS_BASE: [analysis_time]}

    domain_size = 10
    values_by_time_param = {}
    for t, params in [
        (analysis_time, {"air_temperature": "analysis_temp", "relative_humidity": "rh", "precipitation_amount_last_1_hours": "precip",
                          "wind_speed": "ws", "wind_speed_of_gust": "gust", "cloud_area_fraction": "cloud"}),
        (forecast_time, {"air_temperature": "fc_temp", "relative_humidity": "rh", "precipitation_amount_mean": "precip",
                          "wind_speed": "ws", "wind_speed_of_gust": "gust", "cloud_area_fraction": "cloud"}),
    ]:
        for smhi_param, label in params.items():
            arr = [None] * domain_size
            arr[2] = {"analysis_temp": 10.0, "fc_temp": 15.0, "rh": 60.0, "precip": 0.5, "ws": 3.0, "gust": 5.0, "cloud": 40.0}[label]
            arr[5] = {"analysis_temp": 11.0, "fc_temp": 16.0, "rh": 61.0, "precip": 0.6, "ws": 3.1, "gust": 5.1, "cloud": 41.0}[label]
            values_by_time_param[(t, smhi_param)] = arr

    transport = _MockSMHITransport(times_by_base, values_by_time_param)
    provider = _make_provider(transport, grid_index, now)

    result = provider.fetch_combined(cells, past_days=1, forecast_days=1)

    assert set(result) == {"A", "B"}
    # Cell A's analysis-hour temperature should be domain index 2's value
    # (10.0), not domain index 0/1/etc -- proves index-based lookup, not
    # positional/list-order assumption.
    hour_idx = result["A"].times.index("2026-08-02T07:00")
    assert result["A"].temperature_2m[hour_idx] == 10.0
    assert result["B"].temperature_2m[hour_idx] == 11.0

    fc_hour_idx = result["A"].times.index("2026-08-02T09:00")
    assert result["A"].temperature_2m[fc_hour_idx] == 15.0
    assert result["B"].temperature_2m[fc_hour_idx] == 16.0


def test_cells_without_a_grid_index_entry_are_skipped_not_crashed():
    now = datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc)
    cells = [GridCell(cell_id="A", latitude=59.3, longitude=18.0), GridCell(cell_id="UNMAPPED", latitude=0.0, longitude=0.0)]
    grid_index = {"A": 0}  # "UNMAPPED" deliberately absent

    times_by_base = {FORECAST_BASE: [], ANALYSIS_BASE: []}
    transport = _MockSMHITransport(times_by_base, {})
    provider = _make_provider(transport, grid_index, now)

    result = provider.fetch_combined(cells, past_days=1, forecast_days=1)

    assert set(result) == {"A"}


def test_forecast_times_beyond_forecast_days_are_excluded():
    now = datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc)
    cells = [GridCell(cell_id="A", latitude=59.3, longitude=18.0)]
    grid_index = {"A": 0}

    in_range = _iso(datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc))     # +1 day -- within forecast_days=1
    out_of_range = _iso(datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc))  # +3 days -- outside forecast_days=1
    times_by_base = {FORECAST_BASE: [in_range, out_of_range], ANALYSIS_BASE: []}
    values_by_time_param = {(in_range, "air_temperature"): [20.0]}

    transport = _MockSMHITransport(times_by_base, values_by_time_param)
    provider = _make_provider(transport, grid_index, now)

    provider.fetch_combined(cells, past_days=1, forecast_days=1)

    out_of_range_compact = _to_smhi_time_str(datetime.fromisoformat(out_of_range))
    requested_times = [url for url in transport.calls if "geotype/multipoint/time" in url]
    assert not any(out_of_range_compact in url for url in requested_times)


def test_missing_time_parameter_combo_is_not_retried():
    # A 404 means "this (time, parameter) genuinely doesn't exist" -- not
    # transient, so retrying it wastes the backoff delay for no benefit.
    # Regression test: a full-grid fetch is hundreds of individual
    # time/parameter requests, and some are expected to be missing; a
    # naive "retry everything" policy made a real fetch take far longer
    # than the request count alone would predict.
    now = datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc)
    cells = [GridCell(cell_id="A", latitude=59.3, longitude=18.0)]
    grid_index = {"A": 0}

    t = _iso(datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc))
    times_by_base = {FORECAST_BASE: [t], ANALYSIS_BASE: []}
    transport = _MockSMHITransport(times_by_base, {})  # every parameter at t is missing -> 404

    provider = _make_provider(transport, grid_index, now, max_retries=4, backoff_base_s=5.0)  # would be slow if retried

    start = _time.monotonic()
    provider.fetch_combined(cells, past_days=0, forecast_days=1)
    elapsed = _time.monotonic() - start

    assert elapsed < 1.0, f"404s should not be retried, took {elapsed:.2f}s"
    multipoint_calls = [c for c in transport.calls if "geotype/multipoint/time" in c]
    assert len(multipoint_calls) == 6  # one attempt per forecast parameter, no retries


def test_missing_hourly_gap_forward_fills_from_last_known_reading():
    now = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
    cells = [GridCell(cell_id="A", latitude=59.3, longitude=18.0)]
    grid_index = {"A": 0}

    # Two forecast times 3 hours apart (simulating SMHI's coarser step at
    # longer lead times) -- the hour in between should forward-fill from
    # the earlier reading, not go null.
    t1 = _iso(datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc))
    t2 = _iso(datetime(2026, 8, 2, 14, 0, tzinfo=timezone.utc))
    times_by_base = {FORECAST_BASE: [t1, t2], ANALYSIS_BASE: []}
    values_by_time_param = {(t1, "air_temperature"): [12.0], (t2, "air_temperature"): [18.0]}

    transport = _MockSMHITransport(times_by_base, values_by_time_param)
    provider = _make_provider(transport, grid_index, now)

    result = provider.fetch_combined(cells, past_days=0, forecast_days=1)

    idx_12 = result["A"].times.index("2026-08-02T12:00")
    idx_13 = result["A"].times.index("2026-08-02T13:00")
    assert result["A"].temperature_2m[idx_12] == 12.0  # forward-filled from t1
    assert result["A"].temperature_2m[idx_13] == 12.0  # still forward-filled, not yet at t2
