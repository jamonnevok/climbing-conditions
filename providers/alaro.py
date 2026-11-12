"""IRM/KMI ALARO forecast (CC BY 4.0) -- DISABLED in v1.

Verified in Step 0: the directory https://opendata.meteo.be/ftp/forecasts/alaro_40l/
is publicly listable and keeps the 4 most recent runs (6-hourly).
NOT verified: file names inside a run folder, GRIB parameter tables (IRM local tables),
forecast range, time step, and the absence of solar radiation. Until these are checked
this provider deliberately refuses to run rather than guessing.
To enable: implement fetch() after inspecting one run folder, add "alaro" to the
region's forecast provider list, and add tests with a real sample file.
"""
from __future__ import annotations

from .base import ForecastProvider

LISTING_URL = "https://opendata.meteo.be/ftp/forecasts/alaro_40l/"


class AlaroProvider(ForecastProvider):
    name = "alaro"

    def latest_run(self, horizon_end):
        raise NotImplementedError("ALARO provider is disabled in v1 (file structure unverified)")

    def fetch(self, regions, run, max_lead, horizon_end):
        raise NotImplementedError("ALARO provider is disabled in v1 (file structure unverified)")
