import pytest

from pipeline import config
from pipeline.wetness import drying_rate, simulate
from tests.helpers import row

CFG = config.load_scoring()["wetness"]


def test_rain_increases_and_is_capped():
    rows = [row(precip=10, td=9.9, temp=10, wind=0, sw=0)]
    simulate(rows, CFG)
    assert rows[0]["wet_mm"] == pytest.approx(CFG["max_mm"])


def test_dries_faster_with_sun_wind_and_dry_air():
    slow = drying_rate(8, 7.5, 0.5, 0, CFG)
    fast = drying_rate(15, 2, 5, 500, CFG)
    assert fast > 5 * slow > 0


def test_never_negative():
    rows = [row(precip=0, temp=25, td=0, wind=8, sw=800) for _ in range(5)]
    simulate(rows, CFG, initial_mm=0.1)
    assert all(r["wet_mm"] == 0 for r in rows)


def test_missing_input_keeps_state_and_flags_hour():
    rows = [row(precip=2, temp=10, td=9, wind=0, sw=0), row(), row(precip=0, temp=10, td=9, wind=0, sw=0)]
    rows[1]["precip_mm"] = None
    simulate(rows, CFG)
    assert rows[1]["wet_mm"] is None
    assert rows[2]["wet_mm"] == pytest.approx(rows[0]["wet_mm"] - drying_rate(10, 9, 0, 0, CFG), abs=1e-9)
