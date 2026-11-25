"""Open-Meteo Historical Weather (archive API) adapter — modeled ERA5 reanalysis.

This is an ALTERNATIVE, clearly labeled source (`DataKind.MODELED_REANALYSIS`). Its values are
never merged with NOAA station observations.

- `models=era5` is pinned so every hub uses the same 0.25° reanalysis (the default
  `best_match` blends models and changes daily values).
- Units are requested explicitly and the returned `daily_units` are validated.
- Snowfall is returned in cm and normalized to mm (original value/unit preserved).
- Open-Meteo returns null for unavailable values; null -> MISSING.
- Reanalysis has no trace concept: snowfall/precip 0.0 -> ZERO, > 0 -> MEASURED.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from weather_risk.data.errors import InvalidRequestError, InvalidResponseError
from weather_risk.data.http import SourceRequest
from weather_risk.data.models import (
    ACCUMULATION_ELEMENTS,
    NORMALIZED_UNITS,
    ClimateDataset,
    ClimateElement,
    DailyRecord,
    DailyValue,
    DataKind,
    Freshness,
    GeoResolution,
    ObservationStatus,
    Provenance,
    SourceId,
)
from weather_risk.data.periods import iter_dates

BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
MODEL = "era5"
EARLIEST = date(1940, 1, 1)
LICENSE = "CC BY 4.0 (Open-Meteo.com); free API for non-commercial use"
ATTRIBUTION = "Weather data by Open-Meteo.com (ERA5 reanalysis, Copernicus/ECMWF)"

# Open-Meteo variable -> (normalized element, expected unit as returned, factor to normalized)
OM_VARIABLES: dict[str, tuple[ClimateElement, str, float]] = {
    "snowfall_sum": (ClimateElement.SNOWFALL, "cm", 10.0),
    "precipitation_sum": (ClimateElement.PRECIPITATION, "mm", 1.0),
    "temperature_2m_min": (ClimateElement.TMIN, "°C", 1.0),
    "temperature_2m_max": (ClimateElement.TMAX, "°C", 1.0),
    "wind_speed_10m_max": (ClimateElement.WIND_SPEED_MAX, "m/s", 1.0),
    "wind_gusts_10m_max": (ClimateElement.WIND_GUST_MAX, "m/s", 1.0),
}


def build_request(
    latitude: float, longitude: float, start: date, end: date, timezone: str
) -> SourceRequest:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise InvalidRequestError(f"invalid coordinates {latitude},{longitude}")
    if start > end:
        raise InvalidRequestError(f"start {start} is after end {end}")
    if start < EARLIEST:
        raise InvalidRequestError(f"start {start} before {EARLIEST}")
    return SourceRequest(
        source_id=SourceId.OPEN_METEO_ARCHIVE.value,
        url=BASE_URL,
        params={
            "latitude": f"{latitude:.5f}",
            "longitude": f"{longitude:.5f}",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": ",".join(OM_VARIABLES),
            "temperature_unit": "celsius",
            "precipitation_unit": "mm",
            "wind_speed_unit": "ms",
            "timezone": timezone,
            "models": MODEL,
        },
        location_id=f"{latitude:.5f},{longitude:.5f}",
        period=(start.isoformat(), end.isoformat()),
    )


def parse_response(
    body: bytes, req: SourceRequest, *, retrieved_at: datetime, freshness: Freshness
) -> ClimateDataset:
    src = SourceId.OPEN_METEO_ARCHIVE.value
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidResponseError(src, f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidResponseError(src, "expected a JSON object")
    if payload.get("error"):
        raise InvalidResponseError(src, f"API error: {payload.get('reason')}")

    daily = payload.get("daily")
    units = payload.get("daily_units")
    if not isinstance(daily, dict) or not isinstance(units, dict) or "time" not in daily:
        raise InvalidResponseError(src, "missing daily/daily_units")

    for var, (_, expected_unit, _) in OM_VARIABLES.items():
        if var not in daily:
            raise InvalidResponseError(src, f"variable {var} missing from response")
        if units.get(var) != expected_unit:
            raise InvalidResponseError(
                src, f"unit mismatch for {var}: expected {expected_unit!r}, got {units.get(var)!r}"
            )

    start = date.fromisoformat(req.params["start_date"])
    end = date.fromisoformat(req.params["end_date"])
    try:
        times = [date.fromisoformat(t) for t in daily["time"]]
    except (TypeError, ValueError) as exc:
        raise InvalidResponseError(src, "bad time array") from exc
    if times != list(iter_dates(start, end)):
        raise InvalidResponseError(src, "time axis does not match requested range")
    n = len(times)
    for var in OM_VARIABLES:
        if not isinstance(daily[var], list) or len(daily[var]) != n:
            raise InvalidResponseError(src, f"{var} length mismatch")

    records = []
    for i, d in enumerate(times):
        values: dict[ClimateElement, DailyValue] = {}
        for var, (element, orig_unit, factor) in OM_VARIABLES.items():
            raw = daily[var][i]
            if raw is None:
                values[element] = DailyValue(
                    status=ObservationStatus.MISSING,
                    value=None,
                    unit=NORMALIZED_UNITS[element],
                    original_value=None,
                    original_unit=orig_unit,
                )
                continue
            if not isinstance(raw, int | float):
                raise InvalidResponseError(src, f"non-numeric {var} value {raw!r}")
            v = round(float(raw) * factor, 4)
            if element in ACCUMULATION_ELEMENTS:
                if v < 0:
                    raise InvalidResponseError(src, f"negative accumulation {var}={raw}")
                status = ObservationStatus.MEASURED if v > 0 else ObservationStatus.ZERO
            else:
                status = ObservationStatus.MEASURED
            values[element] = DailyValue(
                status=status,
                value=v,
                unit=NORMALIZED_UNITS[element],
                original_value=str(raw),
                original_unit=orig_unit,
            )
        records.append(DailyRecord(date=d, values=values))

    grid = f"{payload.get('latitude')},{payload.get('longitude')}"
    provenance = Provenance(
        source_id=SourceId.OPEN_METEO_ARCHIVE,
        dataset_name=f"Open-Meteo Historical Weather API (model={MODEL})",
        dataset_version=MODEL,
        data_kind=DataKind.MODELED_REANALYSIS,
        request_url=req.url,
        query_params=req.params,
        retrieved_at=retrieved_at,
        freshness=freshness,
        geographic_resolution=GeoResolution.GRID_CELL,
        location_id=grid,
        license=LICENSE,
        attribution=ATTRIBUTION,
    )
    return ClimateDataset(
        provenance=provenance,
        start=start,
        end=end,
        elements=[e for e, _, _ in OM_VARIABLES.values()],
        records=records,
        metadata={
            "model": MODEL,
            "requested_latitude": float(req.params["latitude"]),
            "requested_longitude": float(req.params["longitude"]),
            "grid_latitude": payload.get("latitude"),
            "grid_longitude": payload.get("longitude"),
            "grid_elevation_m": payload.get("elevation"),
            "timezone": payload.get("timezone"),
        },
    )
