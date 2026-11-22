"""Hourly climbing-conditions score (0-10), components, caps and drivers."""
from __future__ import annotations

from datetime import timedelta

from .physics import clear_sky_ghi, cos_solar_zenith
from .timeutil import parse


def clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def lin(x, x0, x1):
    """0 at x0, 1 at x1 (works for x0 > x1 too), clipped."""
    if x1 == x0:
        return 1.0 if x >= x1 else 0.0
    return clip01((x - x0) / (x1 - x0))


def piecewise(x: float, curve: list) -> float:
    if x <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return curve[-1][1]


def c_temperature(t, lo, hi, falloff):
    if lo <= t <= hi:
        return 1.0
    d = lo - t if t < lo else t - hi
    return clip01(1 - d / falloff)


def c_moisture(rh, spread, m):
    return m["rh_share"] * lin(rh, m["rh_bad"], m["rh_good"]) + \
        (1 - m["rh_share"]) * lin(spread, m["spread_bad_c"], m["spread_good_c"])


def c_wetness(w, very_wet):
    return clip01(1 - w / very_wet)


def c_rain(p0, ahead, heavy):
    return min(clip01(1 - p0 / heavy), clip01(1 - 0.5 * ahead / heavy))


def sun_factor(sw, t_iso, lat, lon):
    """(measured / clear-sky shortwave, is_daylight). Night hours give (0, False)."""
    mid = parse(t_iso) + timedelta(minutes=30)
    cs = clear_sky_ghi(cos_solar_zenith(mid, lat, lon))
    return (0.0, False) if cs < 20 else (clip01(sw / cs), True)


def c_sun(sf, t, lo, hi, cfg):
    side = cfg["cool_side"] if t < (lo + hi) / 2 else cfg["warm_side"]
    return clip01(side["base"] + side["gain"] * sf)


def score_rows(rows: list[dict], mode: str, cfg: dict, lat: float, lon: float) -> None:
    """Adds row["score"][mode], row["comp"][mode], row["drivers"][mode]."""
    m = cfg["modes"][mode]
    lo, hi = m["temp_ideal_c"]
    wts = m["weights"]
    wsum = sum(wts.values())
    rc, wc, caps = cfg["rain"], cfg["wetness"], cfg["caps"]
    peak_lo = max(x for x, y in cfg["wind"]["curve"] if y == max(yy for _, yy in cfg["wind"]["curve"]))
    last_active_rain = None
    for i, row in enumerate(rows):
        row.setdefault("score", {})
        row.setdefault("comp", {})
        row.setdefault("drivers", {})
        need = ("temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "sw_wm2", "wet_mm")
        ahead_rows = rows[i + 1: i + 1 + rc["lookahead_hours"]]
        if any(row.get(k) is None for k in need) or any(r.get("precip_mm") is None for r in ahead_rows):
            row["score"][mode], row["comp"][mode], row["drivers"][mode] = None, None, ["missing"]
            continue
        t, rh = row["temp_c"], row["rh"]
        spread = max(0.0, t - row["dewpoint_c"])
        ahead = sum(r["precip_mm"] for r in ahead_rows)
        sf, daylight = sun_factor(row["sw_wm2"], row["t"], lat, lon)
        row["sun_factor"] = round(sf, 2) if daylight else None
        comp = {
            "temperature": c_temperature(t, lo, hi, cfg["temperature"]["falloff_c"]),
            "moisture": c_moisture(rh, spread, m["moisture"]),
            "wetness": c_wetness(row["wet_mm"], wc["very_wet_mm"]),
            "rain": c_rain(row["precip_mm"], ahead, rc["heavy_mm_h"]),
            "wind": piecewise(row["wind_ms"], cfg["wind"]["curve"]),
            "sun": c_sun(sf, t, lo, hi, cfg["sun"]),
        }
        score = 10.0 * sum(wts[k] * comp[k] for k in comp) / wsum
        drivers = []
        active_rain = row["precip_mm"] >= rc["active_mm_h"]
        if active_rain:
            last_active_rain = i
            if score > caps["active_rain"]:
                score = caps["active_rain"]
                drivers.append("cap_active_rain")
        elif last_active_rain is not None and i - last_active_rain <= rc["recovery_hours"]:
            # Rain onset is an immediate cliff, but recovery is gradual.
            # Residual wetness carries most of the recovery signal; humidity and
            # dew-point spread prevent an unrealistic rebound in saturated air.
            dry_progress = lin(
                row["wet_mm"],
                rc["recovery_wet_mm"],
                0.0,
            )
            recovery = (
                rc["recovery_dry_share"] * dry_progress
                + (1.0 - rc["recovery_dry_share"]) * comp["moisture"]
            )
            recovery_cap = caps["active_rain"] + (10.0 - caps["active_rain"]) * recovery
            score = min(score, recovery_cap)
        if row["wet_mm"] >= wc["very_wet_mm"] and score > caps["very_wet"]:
            score = min(score, caps["very_wet"])
            drivers.append("cap_very_wet")
        losses = []
        for k, c in comp.items():
            loss = 10.0 * wts[k] / wsum * (1 - c)
            name = k
            if k == "temperature":
                name = "temperature_cold" if t < lo else "temperature_warm"
            elif k == "wind":
                name = "wind_strong" if row["wind_ms"] > peak_lo else "wind_calm"
            losses.append((loss, name, k))
        losses.sort(reverse=True)
        for loss, name, k in losses:
            if len(drivers) >= cfg["drivers"]["max"]:
                break
            if loss < cfg["drivers"]["min_loss"]:
                break
            if (k == "rain" and "cap_active_rain" in drivers) or (k == "wetness" and "cap_very_wet" in drivers):
                continue
            drivers.append(name)
        row["score"][mode] = round(score, 1)
        row["comp"][mode] = {k: round(v, 2) for k, v in comp.items()}
        row["drivers"][mode] = drivers
