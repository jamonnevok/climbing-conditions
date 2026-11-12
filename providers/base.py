"""Provider interfaces and the normalised hourly data model.

Convention (everywhere in the pipeline):
  * times are UTC, one row per hour, keyed by the hour START "YYYY-MM-DDTHH:00Z";
  * a row describes the period [start, start + 1 h): accumulations (precipitation,
    radiation) are totals/means over that hour, instantaneous fields are valued
    at mid-hour (or the closest available estimate);
  * units: temp_c / dewpoint_c in °C, rh in %, precip_mm in mm per hour,
    wind_ms in m/s (10 m), cloud_pct in %, sw_wm2 = mean downward shortwave W/m².
Missing values are None. Nothing is ever filled with invented values.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

VARS = ("temp_c", "dewpoint_c", "rh", "precip_mm", "wind_ms", "cloud_pct", "sw_wm2")


@dataclass
class HourlySeries:
    kind: str                       # "forecast" | "observation"
    provider: str                   # registry name, e.g. "ecmwf"
    label: str                      # human-readable source label
    hours: dict[str, dict] = field(default_factory=dict)   # iso hour -> {var: value, "interp": bool}
    run: str | None = None          # model run (iso) for forecasts
    sources: dict[str, str] = field(default_factory=dict)  # var -> source label
    meta: dict = field(default_factory=dict)
    modelled: bool = False          # True if "observation" values actually come from a model

    def to_dict(self) -> dict:
        return {"kind": self.kind, "provider": self.provider, "label": self.label, "run": self.run,
                "sources": self.sources, "meta": self.meta, "modelled": self.modelled,
                "hours": self.hours}

    @classmethod
    def from_dict(cls, d: dict) -> "HourlySeries":
        return cls(kind=d["kind"], provider=d["provider"], label=d["label"], hours=d["hours"],
                   run=d.get("run"), sources=d.get("sources", {}), meta=d.get("meta", {}),
                   modelled=d.get("modelled", False))


class ForecastProvider(ABC):
    name: str = "forecast"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    @abstractmethod
    def latest_run(self, horizon_end: datetime) -> tuple[datetime | None, int | None]:
        """Return (run time, max lead hours to download) or (None, None) if the
        provider has no notion of runs (e.g. a re-served API)."""

    @abstractmethod
    def fetch(self, regions: list[dict], run: datetime | None, max_lead: int | None,
              horizon_end: datetime) -> dict[str, HourlySeries]:
        """Return one HourlySeries per region id."""


class ObservationProvider(ABC):
    name: str = "observation"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    @abstractmethod
    def fetch(self, region: dict, start: datetime, end: datetime) -> HourlySeries:
        """Hourly observations for [start, end)."""
