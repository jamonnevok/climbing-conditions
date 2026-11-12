"""Simple stateful wet-rock index (mm of water film on the rock).

Each hour:  W = clip(W + precip - drying, 0, max_mm)
  drying [mm/h] = k_vpd * VPD[kPa] * (1 + k_wind * min(wind, wind_cap)) + k_rad * SW[W/m2] / 1000
This is a deliberately simple, calibratable proxy (see README limitations): it treats
the region as one exposed, horizontal-ish surface and ignores seepage and shade.
"""
from __future__ import annotations

from .physics import vpd_kpa


def drying_rate(t_c, td_c, wind_ms, sw_wm2, cfg) -> float:
    w = min(wind_ms, cfg["wind_cap_ms"])
    return (cfg["k_vpd"] * vpd_kpa(t_c, td_c) * (1 + cfg["k_wind"] * w)
            + cfg["k_rad"] * max(0.0, sw_wm2) / 1000.0)


def simulate(rows: list[dict], cfg: dict, initial_mm: float = 0.0) -> None:
    """Adds row["wet_mm"] (None when inputs are missing: the state is then carried
    unchanged and the hour is flagged, never filled with invented drying)."""
    w = initial_mm
    for row in rows:
        need = (row.get("precip_mm"), row.get("temp_c"), row.get("dewpoint_c"), row.get("wind_ms"), row.get("sw_wm2"))
        if any(v is None for v in need):
            row["wet_mm"] = None
            continue
        p, t, td, wind, sw = need
        w = min(cfg["max_mm"], max(0.0, w + p - drying_rate(t, td, wind, sw, cfg)))
        row["wet_mm"] = w
