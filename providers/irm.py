"""IRM/KMI automatic weather stations (opendata.meteo.be WFS, CC BY 4.0, no key).

Verified in Step 0 (2026-11-12):
  * WFS endpoint https://opendata.meteo.be/service/ows, layers aws:aws_10min and
    aws:aws_station, HTTP 200 without authentication;
  * station list via GetFeature typeNames=aws:aws_station, outputFormat=application/json,
    srsName=EPSG:4326; properties code, name, altitude, date_end (null = active);
  * aws_10min fields (lowercase): code, timestamp, temp_dry_shelter_avg,
    humidity_rel_shelter_avg, precip_quantity, wind_speed_10m, wind_gusts_speed,
    short_wave_from_sky_avg, sun_duration, qc_flags;
  * CQL_FILTER "code=<n> AND timestamp>='<iso>'" works; latency ~1.5-2 h.
UNVERIFIED assumptions (documented in README):
  * timestamp marks the END of the 10-minute interval;
  * units: °C, %, mm per 10 min, m/s, W/m² (mean irradiance);
  * the WFS returns all matching features without paging for <= 72 h of one station.
Data is provisional (qc_flags.validated = false) and labelled as such.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from pipeline.errors import ObservationDownloadError, ParseError
from pipeline.physics import dewpoint_from_rh
from pipeline.timeutil import H, floor_hour, iso, parse

from .base import HourlySeries, ObservationProvider
from .http import get

log = logging.getLogger(__name__)
WFS = "https://opendata.meteo.be/service/ows"

# raw field -> (normalised var, aggregation, plausible min, plausible max)
FIELDS = {
    "temp_dry_shelter_avg": ("temp_c", "mean", -40, 50),
    "humidity_rel_shelter_avg": ("rh", "mean", 0, 105),
    "precip_quantity": ("precip_mm", "sum", 0, 50),
    "wind_speed_10m": ("wind_ms", "mean", 0, 60),
    "short_wave_from_sky_avg": ("sw_wm2", "mean", 0, 1500),
}


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def parse_stations(geojson: dict) -> list[dict]:
    out = []
    for f in geojson.get("features", []):
        c = f["geometry"]["coordinates"]
        # axis order auto-detected (Belgium: lon < 7 < lat)
        lon, lat = (c[0], c[1]) if abs(c[0]) < abs(c[1]) else (c[1], c[0])
        pr = f["properties"]
        out.append({"code": pr.get("code"), "name": pr.get("name"), "altitude": pr.get("altitude"),
                    "date_end": pr.get("date_end"), "lat": lat, "lon": lon})
    return out


def select_stations(stations: list[dict], region: dict) -> list[dict]:
    sc = region["stations"]
    cands = []
    for s in stations:
        if s["date_end"]:
            continue
        d = haversine_km(region["lat"], region["lon"], s["lat"], s["lon"])
        if d <= sc["max_distance_km"]:
            cands.append({**s, "km": round(d, 1)})
    cands.sort(key=lambda s: s["km"])
    return cands[: sc["max_candidates"]]


def aggregate_hourly(records: list[dict], start: datetime, end: datetime, min_records: int) -> dict[str, dict]:
    """10-min records -> hourly rows. Hour [T, T+1h) uses records stamped in (T, T+1h].
    Means need >= min_records valid values; sums need all 6 (no extrapolation)."""
    buckets: dict[str, dict[str, list]] = {}
    for rec in records:
        ts = parse(rec["timestamp"])
        hour = floor_hour(ts - timedelta(seconds=1))
        if not (start <= hour < end):
            continue
        b = buckets.setdefault(iso(hour), {f: [] for f in FIELDS})
        for f, (_, _, lo, hi) in FIELDS.items():
            v = rec.get(f)
            if v is None:
                continue
            if not (lo <= v <= hi):
                continue  # physically implausible -> dropped, not replaced
            b[f].append(v)
    rows = {}
    for key, b in buckets.items():
        row = {}
        for f, (var, agg, _, _) in FIELDS.items():
            vals = b[f]
            if agg == "sum":
                row[var] = sum(vals) if len(vals) >= 6 else None
            else:
                row[var] = sum(vals) / len(vals) if len(vals) >= min_records else None
        if row["rh"] is not None:
            row["rh"] = min(100.0, row["rh"])
        row["dewpoint_c"] = (dewpoint_from_rh(row["temp_c"], row["rh"])
                             if row["temp_c"] is not None and row["rh"] is not None else None)
        row["cloud_pct"] = None  # not observed by AWS
        rows[key] = row
    return rows


class IrmAwsProvider(ObservationProvider):
    name = "irm_aws"
    label = "IRM/KMI AWS (provisional 10-min)"

    def stations(self) -> list[dict]:
        r = get(WFS, dict(service="WFS", version="2.0.0", request="GetFeature", typeNames="aws:aws_station",
                          outputFormat="application/json", srsName="EPSG:4326"), err_cls=ObservationDownloadError)
        try:
            return parse_stations(r.json())
        except Exception as e:
            raise ParseError(f"IRM station list: {e!r}")

    def records(self, code, start: datetime, end: datetime) -> list[dict]:
        cql = (f"code={int(code)} AND timestamp>'{start.strftime('%Y-%m-%dT%H:%M:%SZ')}' "
               f"AND timestamp<='{end.strftime('%Y-%m-%dT%H:%M:%SZ')}'")
        r = get(WFS, dict(service="WFS", version="2.0.0", request="GetFeature", typeNames="aws:aws_10min",
                          outputFormat="application/json", CQL_FILTER=cql), err_cls=ObservationDownloadError)
        try:
            return [f["properties"] for f in r.json().get("features", [])]
        except Exception as e:
            raise ParseError(f"IRM aws_10min for {code}: {e!r}")

    def fetch(self, region, start, end) -> HourlySeries:
        min_rec = self.cfg["observations"]["min_records_per_hour"]
        min_comp = region["stations"]["min_completeness"]
        cands = select_stations(self.stations(), region)
        if not cands:
            raise ObservationDownloadError(f"no active IRM station within {region['stations']['max_distance_km']} km")
        n_hours = int((end - start) / H)
        per_station = []
        for s in cands:
            try:
                recs = self.records(s["code"], start, end)
            except ObservationDownloadError as e:
                log.warning("[IRM] station %s failed: %s", s["code"], e)
                continue
            per_station.append((s, aggregate_hourly(recs, start, end, min_rec)))
        if not per_station:
            raise ObservationDownloadError("all candidate IRM stations failed")

        # Per variable: primary = nearest station meeting the completeness threshold;
        # individual missing hours are filled from the next station (real data, labelled).
        merged: dict[str, dict] = {}
        sources, fill_counts, primary = {}, {}, None
        for var in ("temp_c", "rh", "precip_mm", "wind_ms", "sw_wm2"):
            ranked = []
            for s, rows in per_station:
                have = sum(1 for r in rows.values() if r.get(var) is not None)
                ranked.append((have / max(1, n_hours) >= min_comp, -s["km"], s, rows))
            ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
            first = ranked[0][2]
            primary = primary or first
            used = {}
            t = start
            while t < end:
                k = iso(t)
                for _, _, s, rows in ranked:
                    v = rows.get(k, {}).get(var)
                    if v is not None:
                        merged.setdefault(k, {})[var] = v
                        used[s["code"]] = used.get(s["code"], 0) + 1
                        break
                else:
                    merged.setdefault(k, {})[var] = None
                t += H
            names = {s["code"]: f"{s['code']} {s['name']}" for s, _ in per_station}
            parts = [f"{names[c]} ({n} h)" for c, n in sorted(used.items(), key=lambda x: -x[1])]
            sources[var] = f"{self.label}: " + (", ".join(parts) if parts else "no data")
            fill_counts[var] = used
        for row in merged.values():
            row["cloud_pct"] = None
            # keep dewpoint consistent with the temp/rh actually used
            ok = row.get("temp_c") is not None and row.get("rh") is not None
            row["dewpoint_c"] = dewpoint_from_rh(row["temp_c"], row["rh"]) if ok else None
        sources["dewpoint_c"] = "derived from observed temperature and humidity"
        sources["cloud_pct"] = "not observed"
        obs_hours = [k for k, r in merged.items() if r.get("temp_c") is not None]
        last = max(obs_hours) if obs_hours else None
        return HourlySeries(kind="observation", provider=self.name, label=self.label, hours=merged,
                            sources=sources,
                            meta={"station": {k: primary[k] for k in ("code", "name", "altitude", "km", "lat", "lon")},
                                  "candidates": [{k: s[k] for k in ("code", "name", "km")} for s, _ in per_station],
                                  "last_complete_hour": last, "provisional": True})
