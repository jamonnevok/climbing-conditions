"""Compact calibration history (CSV, one file per region per month).

history/observed/<region>/<YYYY-MM>.csv  - observed hours + observed scores
history/forecast/<region>/<YYYY-MM>.csv  - one row per forecast hour per processed run
Rows are de-duplicated on their key; existing rows are never rewritten.
"""
from __future__ import annotations

import csv
from pathlib import Path

OBS_COLS = ["t", "provider", "station", "temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "sw_wm2",
            "wet_mm", "score_comfort", "score_performance", "fill"]
FC_COLS = ["run", "t", "lead_h", "provider", "temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "cloud_pct",
           "sw_wm2", "wet_mm", "score_comfort", "score_performance"]


def _append(path: Path, cols: list[str], rows: list[dict], key) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            existing = {key(r) for r in csv.DictReader(f)}
    new = [r for r in rows if key({k: str(v) for k, v in r.items()}) not in existing]
    if not new:
        return 0
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in sorted(new, key=lambda r: (str(r.get("run", "")), r["t"])):
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    return len(new)


def _fmt(v, n):
    return None if v is None else round(v, n)


def observed_rows(out: dict, since: str | None = None) -> list[dict]:
    h, m = out["hourly"], out["meta"]
    st = m.get("station") or {}
    rows = []
    for i, t in enumerate(h["t"]):
        if not h["kind"][i].startswith("obs") or (since and t < since) or h["wet_mm"][i] is None:
            continue
        rows.append({"t": t, "provider": m["observation_provider"], "station": st.get("code", ""),
                     **{k: h[k][i] for k in ("temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "sw_wm2", "wet_mm")},
                     "score_comfort": h["score"]["comfort"][i], "score_performance": h["score"]["performance"][i],
                     "fill": "|".join(h["fill"][i])})
    return rows


def forecast_rows(out: dict) -> list[dict]:
    from .timeutil import parse
    h, m = out["hourly"], out["meta"]
    run = m.get("model_run_utc") or ""
    rows = []
    for i, t in enumerate(h["t"]):
        if h["kind"][i] != "fc":
            continue
        lead = int((parse(t) - parse(run)).total_seconds() // 3600) if run else ""
        rows.append({"run": run, "t": t, "lead_h": lead, "provider": m["forecast_provider"],
                     **{k: h[k][i] for k in ("temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "cloud_pct",
                                             "sw_wm2", "wet_mm")},
                     "score_comfort": h["score"]["comfort"][i], "score_performance": h["score"]["performance"][i]})
    return rows


def append_observed(root: Path, region_id: str, rows: list[dict]) -> int:
    n = 0
    for month in sorted({r["t"][:7] for r in rows}):
        n += _append(root / "observed" / region_id / f"{month}.csv", OBS_COLS,
                     [r for r in rows if r["t"][:7] == month], key=lambda r: r["t"])
    return n


def append_forecast(root: Path, region_id: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    month = rows[0]["run"][:7] or rows[0]["t"][:7]
    return _append(root / "forecast" / region_id / f"{month}.csv", FC_COLS, rows,
                   key=lambda r: (r["run"], r["t"]))
