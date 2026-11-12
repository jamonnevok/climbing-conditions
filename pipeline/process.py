"""From normalised inputs to the compact JSON consumed by the frontend."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from providers.base import VARS, HourlySeries
from . import daily, tips, timeline, wetness
from .errors import ScoringError
from .scoring import score_rows
from .timeutil import H, floor_hour, iso, parse

SCHEMA_VERSION = 1
N_DAYS = 5


def _r(v, n=1):
    return None if v is None else round(v, n)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def build_rows(region, fc, obs, scoring_cfg, now, lookback_h, horizon_h):
    start = floor_hour(now) - timedelta(hours=lookback_h)
    end = floor_hour(now) + timedelta(hours=horizon_h)
    if fc and fc.hours:
        end = min(end, parse(max(fc.hours)) + H)
    elif obs and obs.meta.get("last_complete_hour"):
        end = parse(obs.meta["last_complete_hour"]) + H
    rows = timeline.build(obs, fc, start, end)
    wetness.simulate(rows, scoring_cfg["wetness"])
    for mode in scoring_cfg["modes"]:
        score_rows(rows, mode, scoring_cfg, region["lat"], region["lon"])
    return rows


def _day_block(rows, idx, ref_idx, mode, mode_cfg, scfg, tz, all_windows, tips_cfg, now):
    dcfg = scfg["daily"]
    scores = [rows[i]["score"][mode] for i in idx]
    known = [s for s in scores if s is not None]
    day_score = _r(_mean(known)) if idx and len(known) >= len(idx) / 2 else None
    ref_rows = [rows[i] for i in ref_idx]
    window = daily.best_window(ref_rows, mode, dcfg["window_lengths"], dcfg["window_tolerance"])
    drv = Counter(d for r in ref_rows for d in (r["drivers"].get(mode) or []) if d != "missing")
    block = {"score": day_score, "partial": bool(idx) and len(known) < len(idx),
             "best_window": window, "drivers": [d for d, _ in drv.most_common(2)], "tips": [],
             "remaining": bool(ref_idx)}
    if not ref_idx:
        return block
    i0 = ref_idx[0]
    lo, hi = mode_cfg["temp_ideal_c"]
    prev = [rows[j]["precip_mm"] for j in range(max(0, i0 - 48), i0)]
    prev_known = [p for p in prev if p is not None]
    wet0 = next((rows[j]["wet_mm"] for j in range(i0, -1, -1) if rows[j].get("wet_mm") is not None), None)
    htd, dry_at = daily.hours_to_dry(rows, i0, scfg["wetness"]["dry_ok_mm"])
    spreads = [r["temp_c"] - r["dewpoint_c"] for r in ref_rows
               if r.get("temp_c") is not None and r.get("dewpoint_c") is not None]
    later = [w for w in all_windows if w and w["start"] >= rows[i0]["t"]
             and not (window and w["start"] == window["start"])]
    better = max(later, key=lambda w: w["score"], default=None)
    has_better = bool(better and better["score"] >= 5 and (day_score is None or better["score"] >= day_score + 1.5))
    facts = {
        "day_score": day_score,
        "t_mean_c": _mean(r["temp_c"] for r in ref_rows),
        "t_max_c": max((r["temp_c"] for r in ref_rows if r["temp_c"] is not None), default=None),
        "rh_mean": _mean(r["rh"] for r in ref_rows),
        "spread_mean_c": _mean(spreads),
        "wind_mean_ms": _mean(r["wind_ms"] for r in ref_rows),
        "wind_max_ms": max((r["wind_ms"] for r in ref_rows if r["wind_ms"] is not None), default=None),
        "rain_prev48_mm": sum(prev_known) if len(prev_known) >= 36 else None,
        "wet_start_mm": wet0,
        "hours_to_dry": htd,
        "sun_fraction": _mean(r.get("sun_factor") for r in ref_rows),
        "has_better_window": has_better,
        "temp_lo": lo, "temp_hi": hi,
        "dry_ok_mm": scfg["wetness"]["dry_ok_mm"],
    }
    params = {"hours_to_dry": htd, "dry_at": dry_at}
    if has_better:
        params.update(window_day=better["start"], window_start=better["start"],
                      window_end=better["end"], window_score=better["score"])
    block["tips"] = tips.select(tips_cfg, facts, params)
    block["facts"] = {k: (_r(v, 2) if isinstance(v, float) else v) for k, v in facts.items()}
    return block


def process_region(region, fc: HourlySeries | None, obs: HourlySeries | None, cfg: dict, now: datetime,
                   extra_meta: dict | None = None) -> dict:
    try:
        return _process_region(region, fc, obs, cfg, now, extra_meta)
    except ScoringError:
        raise
    except Exception as e:
        raise ScoringError(f"{region['id']}: {e!r}") from e


def _process_region(region, fc, obs, cfg, now, extra_meta):
    scfg, pcfg, tips_cfg = cfg["scoring"], cfg["pipeline"], cfg["tips"]
    tz = ZoneInfo(region["timezone"])
    rows = build_rows(region, fc, obs, scfg, now, pcfg["observations"]["lookback_hours"],
                      pcfg["forecast"]["horizon_hours"])

    hours = scfg["daily"]["hours_local"]
    groups = daily.day_groups(rows, tz, now, N_DAYS)
    now_h = iso(floor_hour(now))
    days = {}
    for mode, mcfg in scfg["modes"].items():
        # best window per day (from now for today) for "best upcoming window" tips
        windows = []
        for date, idx in groups:
            ref = [rows[i] for i in idx if daily.is_daytime(rows[i]["t"], tz, hours) and rows[i]["t"] >= now_h]
            windows.append(daily.best_window(ref, mode, scfg["daily"]["window_lengths"],
                                             scfg["daily"]["window_tolerance"]))
        out = []
        for (date, idx), w in zip(groups, windows):
            day_idx = [i for i in idx if daily.is_daytime(rows[i]["t"], tz, hours)]
            ref_idx = [i for i in day_idx if rows[i]["t"] >= now_h]
            b = _day_block(rows, day_idx, ref_idx, mode, mcfg, scfg, tz, windows, tips_cfg, now)
            b["date"] = date.isoformat()
            out.append(b)
        days[mode] = out

    now_row = next((r for r in rows if r["t"] == now_h), None)
    hourly = {"t": [r["t"] for r in rows], "kind": [r["kind"] for r in rows],
              "fill": [r["fill"] for r in rows]}
    for v in VARS:
        hourly[v] = [_r(r[v], 2 if v == "precip_mm" else 1) for r in rows]
    hourly["wet_mm"] = [_r(r.get("wet_mm"), 2) for r in rows]
    hourly["score"] = {m: [r["score"][m] for r in rows] for m in scfg["modes"]}
    hourly["drivers"] = {m: [r["drivers"][m] for r in rows] for m in scfg["modes"]}

    obs_rows = [r["t"] for r in rows if r["kind"].startswith("obs")]
    sources = {}
    for v in VARS:
        sources[v] = {"observed": obs.sources.get(v) if obs else None, "forecast": fc.sources.get(v) if fc else None}
    meta = {
        "schema": SCHEMA_VERSION,
        "processed_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_run_utc": fc.run if fc else None,
        "forecast_provider": fc.provider if fc else None,
        "forecast_label": fc.label if fc else None,
        "forecast_meta": fc.meta if fc else None,
        "observation_provider": obs.provider if obs else None,
        "observation_label": obs.label if obs else None,
        "observation_modelled": bool(obs and obs.modelled),
        "observation_last_utc": iso(parse(obs_rows[-1]) + H) if obs_rows else None,
        "observation_provisional": bool(obs and obs.meta.get("provisional")),
        "station": obs.meta.get("station") if obs else None,
        "timeline_start_utc": rows[0]["t"] if rows else None,
        "timeline_end_utc": iso(parse(rows[-1]["t"]) + H) if rows else None,
        "sources": sources,
        "warnings": [],
    }
    if extra_meta:
        meta.update(extra_meta)
    return {"region": {k: region[k] for k in ("id", "country", "name", "lat", "lon", "timezone")},
            "meta": meta,
            "now": {m: {"t": now_h, "score": now_row["score"][m] if now_row else None,
                        "drivers": now_row["drivers"][m] if now_row else [],
                        "kind": now_row["kind"] if now_row else None} for m in scfg["modes"]},
            "days": days, "hourly": hourly}
