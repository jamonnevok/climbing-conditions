from datetime import datetime, timedelta, timezone

import pytest

from providers.irm import aggregate_hourly, parse_stations, select_stations

T0 = datetime(2026, 11, 12, 10, tzinfo=timezone.utc)


def rec(minutes, **kw):
    base = {"code": 6459, "timestamp": (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "precip_quantity": 0.1, "temp_dry_shelter_avg": 6.0, "humidity_rel_shelter_avg": 90.0,
            "wind_speed_10m": 3.0, "short_wave_from_sky_avg": 50.0}
    base.update(kw)
    return base


def test_aggregate_full_hour():
    recs = [rec(m) for m in (10, 20, 30, 40, 50, 60)]
    rows = aggregate_hourly(recs, T0, T0 + timedelta(hours=1), 4)
    r = rows["2026-11-12T10:00Z"]
    assert r["precip_mm"] == pytest.approx(0.6)
    assert r["temp_c"] == 6.0 and r["rh"] == 90.0
    assert r["dewpoint_c"] == pytest.approx(4.47, abs=0.05)
    assert r["cloud_pct"] is None


def test_incomplete_hour_has_no_precip_sum_but_keeps_means():
    recs = [rec(m) for m in (10, 20, 30, 40, 50)]
    r = aggregate_hourly(recs, T0, T0 + timedelta(hours=1), 4)["2026-11-12T10:00Z"]
    assert r["precip_mm"] is None
    assert r["temp_c"] == 6.0


def test_implausible_values_dropped():
    recs = [rec(m, temp_dry_shelter_avg=99.0) for m in (10, 20, 30, 40, 50, 60)]
    r = aggregate_hourly(recs, T0, T0 + timedelta(hours=1), 4)["2026-11-12T10:00Z"]
    assert r["temp_c"] is None and r["dewpoint_c"] is None


def test_station_selection_dynamic_nearest_active():
    geo = {"features": [
        {"geometry": {"coordinates": [4.689, 50.582]}, "properties": {"code": 6459, "name": "ERNAGE", "altitude": 159.2, "date_end": None}},
        {"geometry": {"coordinates": [5.255, 50.194]}, "properties": {"code": 6472, "name": "HUMAIN", "altitude": 295.3, "date_end": None}},
        {"geometry": {"coordinates": [4.9, 50.5]}, "properties": {"code": 1, "name": "CLOSED", "altitude": 1, "date_end": "2020-01-01"}},
        {"geometry": {"coordinates": [2.0, 51.0]}, "properties": {"code": 2, "name": "FAR", "altitude": 1, "date_end": None}},
    ]}
    region = {"lat": 50.47, "lon": 4.87, "stations": {"max_distance_km": 60, "max_candidates": 3}}
    sel = select_stations(parse_stations(geo), region)
    assert [s["code"] for s in sel] == [6459, 6472]
    assert sel[0]["km"] == pytest.approx(17.9, abs=0.3)  # matches Step 0 report


def test_axis_order_autodetect():
    geo = {"features": [{"geometry": {"coordinates": [50.582, 4.689]}, "properties": {"code": 1, "name": "X", "altitude": 1, "date_end": None}}]}
    s = parse_stations(geo)[0]
    assert s["lat"] == 50.582 and s["lon"] == 4.689
