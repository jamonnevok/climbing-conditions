"""Synthetic inputs for tests ONLY (never used by the production pipeline)."""
from datetime import datetime, timedelta, timezone

from providers.base import HourlySeries
from pipeline.timeutil import iso

NOW = datetime(2026, 11, 12, 15, 20, tzinfo=timezone.utc)


def row(temp=10.0, td=4.0, rh=None, precip=0.0, wind=3.0, cloud=50.0, sw=100.0):
    from pipeline.physics import rh_from_dewpoint
    return {"temp_c": temp, "dewpoint_c": td, "rh": rh if rh is not None else rh_from_dewpoint(temp, td),
            "precip_mm": precip, "wind_ms": wind, "cloud_pct": cloud, "sw_wm2": sw, "interp": False}


def series(kind, start, n, provider="test", **kw):
    hours = {iso(start + timedelta(hours=i)): row(**kw) for i in range(n)}
    meta = {"last_complete_hour": iso(start + timedelta(hours=n - 1))} if kind == "observation" else {}
    return HourlySeries(kind=kind, provider=provider, label=f"{provider} label", hours=hours,
                        run=iso(start) if kind == "forecast" else None,
                        sources={v: f"{provider} label" for v in ("temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "cloud_pct", "sw_wm2")},
                        meta=meta)
