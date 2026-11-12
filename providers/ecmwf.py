"""ECMWF IFS open data (anonymous, CC-BY-4.0) via the official `ecmwf-opendata` client.

Verified in Step 0 (2026-11-12, GitHub-hosted runner):
  * Client(source="ecmwf", model="ifs", resol="0p25").latest()/retrieve() work anonymously;
  * params 2t, 2d, tp, 10u, 10v, tcc, ssrd present; tp & ssrd stepType=accum
    (accumulated from run start); 2t/2d in K; tcc 0-1; global 1440x721 grid at 0.25°;
  * resol="0p1" with levtype="sfc" works;
  * the 06 UTC run reached step 120 h.
Not verified: whether 06/18 UTC runs reach beyond 120 h (docs say 90 h) -> handled by
probing availability with Client.latest() before downloading.
"""
from __future__ import annotations

import logging
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone

from pipeline.errors import ForecastDownloadError, ParseError
from pipeline.physics import rh_from_dewpoint, wind_speed
from pipeline.resample import deaccumulate, to_hourly
from pipeline.timeutil import iso

from .base import ForecastProvider, HourlySeries

log = logging.getLogger(__name__)
PARAMS = ["2t", "2d", "tp", "10u", "10v", "tcc", "ssrd"]


def _ceil_step(hours: float, step: int) -> int:
    return int(math.ceil(hours / step) * step)


class EcmwfProvider(ForecastProvider):
    name = "ecmwf"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        e = cfg["forecast"]["ecmwf"]
        self.resol = e["resolution"]
        self.source = e["source"]
        self.model = e["model"]
        self.step = e["step_hours"]
        self.max_step = e["max_step_hours"]
        self.retries = e["retries"]
        self.retry_wait = e["retry_wait_seconds"]
        res_label = {"0p25": "0.25°", "0p1": "0.1°"}.get(self.resol, self.resol)
        self.label = f"ECMWF IFS {res_label} open data"

    # -- helpers ----------------------------------------------------------
    def _client(self):
        try:
            from ecmwf.opendata import Client
        except ImportError as e:  # pragma: no cover
            raise ForecastDownloadError(f"ecmwf-opendata not installed: {e}")
        return Client(source=self.source, model=self.model, resol=self.resol)

    def _req(self, **kw) -> dict:
        req = dict(type="fc", stream="oper", **kw)
        if self.resol == "0p1":
            req["levtype"] = "sfc"  # verified in Step 0 for 0p1
        return req

    def _latest_with_step(self, client, step: int) -> datetime:
        d = client.latest(**self._req(param="2t", step=step))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d

    # -- interface --------------------------------------------------------
    def latest_run(self, horizon_end: datetime):
        """Newest run whose files reach the step needed to cover horizon_end.
        If no recent run covers it, the newest run is used with a shorter horizon."""
        client = self._client()
        try:
            newest = self._latest_with_step(client, 0)
        except Exception as e:
            raise ForecastDownloadError(f"cannot determine latest ECMWF run: {e!r}")
        for k in range(3):
            run = newest - timedelta(hours=6 * k)
            need = min(self.max_step, _ceil_step((horizon_end - run).total_seconds() / 3600, self.step))
            try:
                found = self._latest_with_step(client, need)
            except Exception as e:
                log.info("[ECMWF] no run with step %s: %r", need, e)
                continue
            if found == run:
                log.info("[ECMWF] using run %s (lead up to %s h)", iso(run), need)
                return run, need
        # newest run is always available to 90 h per ECMWF documentation
        log.warning("[ECMWF] no recent run covers the full horizon; using %s to 90 h", iso(newest))
        return newest, min(90, self.max_step)

    def fetch(self, regions, run, max_lead, horizon_end):
        client = self._client()
        steps = list(range(0, max_lead + 1, self.step))
        with tempfile.TemporaryDirectory(prefix="ecmwf-") as tmp:
            target = os.path.join(tmp, "fc.grib2")
            last_err = None
            for attempt in range(1, self.retries + 1):
                try:
                    client.retrieve(**self._req(param=PARAMS, step=steps), date=run.replace(tzinfo=None), target=target)
                    last_err = None
                    break
                except Exception as e:  # network / not yet published
                    last_err = e
                    log.warning("[ECMWF] download attempt %d/%d failed: %r", attempt, self.retries, e)
                    if attempt < self.retries:
                        import time
                        time.sleep(self.retry_wait * attempt)
            if last_err is not None:
                raise ForecastDownloadError(f"ECMWF download failed for run {iso(run)}: {last_err!r}")
            size_mb = os.path.getsize(target) / 1e6
            log.info("[ECMWF] downloaded %.1f MB for %d steps", size_mb, len(steps))
            points = self._decode(target, regions)
        # GRIB file is deleted with the temporary directory here.
        out = {}
        for r in regions:
            out[r["id"]] = self._to_series(r, run, points[r["id"]], max_lead, size_mb)
        return out

    def _decode(self, path: str, regions: list[dict]) -> dict:
        try:
            import eccodes
        except ImportError as e:  # pragma: no cover
            raise ParseError(f"eccodes not installed: {e}")
        pts = {r["id"]: {p: {} for p in PARAMS} for r in regions}
        n = 0
        try:
            with open(path, "rb") as f:
                while (h := eccodes.codes_grib_new_from_file(f)) is not None:
                    try:
                        sn = eccodes.codes_get(h, "shortName")
                        if sn not in PARAMS:
                            continue
                        step = int(eccodes.codes_get(h, "endStep"))
                        for r in regions:
                            near = eccodes.codes_grib_find_nearest(h, r["lat"], r["lon"], npoints=4)
                            pts[r["id"]][sn][step] = _idw(near)
                        n += 1
                    finally:
                        eccodes.codes_release(h)
        except Exception as e:
            raise ParseError(f"GRIB decoding failed: {e!r}")
        if n == 0:
            raise ParseError("GRIB file contained no expected messages")
        return pts

    def _to_series(self, region, run, p, max_lead, size_mb) -> HourlySeries:
        k = 273.15
        missing = [v for v in PARAMS if not p[v]]
        if missing:
            raise ParseError(f"ECMWF parameters missing after decode: {missing}")
        instants = {
            "temp_c": {s: v - k for s, v in p["2t"].items()},
            "dewpoint_c": {s: v - k for s, v in p["2d"].items()},
            "wind_ms": {s: wind_speed(p["10u"][s], p["10v"][s]) for s in p["10u"] if s in p["10v"]},
            "cloud_pct": {s: 100.0 * v for s, v in p["tcc"].items()},
        }
        totals = {
            "precip_mm": {s: v * 1000.0 for s, v in deaccumulate(p["tp"]).items()},  # m -> mm
            "sw_j": deaccumulate(p["ssrd"]),                                          # J/m2
        }
        rows = to_hourly(run, instants, totals, region["lat"], region["lon"], max_lead)
        for row in rows.values():
            if row["temp_c"] is not None and row["dewpoint_c"] is not None:
                row["dewpoint_c"] = min(row["dewpoint_c"], row["temp_c"])
                row["rh"] = rh_from_dewpoint(row["temp_c"], row["dewpoint_c"])
            else:
                row["rh"] = None
        src = {v: self.label for v in ("temp_c", "dewpoint_c", "precip_mm", "wind_ms", "cloud_pct", "sw_wm2")}
        src["rh"] = f"derived from {self.label} 2t/2d"
        return HourlySeries(kind="forecast", provider=self.name, label=self.label, hours=rows, run=iso(run),
                            sources=src, meta={"resolution": self.resol, "max_lead_h": max_lead,
                                               "download_mb": round(size_mb, 1), "time_step_h": self.step})


def _idw(near) -> float:
    """Inverse-distance weighting of the 4 nearest grid points."""
    vals = [(getattr(x, "value", None) if not isinstance(x, dict) else x["value"],
             getattr(x, "distance", None) if not isinstance(x, dict) else x["distance"]) for x in near]
    for v, d in vals:
        if d is not None and d < 1e-6:
            return float(v)
    ws = [(v, 1.0 / d) for v, d in vals if d]
    tot = sum(w for _, w in ws)
    return float(sum(v * w for v, w in ws) / tot)
