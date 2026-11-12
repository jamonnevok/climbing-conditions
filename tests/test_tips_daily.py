from datetime import timedelta

from pipeline import config, tips
from pipeline.daily import best_window, hours_to_dry
from pipeline.timeutil import iso
from tests.helpers import NOW

RULES = config.load_tips()


def mk(scores):
    start = NOW.replace(hour=8, minute=0)
    return [{"t": iso(start + timedelta(hours=i)), "score": {"comfort": s}} for i, s in enumerate(scores)]


def test_best_window_prefers_longer_when_close():
    w = best_window(mk([3, 7, 7.2, 7.1, 7.0, 2]), "comfort", [2, 3, 4], 0.3)
    assert w["hours"] == 4 and w["score"] == 7.1


def test_best_window_short_peak():
    w = best_window(mk([3, 9, 9, 3, 3, 3]), "comfort", [2, 3, 4], 0.3)
    assert w["hours"] == 2 and w["score"] == 9


def test_best_window_skips_gaps_and_none():
    assert best_window(mk([None, 5, None, 6]), "comfort", [2, 3, 4], 0.3) is None


def test_hours_to_dry():
    rows = [{"t": str(i), "wet_mm": w} for i, w in enumerate([1.0, 0.6, None, 0.3, 0.15])]
    assert hours_to_dry(rows, 0, 0.2) == (4, "4")
    assert hours_to_dry(rows[:3], 0, 0.2) == (-1, None)


BASE = dict(day_score=6, t_mean_c=10, t_max_c=14, rh_mean=60, spread_mean_c=6, wind_mean_ms=4, wind_max_ms=6,
            rain_prev48_mm=0, wet_start_mm=0, hours_to_dry=0, sun_fraction=0.1, has_better_window=False,
            temp_lo=8, temp_hi=18, dry_ok_mm=0.2)


def keys(**over):
    return [x["key"] for x in tips.select(RULES, {**BASE, **over}, {})]


def test_neutral_day_has_no_tips():
    assert keys() == []


def test_humid_still_rule():
    assert "humid_still" in keys(rh_mean=90, wind_mean_ms=1)
    assert "humid_still" not in keys(rh_mean=90, wind_mean_ms=5)


def test_warm_cold_rules_use_mode_band():
    assert "warm" in keys(t_max_c=22)
    assert "cold" in keys(t_mean_c=3)


def test_recent_rain_and_drying_time():
    k = keys(rain_prev48_mm=5, wet_start_mm=0.8, hours_to_dry=6)
    assert k[0] == "recent_rain" and "drying_time" in k
    assert "not_drying" in keys(wet_start_mm=0.8, hours_to_dry=-1)


def test_poor_day_points_to_best_window_first():
    assert keys(day_score=2, has_better_window=True, wind_max_ms=12)[0] == "poor_best_window"


def test_max_tips_respected():
    k = keys(day_score=2, has_better_window=True, rain_prev48_mm=5, wet_start_mm=1, hours_to_dry=3,
             rh_mean=95, wind_mean_ms=1, t_mean_c=1, sun_fraction=0.5)
    assert len(k) == RULES["max_tips"]


def test_unknown_fact_never_triggers():
    assert "warm" not in keys(t_max_c=None)


def test_rules_valid_and_translated():
    assert tips.validate(RULES, config.load_i18n()) == []
