from __future__ import annotations

from datetime import date

import httpx
import pytest
from grid import GridCell
from weather import DiskCache, OpenMeteoProvider, WeatherValidationError


class _MockTransport(httpx.BaseTransport):
    """Deterministic transport used to unit test OpenMeteoProvider without
    real network access."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if not self.responses:
            raise AssertionError("No more mock responses configured")
        status, payload = self.responses.pop(0)
        return httpx.Response(status_code=status, json=payload, request=request)


def _valid_payload_for(cells: list[GridCell]) -> list[dict]:
    hours = ["2026-07-20T00:00", "2026-07-20T01:00"]
    return [
        {
            "hourly": {
                "time": hours,
                "temperature_2m": [15.0, 15.5],
                "relative_humidity_2m": [60.0, 61.0],
                "precipitation": [0.0, 0.1],
                "wind_speed_10m": [2.0, 2.5],
                "wind_gusts_10m": [4.0, 4.5],
                "cloud_cover": [50.0, 55.0],
                "soil_moisture_0_to_1cm": [0.2, 0.21],
            }
        }
        for _ in cells
    ]


def _provider_with_transport(transport: _MockTransport, tmp_path) -> OpenMeteoProvider:
    client = httpx.Client(transport=transport)
    cache = DiskCache(directory=tmp_path, ttl_s=3600)
    return OpenMeteoProvider(cache=cache, client=client, max_retries=2, backoff_base_s=0.001)


def test_fetch_forecast_parses_valid_response(tmp_path):
    cells = [GridCell(cell_id="A", latitude=59.3, longitude=18.0), GridCell(cell_id="B", latitude=57.7, longitude=11.9)]
    transport = _MockTransport([(200, _valid_payload_for(cells))])
    provider = _provider_with_transport(transport, tmp_path)

    result = provider.fetch_forecast(cells, date(2026, 7, 20), date(2026, 7, 20))

    assert set(result) == {"A", "B"}
    assert result["A"].temperature_2m == [15.0, 15.5]
    assert result["A"].soil_moisture == [0.2, 0.21]


def test_fetch_forecast_retries_on_transient_failure_then_succeeds(tmp_path):
    cells = [GridCell(cell_id="A", latitude=59.3, longitude=18.0)]
    transport = _MockTransport([(500, {"error": True, "reason": "server error"}), (200, _valid_payload_for(cells))])
    provider = _provider_with_transport(transport, tmp_path)

    result = provider.fetch_forecast(cells, date(2026, 7, 20), date(2026, 7, 20))

    assert "A" in result
    assert transport.calls == 2


def test_fetch_forecast_gives_up_after_max_retries_and_skips_batch(tmp_path):
    cells = [GridCell(cell_id="A", latitude=59.3, longitude=18.0)]
    transport = _MockTransport([(500, {"error": True, "reason": "down"})] * 10)
    provider = _provider_with_transport(transport, tmp_path)

    result = provider.fetch_forecast(cells, date(2026, 7, 20), date(2026, 7, 20))

    assert result == {}


def test_response_validation_rejects_error_payload(tmp_path):
    from weather import _validate_response

    with pytest.raises(WeatherValidationError):
        _validate_response({"error": True, "reason": "Invalid coordinates"})


def test_implausible_values_are_dropped_not_trusted(tmp_path):
    cells = [GridCell(cell_id="A", latitude=59.3, longitude=18.0)]
    payload = _valid_payload_for(cells)
    payload[0]["hourly"]["temperature_2m"] = [999.0, 15.5]  # implausible
    transport = _MockTransport([(200, payload)])
    provider = _provider_with_transport(transport, tmp_path)

    result = provider.fetch_forecast(cells, date(2026, 7, 20), date(2026, 7, 20))

    assert result["A"].temperature_2m[0] is None
    assert result["A"].temperature_2m[1] == 15.5


def test_disk_cache_avoids_second_request(tmp_path):
    cells = [GridCell(cell_id="A", latitude=59.3, longitude=18.0)]
    transport = _MockTransport([(200, _valid_payload_for(cells))])
    provider = _provider_with_transport(transport, tmp_path)

    provider.fetch_forecast(cells, date(2026, 7, 20), date(2026, 7, 20))
    provider.fetch_forecast(cells, date(2026, 7, 20), date(2026, 7, 20))

    assert transport.calls == 1
