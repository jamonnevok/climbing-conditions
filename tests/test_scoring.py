from datetime import timedelta

import pytest

from pipeline import config
from pipeline.scoring import c_moisture, c_rain, c_temperature, c_wetness, piecewise, score_rows, lin
from pipeline.timeutil import iso
from tests.helpers import NOW, row

CFG = config.load_scoring()


def mk_rows(n=6, **kw):
    rows = []
    for i in range(n):
        r = row(**{k: v for k, v in kw.items() if k != "wet"})
        r["t"] = iso(NOW.replace(hour=12, minute=0) + timedelta(hours=i))
        r["wet_mm"] = kw.get("wet", 0.0)
        r["kind"] = "fc"
        rows.append(r)
    return rows


def test_temperature_band_and_falloff():
    assert c_temperature(10, 8, 18, 10) == 1
    assert c_temperature(3, 8, 18, 10) == pytest.approx(0.5)
    assert c_temperature(-5, 8, 18, 10) == 0
    assert c_temperature(28, 8, 18, 10) == 0


def test_lin_both_directions():
    assert lin(5, 0, 10) == 0.5
    assert lin(95, 95, 65) == 0 and lin(65, 95, 65) == 1


def test_moisture_limits():
    m = CFG["modes"]["comfort"]["moisture"]
    assert c_moisture(40, 12, m) == 1
    assert c_moisture(99, 0.2, m) == 0


def test_wetness_and_rain_components():
    assert c_wetness(0, 1) == 1 and c_wetness(2, 1) == 0
    assert c_rain(0, 0, 1) == 1
    assert c_rain(0, 1, 1) == pytest.approx(0.5)
    assert c_rain(2, 0, 1) == 0


def test_wind_curve():
    curve = CFG["wind"]["curve"]
    assert piecewise(0, curve) == 0.6
    assert piecewise(4, curve) == 1.0
    assert piecewise(8, curve) == pytest.approx(0.7)
    assert piecewise(30, curve) == 0.0


def test_perfect_conditions_score_high_and_bounded():
    rows = mk_rows(temp=12, td=0, wind=4, sw=300)
    score_rows(rows, "comfort", CFG, 50.47, 4.87)
    s = rows[0]["score"]["comfort"]
    assert 8.5 <= s <= 10


def test_active_rain_caps_at_2():
    rows = mk_rows(temp=12, td=0, wind=4, precip=0.5)
    score_rows(rows, "comfort", CFG, 50.47, 4.87)
    assert rows[0]["score"]["comfort"] <= CFG["caps"]["active_rain"]
    assert "cap_active_rain" in rows[0]["drivers"]["comfort"]


def test_very_wet_caps_at_5():
    rows = mk_rows(temp=12, td=0, wind=4, wet=1.5)
    score_rows(rows, "comfort", CFG, 50.47, 4.87)
    assert rows[0]["score"]["comfort"] <= CFG["caps"]["very_wet"]
    assert "cap_very_wet" in rows[0]["drivers"]["comfort"]


def test_missing_input_gives_no_score():
    rows = mk_rows()
    rows[0]["temp_c"] = None
    score_rows(rows, "comfort", CFG, 50.47, 4.87)
    assert rows[0]["score"]["comfort"] is None
    assert rows[0]["drivers"]["comfort"] == ["missing"]


def test_missing_lookahead_rain_gives_no_score():
    rows = mk_rows()
    rows[1]["precip_mm"] = None
    score_rows(rows, "comfort", CFG, 50.47, 4.87)
    assert rows[0]["score"]["comfort"] is None


def test_drivers_name_humidity_and_wet_rock():
    rows = mk_rows(temp=10, td=9.5, wind=1, wet=0.8)
    score_rows(rows, "performance", CFG, 50.47, 4.87)
    d = rows[0]["drivers"]["performance"]
    assert "moisture" in d and "wetness" in d


def test_modes_differ_in_heat():
    rows = mk_rows(temp=20, td=5, wind=4)
    score_rows(rows, "comfort", CFG, 50.47, 4.87)
    score_rows(rows, "performance", CFG, 50.47, 4.87)
    assert rows[0]["score"]["comfort"] > rows[0]["score"]["performance"]


def test_scores_always_within_0_10():
    import itertools
    for temp, td, p, w, wet in itertools.product([-15, 5, 35], [-20, 4], [0, 5], [0, 25], [0, 4]):
        rows = mk_rows(temp=temp, td=min(td, temp), precip=p, wind=w, wet=wet)
        score_rows(rows, "comfort", CFG, 50.47, 4.87)
        assert 0 <= rows[0]["score"]["comfort"] <= 10


def test_active_rain_cliff_and_gradual_post_rain_recovery():
    """Rain starts abruptly; recovery follows drying and decreasing moisture."""
    from pipeline.wetness import simulate

    weather = [
        # dry lead-in
        (0.00, 1.1, -2.0, 78, 2.0, 0),
        # active rain: immediate cliff
        (0.40, 1.2, 0.8, 90, 2.0, 5),
        (0.48, 1.5, 1.1, 94, 2.0, 35),
        # rain stops, but saturated air and residual wetness remain
        (0.07, 1.5, 1.1, 94, 2.0, 57),
        (0.07, 1.6, 1.0, 93, 2.0, 43),
        (0.07, 1.6, 0.8, 92, 2.0, 22),
        # progressively drier air and rock
        (0.01, 2.0, 0.5, 88, 2.5, 20),
        (0.00, 3.0, 0.0, 82, 3.0, 60),
        (0.00, 4.0, 0.0, 75, 3.0, 100),
        (0.00, 5.0, 0.0, 70, 3.0, 120),
    ]

    rows = []
    for i, (precip, temp, td, rh, wind, sw) in enumerate(weather):
        r = row(temp=temp, td=td, rh=rh, precip=precip, wind=wind, sw=sw)
        r["t"] = iso(NOW.replace(hour=6, minute=0) + timedelta(hours=i))
        r["kind"] = "fc"
        rows.append(r)

    simulate(rows, CFG["wetness"])
    score_rows(rows, "performance", CFG, 50.47, 4.87)

    scores = [r["score"]["performance"] for r in rows]

    # Active rain retains the sharp, realistic cliff.
    assert scores[1] == pytest.approx(CFG["caps"]["active_rain"])
    assert scores[2] == pytest.approx(CFG["caps"]["active_rain"])

    # Stopping rain does not create a reverse cliff.
    assert scores[3] <= 6.0
    assert scores[3] - scores[2] <= 4.0

    # Recovery is progressive as wetness and atmospheric moisture decrease.
    assert scores[3] < scores[4] < scores[5] < scores[6]
    assert scores[7] >= scores[6]
