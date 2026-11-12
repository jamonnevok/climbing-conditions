"""Turn 3-hourly model output into hourly rows (hour-start convention)."""
from __future__ import annotations

from datetime import datetime, timedelta

from .physics import clear_sky_ghi, cos_solar_zenith
from .timeutil import H, iso


def deaccumulate(cum: dict[int, float]) -> dict[int, float]:
    """Accumulated-from-run-start values {step: value} -> per-interval totals
    {end_step: total over (previous_step, end_step]}. Small negative differences
    (packing noise) are clipped to 0."""
    out, prev_step, prev = {}, None, None
    for s in sorted(cum):
        if prev_step is not None and cum[s] is not None and prev is not None:
            out[s] = max(0.0, cum[s] - prev)
        prev_step, prev = s, cum[s]
    return out


def interp_instant(values: dict[int, float], lead_h: float) -> float | None:
    """Linear interpolation of an instantaneous field at fractional lead time."""
    steps = sorted(s for s, v in values.items() if v is not None)
    if not steps or lead_h < steps[0] or lead_h > steps[-1]:
        return None
    for a, b in zip(steps, steps[1:]):
        if a <= lead_h <= b:
            w = (lead_h - a) / (b - a)
            return values[a] * (1 - w) + values[b] * w
    return values[steps[-1]] if lead_h == steps[-1] else None


def to_hourly(run: datetime, instants: dict[str, dict[int, float]], interval_totals: dict[str, dict[int, float]],
              lat: float, lon: float, last_step: int) -> dict[str, dict]:
    """Build hourly rows from run start up to last_step.

    instants: var -> {step: value}  (interpolated at mid-hour)
    interval_totals: {"precip_mm": {end_step: mm}, "sw_j": {end_step: J/m2}}
      precipitation is spread evenly over the hours of its interval;
      radiation energy is spread in proportion to clear-sky irradiance, which
      conserves the model's interval total while giving a realistic daily shape.
    """
    rows = {}
    for h in range(0, last_step):
        start = run + timedelta(hours=h)
        mid = h + 0.5
        row = {k: interp_instant(v, mid) for k, v in instants.items()}
        # interval containing this hour: (end-Δ, end]
        ends = sorted(interval_totals.get("precip_mm", {}) or interval_totals.get("sw_j", {}))
        end = next((e for e in ends if e > h), None)
        prev_end = max([0] + [e for e in ends if e < (end or 0)])
        if end is None:
            row["precip_mm"] = None
            row["sw_wm2"] = None
        else:
            n = end - prev_end
            p = interval_totals.get("precip_mm", {}).get(end)
            row["precip_mm"] = None if p is None else p / n
            e_j = interval_totals.get("sw_j", {}).get(end)
            if e_j is None:
                row["sw_wm2"] = None
            else:
                weights = []
                for k in range(prev_end, end):
                    t = run + timedelta(hours=k + 0.5)
                    weights.append(clear_sky_ghi(cos_solar_zenith(t, lat, lon)))
                tot = sum(weights)
                share = weights[h - prev_end] / tot if tot > 0 else 1.0 / n
                row["sw_wm2"] = e_j * share / 3600.0
        row["interp"] = True
        rows[iso(start)] = row
    return rows
