import math
from datetime import datetime, timezone

import pytest

from pipeline import physics as p


def test_rh_equals_100_when_dewpoint_equals_temp():
    assert p.rh_from_dewpoint(12.3, 12.3) == pytest.approx(100.0)


def test_rh_known_value():
    # T=20 °C, Td=10 °C -> ~52.5 % (Magnus)
    assert p.rh_from_dewpoint(20, 10) == pytest.approx(52.5, abs=0.5)


def test_dewpoint_roundtrip():
    for t, rh in [(-5, 80), (0, 50), (15, 65), (30, 30)]:
        assert p.rh_from_dewpoint(t, p.dewpoint_from_rh(t, rh)) == pytest.approx(rh, abs=0.01)


def test_rh_clipped():
    assert p.rh_from_dewpoint(10, 12) == 100.0


def test_vpd_zero_when_saturated_and_positive_otherwise():
    assert p.vpd_kpa(10, 10) == 0.0
    assert p.vpd_kpa(20, 10) > 0.9


def test_wind_speed():
    assert p.wind_speed(3, 4) == 5


def test_solar_noon_vs_night_namur():
    noon = datetime(2026, 6, 21, 11, 40, tzinfo=timezone.utc)
    night = datetime(2026, 6, 21, 23, 40, tzinfo=timezone.utc)
    assert p.cos_solar_zenith(noon, 50.47, 4.87) == pytest.approx(math.cos(math.radians(50.47 - 23.44)), abs=0.02)
    assert p.cos_solar_zenith(night, 50.47, 4.87) < 0
    assert p.clear_sky_ghi(-0.1) == 0
    assert 800 < p.clear_sky_ghi(0.9) < 1000
