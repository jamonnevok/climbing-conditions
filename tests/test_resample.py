from datetime import datetime, timezone

import pytest

from pipeline.resample import deaccumulate, interp_instant, to_hourly

RUN = datetime(2026, 11, 12, 0, tzinfo=timezone.utc)


def test_deaccumulate_and_clip_negative_noise():
    assert deaccumulate({0: 0.0, 3: 1.0, 6: 1.5, 9: 1.49999}) == {3: 1.0, 6: 0.5, 9: 0.0}


def test_interp_instant():
    v = {0: 0.0, 3: 3.0}
    assert interp_instant(v, 1.5) == pytest.approx(1.5)
    assert interp_instant(v, 4) is None


def test_to_hourly_conserves_precip_and_radiation():
    instants = {"temp_c": {0: 5, 3: 8, 6: 11, 9: 9, 12: 7}}
    precip = {3: 3.0, 6: 0.0, 9: 1.5, 12: 0.0}
    sw = {3: 0.0, 6: 1.08e6, 9: 2.16e6, 12: 0.5e6}  # J/m2 per 3 h
    rows = to_hourly(RUN, instants, {"precip_mm": precip, "sw_j": sw}, 50.47, 4.87, 12)
    assert len(rows) == 12
    vals = list(rows.values())
    assert sum(r["precip_mm"] for r in vals) == pytest.approx(4.5)
    assert sum(r["sw_wm2"] * 3600 for r in vals) == pytest.approx(sum(sw.values()))
    assert vals[0]["precip_mm"] == pytest.approx(1.0)
    assert vals[1]["temp_c"] == pytest.approx(6.5)
    # in November at Namur, 06-09 UTC radiation is weighted towards the later hours
    assert vals[6]["sw_wm2"] < vals[8]["sw_wm2"]
