#!/usr/bin/env python3
"""Step 0 live verification of all data sources (anonymous, no API key).

Run locally (`python scripts/step0_verify.py`) or via the manual `step0-verify`
workflow. Prints a JSON report and writes step0_report.json. Exit code 1 if any
check failed. Re-run it whenever a provider seems to have changed.
"""
import json
import math
import os
import re
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta, timezone

import requests

NAMUR = (50.47, 4.87)
WANTED = ["2t", "2d", "tp", "10u", "10v", "tcc", "ssrd"]
REPORT = {"generated_utc": datetime.now(timezone.utc).isoformat(), "checks": {}}
UA = {"User-Agent": "climbing-conditions-advisor-step0/1.0"}
WFS = "https://opendata.meteo.be/service/ows"


def check(name):
    def deco(fn):
        def run():
            t0 = time.time()
            try:
                REPORT["checks"][name] = {"ok": True, **(fn() or {})}
            except Exception as e:
                REPORT["checks"][name] = {"ok": False, "error": repr(e), "trace": traceback.format_exc()[-800:]}
            REPORT["checks"][name]["seconds"] = round(time.time() - t0, 1)
        return run
    return deco


@check("ecmwf_client_0p25")
def ecmwf_client():
    from ecmwf.opendata import Client
    out = {}
    c = Client(source="ecmwf", model="ifs", resol="0p25")
    req = dict(type="fc", stream="oper", param=WANTED)
    latest_any = c.latest(**req, step=0)
    latest_long = c.latest(**req, step=120)
    out["latest_run_any"] = latest_any.isoformat()
    out["latest_run_reaching_120h"] = latest_long.isoformat()
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "t.grib2")
        c.retrieve(**req, step=[0, 3, 6, 120], date=latest_long, target=target)
        out["bytes_for_7_params_x_4_steps"] = os.path.getsize(target)
        import eccodes
        found, meta = set(), {}
        with open(target, "rb") as f:
            while (h := eccodes.codes_grib_new_from_file(f)) is not None:
                sn = eccodes.codes_get(h, "shortName")
                found.add(sn)
                meta.setdefault(sn, {k: eccodes.codes_get(h, k) for k in ("units", "stepType", "Ni", "Nj")})
                eccodes.codes_release(h)
        out["shortNames_found"] = sorted(found)
        out["missing"] = sorted(set(WANTED) - found)
        out["field_meta"] = meta
    return out


@check("ecmwf_direct_index_fallback")
def ecmwf_direct():
    now = datetime.now(timezone.utc)
    for back in range(0, 48, 6):
        run = (now - timedelta(hours=back)).replace(minute=0, second=0, microsecond=0)
        run = run.replace(hour=run.hour - run.hour % 6)
        url = (f"https://data.ecmwf.int/forecasts/{run:%Y%m%d}/{run:%H}z/ifs/0p25/oper/"
               f"{run:%Y%m%d%H%M%S}-0h-oper-fc.index")
        if requests.head(url, headers=UA, timeout=30).status_code == 200:
            idx = requests.get(url, headers=UA, timeout=60).text.splitlines()
            params = sorted({json.loads(l).get("param") for l in idx if l.strip()})
            return {"run": run.isoformat(), "index_url": url, "wanted_present": [p for p in WANTED if p in params]}
    raise RuntimeError("no index file found in last 48 h")


@check("ecmwf_0p1_available")
def ecmwf_0p1():
    from ecmwf.opendata import Client
    d = Client(source="ecmwf", model="ifs", resol="0p1").latest(type="fc", stream="oper", param="2t", step=0, levtype="sfc")
    return {"latest_0p1_run": d.isoformat()}


@check("irm_wfs_capabilities")
def irm_caps():
    r = requests.get(WFS, params=dict(service="WFS", version="2.0.0", request="GetCapabilities"), headers=UA, timeout=60)
    r.raise_for_status()
    layers = ["aws:aws_10min", "aws:aws_1hour", "aws:aws_station", "synop:synop_data"]
    return {"http": r.status_code, "layers_present": {l: (l in r.text) for l in layers}}


@check("irm_aws_10min_schema")
def irm_schema():
    r = requests.get(WFS, params=dict(service="WFS", version="2.0.0", request="DescribeFeatureType",
                                      typeNames="aws:aws_10min"), headers=UA, timeout=60)
    r.raise_for_status()
    names = re.findall(r'name="([A-Za-z0-9_]+)"', r.text)
    used = ["temp_dry_shelter_avg", "humidity_rel_shelter_avg", "precip_quantity", "wind_speed_10m",
            "short_wave_from_sky_avg", "code", "timestamp"]
    return {"all_fields": names, "used_fields_present": {f: f in names for f in used}}


@check("irm_stations_dynamic")
def irm_stations():
    r = requests.get(WFS, params=dict(service="WFS", version="2.0.0", request="GetFeature", typeNames="aws:aws_station",
                                      outputFormat="application/json", srsName="EPSG:4326"), headers=UA, timeout=60)
    r.raise_for_status()
    rows = []
    for f in r.json()["features"]:
        c = f["geometry"]["coordinates"]
        lon, lat = (c[0], c[1]) if abs(c[0]) < abs(c[1]) else (c[1], c[0])
        p1, p2 = math.radians(lat), math.radians(NAMUR[0])
        a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(NAMUR[1] - lon) / 2) ** 2
        rows.append({**{k: f["properties"].get(k) for k in ("code", "name", "altitude", "date_end")},
                     "km_from_namur": round(6371 * 2 * math.asin(math.sqrt(a)), 1)})
    rows.sort(key=lambda x: x["km_from_namur"])
    return {"n_stations": len(rows), "nearest_5": rows[:5]}


@check("irm_aws_10min_latest")
def irm_latest():
    near = REPORT["checks"].get("irm_stations_dynamic", {}).get("nearest_5", [{}])[0].get("code")
    since = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(WFS, headers=UA, timeout=60, params=dict(
        service="WFS", version="2.0.0", request="GetFeature", typeNames="aws:aws_10min",
        outputFormat="application/json", CQL_FILTER=f"code={near} AND timestamp>='{since}'"))
    props = [f["properties"] for f in r.json().get("features", [])]
    ts = sorted(str(x.get("timestamp")) for x in props)
    return {"station": near, "n_records_6h": len(props), "latest_timestamp": ts[-1] if ts else None}


@check("irm_alaro_forecast_listing")
def irm_alaro():
    r = requests.get("https://opendata.meteo.be/ftp/forecasts/alaro_40l/", headers=UA, timeout=60)
    r.raise_for_status()
    return {"entries": re.findall(r'href="([^"?/][^"]*)"', r.text)[:15]}


@check("open_meteo_ecmwf_hourly")
def open_meteo():
    hourly = "temperature_2m,dew_point_2m,relative_humidity_2m,precipitation,wind_speed_10m,cloud_cover,shortwave_radiation"
    r = requests.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=60, params=dict(
        latitude=NAMUR[0], longitude=NAMUR[1], hourly=hourly, models="ecmwf_ifs025", forecast_days=6,
        past_days=3, wind_speed_unit="ms", timezone="UTC"))
    h = r.json().get("hourly", {})
    return {"http": r.status_code, "vars_returned": sorted(k for k in h if k != "time"),
            "n_hours": len(h.get("time", [])), "first_time": (h.get("time") or [None])[0]}


if __name__ == "__main__":
    for fn in (ecmwf_client, ecmwf_direct, ecmwf_0p1, irm_caps, irm_schema, irm_stations, irm_latest, irm_alaro, open_meteo):
        fn()
    print(json.dumps(REPORT, indent=2, default=str))
    with open("step0_report.json", "w") as f:
        json.dump(REPORT, f, indent=2, default=str)
    sys.exit(0 if all(c["ok"] for c in REPORT["checks"].values()) else 1)
