"""Meteorological helper formulas (metric units)."""
from __future__ import annotations

import math
from datetime import datetime

# Magnus coefficients over water (Alduchov & Eskridge 1996)
A, B = 17.625, 243.04


def sat_vapour_pressure_kpa(t_c: float) -> float:
    return 0.61094 * math.exp(A * t_c / (B + t_c))


def rh_from_dewpoint(t_c: float, td_c: float) -> float:
    """Relative humidity in % from temperature and dewpoint (°C), clipped 0-100."""
    rh = 100.0 * math.exp(A * td_c / (B + td_c) - A * t_c / (B + t_c))
    return max(0.0, min(100.0, rh))


def dewpoint_from_rh(t_c: float, rh: float) -> float:
    """Dewpoint (°C) from temperature (°C) and relative humidity (%)."""
    rh = max(0.1, min(100.0, rh))
    g = math.log(rh / 100.0) + A * t_c / (B + t_c)
    return B * g / (A - g)


def vpd_kpa(t_c: float, td_c: float) -> float:
    """Vapour-pressure deficit (kPa)."""
    return max(0.0, sat_vapour_pressure_kpa(t_c) - sat_vapour_pressure_kpa(td_c))


def wind_speed(u: float, v: float) -> float:
    return math.hypot(u, v)


def cos_solar_zenith(when: datetime, lat: float, lon: float) -> float:
    """Cosine of the solar zenith angle (NOAA approximation). `when` must be UTC-aware."""
    doy = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60 + when.second / 3600
    g = 2 * math.pi / 365 * (doy - 1 + (hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    tst = hour * 60 + eqtime + 4 * lon
    ha = math.radians(tst / 4 - 180)
    la = math.radians(lat)
    return math.sin(la) * math.sin(decl) + math.cos(la) * math.cos(decl) * math.cos(ha)


def clear_sky_ghi(cosz: float) -> float:
    """Haurwitz clear-sky global horizontal irradiance (W/m2)."""
    if cosz <= 0.0:
        return 0.0
    return 1098.0 * cosz * math.exp(-0.057 / cosz)
