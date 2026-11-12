from datetime import datetime, timezone

import pytest

from providers.openmeteo import parse_response

J = {"hourly": {
    "time": ["2026-11-12T00:00", "2026-11-12T01:00", "2026-11-12T02:00"],
    "temperature_2m": [4.0, 6.0, 8.0], "dew_point_2m": [2.0, 2.0, 2.0], "relative_humidity_2m": [87, 75, 66],
    "precipitation": [0.0, 1.2, 0.4], "wind_speed_10m": [2.0, 4.0, 6.0], "cloud_cover": [100, 50, 0],
    "shortwave_radiation": [0, 0, 10]}}


def test_hour_start_convention():
    rows = parse_response(J, datetime(2026, 11, 12, 0, tzinfo=timezone.utc), datetime(2026, 11, 12, 3, tzinfo=timezone.utc))
    r0 = rows["2026-11-12T00:00Z"]
    assert r0["temp_c"] == pytest.approx(5.0)     # mid-hour mean
    assert r0["precip_mm"] == pytest.approx(1.2)  # preceding-hour total labelled at 01:00
    # the last hour has no following value and no accumulation: it is left out, not invented
    assert "2026-11-12T02:00Z" not in rows
