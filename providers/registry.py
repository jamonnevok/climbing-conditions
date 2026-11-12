from __future__ import annotations

from .alaro import AlaroProvider
from .ecmwf import EcmwfProvider
from .irm import IrmAwsProvider
from .openmeteo import OpenMeteoForecast, OpenMeteoPast

FORECAST = {"ecmwf": EcmwfProvider, "openmeteo": OpenMeteoForecast, "alaro": AlaroProvider}
OBSERVATION = {"irm_aws": IrmAwsProvider, "openmeteo_past": OpenMeteoPast}
