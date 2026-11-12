"""End-to-end pipeline tests with fake providers (no network)."""
import json
from datetime import timedelta

import pytest

import pipeline.__main__ as cli
from pipeline import config, history, timeline
from pipeline.errors import ForecastDownloadError
from pipeline.process import process_region
from pipeline.timeutil import floor_hour, iso
from providers.base import ForecastProvider, ObservationProvider
from tests.helpers import NOW, series

CFG = {"regions": config.load_regions(), "scoring": config.load_scoring(),
       "pipeline": config.load_pipeline(), "tips": config.load_tips()}
REGION = CFG["regions"][0]


def inputs(now=NOW):
    obs = series("observation", floor_hour(now) - timedelta(hours=72), 70, provider="irm_aws", precip=0.0)
    # rain 30 h ago to exercise wetness
    k = iso(floor_hour(now) - timedelta(hours=30))
    obs.hours[k]["precip_mm"] = 3.0
    fc = series("forecast", floor_hour(now) - timedelta(hours=9), 140, provider="ecmwf", temp=9, td=3)
    return fc, obs


def test_timeline_prefers_observations_and_fills_gaps_from_forecast():
    fc, obs = inputs()
    first_obs, last_obs = sorted(obs.hours)[0], sorted(obs.hours)[-1]
    obs.hours[first_obs]["sw_wm2"] = None   # no forecast covers this hour -> stays missing
    obs.hours[last_obs]["sw_wm2"] = None    # forecast covers it -> filled and labelled
    rows = timeline.build(obs, fc, floor_hour(NOW) - timedelta(hours=72), floor_hour(NOW) + timedelta(hours=5))
    kinds = [r["kind"] for r in rows]
    assert kinds[0] == "obs" and kinds[-1] == "fc"
    assert kinds.index("fc") == 70
    by_t = {r["t"]: r for r in rows}
    assert by_t[first_obs]["sw_wm2"] is None and by_t[first_obs]["fill"] == []
    assert "sw_wm2" in by_t[last_obs]["fill"] and by_t[last_obs]["sw_wm2"] is not None


def test_missing_hours_stay_missing():
    rows = timeline.build(None, None, NOW, NOW + timedelta(hours=2))
    assert all(r["kind"] == "missing" and r["temp_c"] is None for r in rows)


def test_process_region_output_shape():
    fc, obs = inputs()
    out = process_region(REGION, fc, obs, CFG, NOW)
    assert set(out["days"]) == {"comfort", "performance"}
    assert len(out["days"]["comfort"]) == 5
    h = out["hourly"]
    assert len(h["t"]) == len(h["score"]["comfort"]) == len(h["wet_mm"])
    assert out["meta"]["model_run_utc"] == fc.run
    assert out["meta"]["observation_last_utc"]
    assert out["meta"]["sources"]["temp_c"]["observed"] == "irm_aws label"
    assert all(s is None or 0 <= s <= 10 for s in h["score"]["comfort"])
    assert out["now"]["comfort"]["score"] is not None
    assert max(h["wet_mm"][:70]) > 0  # rain was registered


class FakeFc(ForecastProvider):
    name = "ecmwf"
    calls = 0

    def latest_run(self, horizon_end):
        return floor_hour(NOW) - timedelta(hours=9), 132

    def fetch(self, regions, run, max_lead, horizon_end):
        FakeFc.calls += 1
        fc, _ = inputs()
        fc.meta.update({"resolution": "0p25", "max_lead_h": 132})
        return {r["id"]: fc for r in regions}


class BrokenFc(FakeFc):
    def latest_run(self, horizon_end):
        raise ForecastDownloadError("simulated outage")


class FakeObs(ObservationProvider):
    name = "irm_aws"

    def fetch(self, region, start, end):
        return inputs()[1]


class BrokenObs(ObservationProvider):
    def fetch(self, region, start, end):
        raise RuntimeError("simulated IRM outage")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "WORK", tmp_path / "work")
    monkeypatch.setattr(cli, "DIST", tmp_path / "dist")
    monkeypatch.setattr(cli, "HISTORY", tmp_path / "history")
    monkeypatch.setattr(cli, "utcnow", lambda: NOW)
    monkeypatch.setitem(cli.FORECAST, "ecmwf", FakeFc)
    monkeypatch.setitem(cli.FORECAST, "openmeteo", BrokenFc)
    monkeypatch.setitem(cli.OBSERVATION, "irm_aws", FakeObs)
    monkeypatch.setitem(cli.OBSERVATION, "openmeteo_past", BrokenObs)
    return tmp_path


def run(*cmd):
    return cli.main(list(cmd))


def test_full_update_then_reuse_same_run(sandbox):
    FakeFc.calls = 0
    assert run("update") == 0
    d = json.loads((sandbox / "dist/data/be-namur/latest.json").read_text())
    assert d["meta"]["forecast_provider"] == "ecmwf" and not d["meta"]["forecast_reused"]
    assert (sandbox / "dist/index.html").exists() and (sandbox / "dist/site-config.json").exists()
    obs_files = list((sandbox / "history/observed/be-namur").glob("*.csv"))
    fc_files = list((sandbox / "history/forecast/be-namur").glob("*.csv"))
    assert obs_files and fc_files
    n_fc = sum(1 for _ in open(fc_files[0]))
    # second run: same model run -> no new download, no new forecast history
    assert run("update") == 0
    assert FakeFc.calls == 1
    d2 = json.loads((sandbox / "dist/data/be-namur/latest.json").read_text())
    assert d2["meta"]["forecast_reused"] is True
    assert sum(1 for _ in open(fc_files[0])) == n_fc


def test_forecast_outage_falls_back_to_previous_and_flags_it(sandbox, monkeypatch):
    assert run("update") == 0
    monkeypatch.setitem(cli.FORECAST, "ecmwf", BrokenFc)
    assert run("update") == 0
    d = json.loads((sandbox / "dist/data/be-namur/latest.json").read_text())
    assert d["meta"]["forecast_stale"] is True
    assert any("reusing previous forecast" in w for w in d["meta"]["warnings"])


def test_total_outage_without_previous_refuses_to_publish(sandbox, monkeypatch):
    monkeypatch.setitem(cli.FORECAST, "ecmwf", BrokenFc)
    assert run("fetch-previous") == 0
    assert run("fetch-forecast") == 50
    assert not (sandbox / "dist/data/be-namur/latest.json").exists()


def test_observation_outage_is_labelled_not_invented(sandbox, monkeypatch):
    monkeypatch.setitem(cli.OBSERVATION, "irm_aws", BrokenObs)
    assert run("update") == 0
    d = json.loads((sandbox / "dist/data/be-namur/latest.json").read_text())
    assert d["meta"]["observation_provider"] is None
    assert not any(k.startswith("obs") for k in d["hourly"]["kind"])
    assert any("no observations" in w for w in d["meta"]["warnings"])


def test_rescore_from_previous_keeps_data_time(sandbox):
    assert run("update") == 0
    before = json.loads((sandbox / "dist/data/be-namur/latest.json").read_text())
    assert run("fetch-previous") == 0
    assert run("score", "--from-previous") == 0
    after = json.loads((sandbox / "dist/data/be-namur/latest.json").read_text())
    assert after["meta"]["processed_utc"] == before["meta"]["processed_utc"]
    assert after["meta"]["rescored_from_previous"] is True


def test_daily_history_observations_only(sandbox):
    assert run("daily-history") == 0
    files = list((sandbox / "history/observed/be-namur").glob("*.csv"))
    assert files
    lines = open(files[0]).read().strip().splitlines()
    assert 1 < len(lines) <= 25
    assert not (sandbox / "history/forecast").exists()
    # idempotent
    assert run("daily-history") == 0
    assert len(open(files[0]).read().strip().splitlines()) == len(lines)


def test_validate_catches_bad_scores(sandbox):
    assert run("update") == 0
    p = sandbox / "dist/data/be-namur/latest.json"
    d = json.loads(p.read_text())
    d["hourly"]["score"]["comfort"][0] = 42
    p.write_text(json.dumps(d))
    assert run("validate") == 40
