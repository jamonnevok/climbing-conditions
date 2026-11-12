"""Open-Meteo fallback (re-serves ECMWF IFS). Free for NON-COMMERCIAL use only,
no key; limits 10 000 calls/day (see README). This app makes <= 2 calls per run.

Verified in Step 0: /v1/forecast with models=ecmwf_ifs025, hourly variables
temperature_2m, dew_point_2m, relative_humidity_2m, precipitation, wind_speed_10m,
cloud_cover, shortwave_radiation, wind_speed_unit=ms, timezone=UTC -> 144 hourly rows.
UNVERIFIED (from Open-Meteo documentation, not tested in Step 0):
  * `past_days` parameter (used for the observation fallback);
  * precipitation / shortwave_radiation are totals/means over the PRECEDING hour;
  * the exact model run used is not exposed -> run time reported as unknown.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from pipeline.errors import FallbackError, ParseError
from pipeline.timeutil import H, iso, parse

from .base import ForecastProvider, HourlySeries, ObservationProvider
from .http import get

URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = ["temperature_2m", "dew_point_2m", "relative_humidity_2m", "precipitation",
          "wind_speed_10m", "cloud_cover", "shortwave_radiation"]


def parse_response(j: dict, start: datetime, end: datetime) -> dict[str, dict]:
    """Convert Open-Meteo hourly arrays to hour-start rows for [start, end)."""
    try:
        h = j["hourly"]
        times = [parse(t) for t in h["time"]]
        idx = {t: i for i, t in enumerate(times)}

        def val(name, t):
            i = idx.get(t)
            return None if i is None else h[name][i]

        rows = {}
        t = start
        while t < end:
            t1 = t + H
            def mid(name):
                a, b = val(name, t), val(name, t1)
                return None if a is None or b is None else (a + b) / 2
            row = {
                "temp_c": mid("temperature_2m"),
                "dewpoint_c": mid("dew_point_2m"),
                "rh": mid("relative_humidity_2m"),
                # preceding-hour values are labelled at the hour END
                "precip_mm": val("precipitation", t1),
                "sw_wm2": val("shortwave_radiation", t1),
                "wind_ms": mid("wind_speed_10m"),
                "cloud_pct": mid("cloud_cover"),
                "interp": False,
            }
            if any(v is not None for k, v in row.items() if k != "interp"):
                rows[iso(t)] = row
            t = t1
        return rows
    except (KeyError, TypeError, ValueError) as e:
        raise ParseError(f"Open-Meteo response: {e!r}")


def _request(cfg, region, **extra) -> dict:
    params = dict(latitude=region["lat"], longitude=region["lon"], hourly=",".join(HOURLY),
                  models=cfg["forecast"]["openmeteo"]["model"], wind_speed_unit="ms", timezone="UTC", **extra)
    try:
        return get(URL, params, err_cls=FallbackError).json()
    except ValueError as e:
        raise ParseError(f"Open-Meteo returned non-JSON: {e!r}")


class OpenMeteoForecast(ForecastProvider):
    name = "openmeteo"

    @property
    def label(self):
        return f"Open-Meteo ({self.cfg['forecast']['openmeteo']['model']}, ECMWF IFS)"

    def latest_run(self, horizon_end):
        return None, None

    def fetch(self, regions, run, max_lead, horizon_end):
        out = {}
        for r in regions:
            j = _request(self.cfg, r, forecast_days=6)
            first = parse(j["hourly"]["time"][0])
            rows = parse_response(j, first, horizon_end)
            src = {v: self.label for v in ("temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "cloud_pct", "sw_wm2")}
            out[r["id"]] = HourlySeries(kind="forecast", provider=self.name, label=self.label, hours=rows,
                                        run=None, sources=src, meta={"run_note": "model run not exposed by Open-Meteo"})
        return out


class OpenMeteoPast(ObservationProvider):
    """Fallback for observations: MODELLED past hours, clearly labelled as such."""
    name = "openmeteo_past"

    def fetch(self, region, start, end):
        days = max(1, int((end - start) / timedelta(days=1)) + 1)
        j = _request(self.cfg, region, past_days=days, forecast_days=1)  # past_days: UNVERIFIED
        rows = parse_response(j, start, end)
        label = f"Open-Meteo past hours (modelled, {self.cfg['forecast']['openmeteo']['model']})"
        src = {v: label for v in ("temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "cloud_pct", "sw_wm2")}
        last = max(rows) if rows else None
        return HourlySeries(kind="observation", provider=self.name, label=label, hours=rows, sources=src,
                            modelled=True, meta={"station": None, "last_complete_hour": last, "provisional": False})
