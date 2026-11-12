"""Merge observations (past) and forecast (future) into one continuous hourly timeline."""
from __future__ import annotations

from datetime import datetime

from providers.base import VARS, HourlySeries
from .timeutil import H, iso

FILLABLE = ("temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "sw_wm2")


def build(obs: HourlySeries | None, fc: HourlySeries | None, start: datetime, end: datetime) -> list[dict]:
    """Rows for [start, end). Observed rows are used up to the last complete observed
    hour; individual missing observed variables are taken from the forecast for that
    hour and listed in row["fill"]. Hours with neither source stay empty (kind "missing")."""
    obs_last = obs.meta.get("last_complete_hour") if obs else None
    rows, t = [], start
    while t < end:
        k = iso(t)
        o = obs.hours.get(k) if obs and obs_last and k <= obs_last else None
        f = fc.hours.get(k) if fc else None
        if o is not None and o.get("temp_c") is not None:
            row = {"t": k, "kind": "obs_model" if obs.modelled else "obs", "fill": []}
            for v in VARS:
                row[v] = o.get(v)
                if row[v] is None and f is not None and f.get(v) is not None:
                    row[v] = f[v]
                    if v in FILLABLE:
                        row["fill"].append(v)
            row["interp"] = False
        elif f is not None:
            row = {"t": k, "kind": "fc", "fill": [], "interp": bool(f.get("interp"))}
            for v in VARS:
                row[v] = f.get(v)
        else:
            row = {"t": k, "kind": "missing", "fill": [], "interp": False}
            for v in VARS:
                row[v] = None
        rows.append(row)
        t += H
    return rows
