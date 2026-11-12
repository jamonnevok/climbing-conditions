"""Command-line entry point:  python -m pipeline <command>

Stages (each one is a separate GitHub Actions step, so failures are easy to locate):
  fetch-previous      load the inputs of the currently published site (for reuse)
  fetch-forecast      newest ECMWF run (reused if already processed) -> fallback chain
  fetch-observations  latest IRM/KMI observations -> fallback chain
  site                assemble the static frontend into dist/
  score               timeline, wetness, scores, tips -> dist/data/*.json
  validate            sanity-check the generated JSON
  history             append compact calibration history (CSV)
  daily-history       quiet daily run: observations only, history only, no deploy
  update              everything above, in order (local convenience)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import timedelta
from pathlib import Path

from providers.base import HourlySeries
from providers.registry import FORECAST, OBSERVATION

from . import config, history
from .errors import (FallbackError, ForecastDownloadError, NoDataError, ObservationDownloadError,
                     ParseError, PipelineError, ValidationError)
from .process import process_region
from .timeutil import floor_hour, iso, parse, utcnow

ROOT = config.ROOT
WORK = Path(os.environ.get("CCA_WORK", ROOT / "work"))
DIST = Path(os.environ.get("CCA_DIST", ROOT / "dist"))
HISTORY = ROOT / "history"
log = logging.getLogger("pipeline")


def _cfg() -> dict:
    return {"regions": config.load_regions(), "scoring": config.load_scoring(),
            "pipeline": config.load_pipeline(), "tips": config.load_tips()}


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _write(p: Path, obj, compact=True):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":") if compact else None,
                            indent=None if compact else 2), encoding="utf-8")


def _state() -> dict:
    return _read(WORK / "state.json") or {"warnings": {}, "new_run": False}


def _save_state(s):
    _write(WORK / "state.json", s, compact=False)


def _warn(state, region_id, msg):
    log.warning(msg)
    state["warnings"].setdefault(region_id, []).append(msg)


# ---------------------------------------------------------------- stages --
def cmd_fetch_previous(args):
    """Previous published inputs, from the live site (CI) or local dist/ (local)."""
    import requests
    cfg = _cfg()
    # a fresh pipeline run starts here: reset working state and inputs
    shutil.rmtree(WORK / "inputs", ignore_errors=True)
    shutil.rmtree(WORK / "previous", ignore_errors=True)
    _save_state({"warnings": {}, "new_run": False})
    for r in cfg["regions"]:
        dest = WORK / "previous" / r["id"]
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("inputs.json", "latest.json"):
            if args.base_url:
                url = f"{args.base_url.rstrip('/')}/data/{r['id']}/{name}"
                try:
                    resp = requests.get(url, timeout=30)
                    if resp.status_code == 200:
                        (dest / name).write_bytes(resp.content)
                        log.info("previous %s: downloaded %s", r["id"], name)
                    else:
                        log.info("previous %s: %s not available (HTTP %s)", r["id"], name, resp.status_code)
                except Exception as e:
                    log.info("previous %s: %s not available (%r)", r["id"], name, e)
            elif (DIST / "data" / r["id"] / name).exists():
                shutil.copy(DIST / "data" / r["id"] / name, dest / name)
                log.info("previous %s: copied local %s", r["id"], name)


def cmd_fetch_forecast(args):
    cfg = _cfg()
    state = _state()
    now = utcnow()
    horizon_end = floor_hour(now) + timedelta(hours=cfg["pipeline"]["forecast"]["horizon_hours"])
    by_chain: dict[tuple, list] = {}
    for r in cfg["regions"]:
        by_chain.setdefault(tuple(r["providers"]["forecast"]), []).append(r)
    any_new = False
    for chain, regions in by_chain.items():
        result, errors = None, []
        for i, name in enumerate(chain):
            prov = FORECAST[name](cfg["pipeline"])
            try:
                run, lead = prov.latest_run(horizon_end)
                reused = _reuse_previous(regions, name, run, lead, cfg) if run else None
                if reused:
                    log.info("[%s] run %s already processed: reusing inputs, no download", name.upper(), iso(run))
                    result, new_run = reused, False
                else:
                    result, new_run = prov.fetch(regions, run, lead, horizon_end), True
                for s in result.values():
                    s.meta["fallback"] = i > 0
                    s.meta["reused"] = not new_run
                any_new = any_new or new_run
                break
            except NotImplementedError as e:
                errors.append(f"{name}: {e}")
            except PipelineError as e:
                tag = e.tag if i == 0 else "FALLBACK"
                print(f"::warning::[{tag}] forecast provider {name} failed: {e}")
                errors.append(f"{name}: {e}")
            except Exception as e:
                print(f"::warning::[{'ECMWF' if i == 0 else 'FALLBACK'}] forecast provider {name} failed: {e!r}")
                errors.append(f"{name}: {e!r}")
        for r in regions:
            if errors:
                for e in errors:
                    _warn(state, r["id"], f"forecast: {e}")
            if result is None:
                prev = _read(WORK / "previous" / r["id"] / "inputs.json")
                if prev and prev.get("forecast"):
                    s = HourlySeries.from_dict(prev["forecast"])
                    s.meta["stale"] = True
                    s.meta["reused"] = True
                    _warn(state, r["id"], f"all forecast providers failed; reusing previous forecast (run {s.run})")
                    _write(WORK / "inputs" / r["id"] / "forecast.json", s.to_dict())
                    continue
                _save_state(state)
                raise NoDataError(f"{r['id']}: no forecast from {list(chain)} and no previous forecast")
            _write(WORK / "inputs" / r["id"] / "forecast.json", result[r["id"]].to_dict())
    state["new_run"] = any_new
    _save_state(state)


def _reuse_previous(regions, provider, run, lead, cfg):
    out = {}
    for r in regions:
        prev = _read(WORK / "previous" / r["id"] / "inputs.json")
        f = (prev or {}).get("forecast")
        if not f or f.get("provider") != provider or f.get("run") != iso(run):
            return None
        m = f.get("meta", {})
        if m.get("resolution") != cfg["pipeline"]["forecast"]["ecmwf"]["resolution"] or m.get("max_lead_h", 0) < lead:
            return None
        out[r["id"]] = HourlySeries.from_dict(f)
    return out


def _fetch_obs(region, cfg, state, lookback_h, chain=None):
    now = utcnow()
    end = floor_hour(now)
    start = end - timedelta(hours=lookback_h)
    for i, name in enumerate(chain or region["providers"]["observation"]):
        try:
            s = OBSERVATION[name](cfg["pipeline"]).fetch(region, start, end)
            s.meta["fallback"] = i > 0
            if not s.meta.get("last_complete_hour"):
                raise ObservationDownloadError("no usable hours returned")
            return s
        except Exception as e:
            tag = "IRM" if i == 0 else "FALLBACK"
            print(f"::warning::[{tag}] observation provider {name} failed for {region['id']}: {e}")
            _warn(state, region["id"], f"observations: {name}: {e}")
    return None


def cmd_fetch_observations(args):
    cfg = _cfg()
    state = _state()
    for r in cfg["regions"]:
        s = _fetch_obs(r, cfg, state, cfg["pipeline"]["observations"]["lookback_hours"])
        p = WORK / "inputs" / r["id"] / "observation.json"
        if s is None:
            if p.exists():
                p.unlink()
            _warn(state, r["id"], "no observations available: wetness spin-up uses forecast hours only")
        else:
            _write(p, s.to_dict())
    _save_state(state)


def cmd_site(args):
    """Copy the static frontend + translations into dist/ (keeps dist/data)."""
    cfg = _cfg()
    DIST.mkdir(parents=True, exist_ok=True)
    for item in DIST.iterdir():
        if item.name != "data":
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copytree(ROOT / "frontend", DIST, dirs_exist_ok=True)
    shutil.copytree(ROOT / "config" / "i18n", DIST / "i18n", dirs_exist_ok=True)
    site_cfg = {
        "repo": os.environ.get("GITHUB_REPOSITORY", ""),
        "branch": cfg["pipeline"]["site"]["repo_branch"],
        "workflow": cfg["pipeline"]["site"]["update_workflow_file"],
        "regions": [{"id": r["id"], "name": r["name"], "timezone": r["timezone"]} for r in cfg["regions"]],
        "modes": list(cfg["scoring"]["modes"]),
        "temp_bands": {m: v["temp_ideal_c"] for m, v in cfg["scoring"]["modes"].items()},
    }
    _write(DIST / "site-config.json", site_cfg, compact=False)
    log.info("site assembled in %s", DIST)


def cmd_score(args):
    cfg = _cfg()
    state = _state()
    now = utcnow()
    index = {"processed_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "regions": []}
    produced = 0
    for r in cfg["regions"]:
        src = WORK / ("previous" if args.from_previous else "inputs") / r["id"]
        if args.from_previous:
            prev = _read(src / "inputs.json") or {}
            fcd, obd = prev.get("forecast"), prev.get("observation")
            prev_latest = _read(src / "latest.json")
            if prev_latest:  # keep the data's own time reference: re-score, do not pretend it is fresh
                now_ref = parse(prev_latest["meta"]["processed_utc"])
            else:
                now_ref = now
        else:
            fcd, obd = _read(src / "forecast.json"), _read(src / "observation.json")
            now_ref = now
        if not fcd and not obd:
            log.warning("%s: no inputs, region published without data", r["id"])
            index["regions"].append({"id": r["id"], "available": False})
            continue
        fc = HourlySeries.from_dict(fcd) if fcd else None
        obs = HourlySeries.from_dict(obd) if obd else None
        extra = {"warnings": state["warnings"].get(r["id"], []) if not args.from_previous else
                 ((_read(src / "latest.json") or {}).get("meta", {}).get("warnings", [])),
                 "forecast_fallback": bool(fc and fc.meta.get("fallback")),
                 "forecast_reused": bool(fc and fc.meta.get("reused")),
                 "forecast_stale": bool(fc and fc.meta.get("stale")),
                 "observation_fallback": bool(obs and obs.meta.get("fallback")),
                 "rescored_from_previous": bool(args.from_previous)}
        out = process_region(r, fc, obs, cfg, now_ref, extra)
        if args.from_previous:
            out["meta"]["rescored_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        _write(DIST / "data" / r["id"] / "latest.json", out)
        _write(DIST / "data" / r["id"] / "inputs.json",
               {"forecast": fcd, "observation": obd, "saved_utc": out["meta"]["processed_utc"]})
        index["regions"].append({"id": r["id"], "available": True, "processed_utc": out["meta"]["processed_utc"]})
        produced += 1
    _write(DIST / "data" / "index.json", index, compact=False)
    log.info("scored %d region(s)", produced)


def cmd_validate(args):
    cfg = _cfg()
    from .tips import validate as validate_tips
    problems = list(validate_tips(cfg["tips"], config.load_i18n()))
    idx = _read(DIST / "data" / "index.json")
    if not (DIST / "index.html").exists():
        problems.append("dist/index.html missing (run `site`)")
    for entry in (idx or {}).get("regions", []):
        if not entry.get("available"):
            continue
        d = _read(DIST / "data" / entry["id"] / "latest.json")
        if d is None:
            problems.append(f"{entry['id']}: latest.json missing")
            continue
        h = d["hourly"]
        n = len(h["t"])
        if n == 0:
            problems.append(f"{entry['id']}: empty timeline")
        for k in ("temp_c", "rh", "precip_mm", "wind_ms", "wet_mm"):
            if len(h[k]) != n:
                problems.append(f"{entry['id']}: hourly.{k} length {len(h[k])} != {n}")
        if h["t"] != sorted(h["t"]):
            problems.append(f"{entry['id']}: timeline not sorted")
        for mode, arr in h["score"].items():
            bad = [s for s in arr if s is not None and not (0 <= s <= 10)]
            if bad:
                problems.append(f"{entry['id']}: {mode} scores out of range {bad[:3]}")
            if all(s is None for s in arr):
                problems.append(f"{entry['id']}: {mode} has no score at all")
        for key in ("processed_utc", "sources"):
            if not d["meta"].get(key):
                problems.append(f"{entry['id']}: meta.{key} missing")
        if not d["meta"].get("model_run_utc") and d["meta"].get("forecast_provider") == "ecmwf":
            problems.append(f"{entry['id']}: ECMWF forecast without model run time")
        size = (DIST / "data" / entry["id"] / "latest.json").stat().st_size
        if size > 2_000_000:
            problems.append(f"{entry['id']}: latest.json unexpectedly large ({size} bytes)")
    if problems:
        raise ValidationError("; ".join(problems))
    log.info("validation OK")


def cmd_history(args):
    cfg = _cfg()
    state = _state()
    if not cfg["pipeline"]["history"]["enabled"]:
        log.info("history disabled in config")
        return
    for r in cfg["regions"]:
        d = _read(DIST / "data" / r["id"] / "latest.json")
        if not d:
            continue
        n_obs = history.append_observed(HISTORY, r["id"], history.observed_rows(d)) \
            if d["meta"].get("observation_provider") == "irm_aws" else 0
        n_fc = 0
        if state.get("new_run") and d["meta"].get("forecast_provider") == "ecmwf" and not d["meta"].get("forecast_reused"):
            n_fc = history.append_forecast(HISTORY, r["id"], history.forecast_rows(d))
        log.info("history %s: +%d observed rows, +%d forecast rows", r["id"], n_obs, n_fc)


def cmd_daily_history(args):
    """Quiet daily run: IRM observations only (a few hundred KB), no forecast download,
    no fallback, no deploy. Writes observed conditions + observed scores for the last 24 h."""
    cfg = _cfg()
    if not cfg["pipeline"]["history"]["enabled"]:
        log.info("history disabled in config; nothing to do")
        return
    state = {"warnings": {}}
    lookback = cfg["pipeline"]["history"]["daily_lookback_hours"]
    now = utcnow()
    since = iso(floor_hour(now) - timedelta(hours=24))
    failed = 0
    for r in cfg["regions"]:
        primary = r["providers"]["observation"][:1]
        if primary != ["irm_aws"]:
            log.info("%s: primary observation provider is %s; daily history only uses real stations", r["id"], primary)
            continue
        s = _fetch_obs(r, cfg, state, lookback, chain=primary)
        if s is None:
            failed += 1
            continue
        pcfg = {**cfg, "pipeline": {**cfg["pipeline"],
                                    "observations": {**cfg["pipeline"]["observations"], "lookback_hours": lookback},
                                    "forecast": {**cfg["pipeline"]["forecast"], "horizon_hours": 0}}}
        out = process_region(r, None, s, pcfg, now)
        n = history.append_observed(HISTORY, r["id"], history.observed_rows(out, since=since))
        log.info("daily history %s: +%d observed rows", r["id"], n)
    if failed:
        raise ObservationDownloadError(f"{failed} region(s) without observations today (nothing written for them)")


def cmd_update(args):
    a = argparse.Namespace(base_url=None, from_previous=False)
    for f in (cmd_fetch_previous, cmd_fetch_forecast, cmd_fetch_observations, cmd_site, cmd_score,
              cmd_validate, cmd_history):
        log.info("== %s", f.__name__.replace("cmd_", ""))
        f(a)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    fp = sub.add_parser("fetch-previous")
    fp.add_argument("--base-url", default=None, help="published site URL (CI); default: local dist/")
    sub.add_parser("fetch-forecast")
    sub.add_parser("fetch-observations")
    sub.add_parser("site")
    sc = sub.add_parser("score")
    sc.add_argument("--from-previous", action="store_true", help="re-score the previously published inputs")
    sub.add_parser("validate")
    sub.add_parser("history")
    sub.add_parser("daily-history")
    sub.add_parser("update")
    args = p.parse_args(argv)
    fn = globals()["cmd_" + args.cmd.replace("-", "_")]
    try:
        fn(args)
    except PipelineError as e:
        print(f"::error::[{e.tag}] {e}")
        log.error("[%s] %s", e.tag, e)
        return e.exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
