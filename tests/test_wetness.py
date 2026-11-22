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

def test_nov21_sunny_crag_dries_by_afternoon():
    """Regression: a wet crag followed by a cold, sunny, dry day must become climbable."""
    rows = [
        row(precip=0.00, temp=1.5, td=1.0, wind=2.6, sw=29),
        row(precip=0.03, temp=2.7, td=2.1, wind=2.6, sw=133),
        row(precip=0.03, temp=4.4, td=3.3, wind=2.4, sw=234),
        row(precip=0.00, temp=6.0, td=2.5, wind=2.6, sw=309),
        row(precip=0.00, temp=7.3, td=2.3, wind=2.4, sw=333),
        row(precip=0.00, temp=8.2, td=2.1, wind=1.9, sw=303),
        row(precip=0.00, temp=8.4, td=1.5, wind=2.0, sw=228),
        row(precip=0.00, temp=8.4, td=1.3, wind=1.2, sw=117),
    ]

    simulate(rows, CFG, initial_mm=CFG["max_mm"])

    assert rows[-3]["wet_mm"] <= CFG["dry_ok_mm"]
    assert rows[-1]["wet_mm"] == pytest.approx(0.0)
