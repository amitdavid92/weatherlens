"""NOAA NCEI Access Data Service — GHCN-Daily `daily-summaries` adapter (no token required).

Source-specific parsing lives only here. Requests use `units=metric`, under which the service
returns SNOW/PRCP in mm, TMIN/TMAX in °C and AWND/WSF5 in m/s (verified live against
`units=standard`; see tests/integration).

Per-element status rules:
- SNOW, PRCP (accumulations): value > 0 -> MEASURED; value == 0 with measurement flag "T" ->
  TRACE; value == 0 otherwise -> ZERO; key absent/empty -> MISSING.
- TMIN, TMAX, AWND, WSF5: any numeric value (including negative and 0) -> MEASURED;
  key absent/empty -> MISSING. Trace/zero semantics are never applied to these.
- Dates absent from the response are MISSING for every element.
- Quality flags are preserved; a non-empty quality flag marks the value `quality_flagged`
  (the value is kept; exclusion policy belongs to the analytics layer).
"""

from __future__ import annotations

import json
import re
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

BASE_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
DATASET = "daily-summaries"
STATION_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}$")  # e.g. USW00003017
EARLIEST = date(1900, 1, 1)
LICENSE = "Public domain (U.S. Government work, NOAA NCEI)"
ATTRIBUTION = "NOAA National Centers for Environmental Information, GHCN-Daily"

NOAA_ELEMENTS: dict[str, ClimateElement] = {
    "SNOW": ClimateElement.SNOWFALL,
    "PRCP": ClimateElement.PRECIPITATION,
    "TMIN": ClimateElement.TMIN,
    "TMAX": ClimateElement.TMAX,
    "AWND": ClimateElement.WIND_AVG,
    "WSF5": ClimateElement.WIND_GUST_MAX,
}
# Units returned by the service with units=metric (original == normalized; no conversion).
NOAA_METRIC_UNITS: dict[str, str] = {
    "SNOW": "mm",
    "PRCP": "mm",
    "TMIN": "degC",
    "TMAX": "degC",
    "AWND": "m/s",
    "WSF5": "m/s",
}


def validate_station_id(station_id: str) -> str:
    if not STATION_RE.match(station_id):
        raise InvalidRequestError(f"invalid GHCN-Daily station id: {station_id!r}")
    return station_id


def build_request(
    station_id: str, start: date, end: date, elements: list[str] | None = None
) -> SourceRequest:
    validate_station_id(station_id)
    if start > end:
        raise InvalidRequestError(f"start {start} is after end {end}")
    if start < EARLIEST:
        raise InvalidRequestError(f"start {start} before {EARLIEST}")
    elements = elements or list(NOAA_ELEMENTS)
    unknown = set(elements) - set(NOAA_ELEMENTS)
    if unknown:
        raise InvalidRequestError(f"unsupported NOAA elements: {sorted(unknown)}")
    return SourceRequest(
        source_id=SourceId.NOAA_GHCN_DAILY.value,
        url=BASE_URL,
        params={
            "dataset": DATASET,
            "stations": station_id,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dataTypes": ",".join(elements),
            "units": "metric",
            "format": "json",
            "includeAttributes": "true",
        },
        location_id=station_id,
        period=(start.isoformat(), end.isoformat()),
    )


def _parse_flags(raw: str | None) -> tuple[str | None, str | None, str | None]:
    if not raw:
        return None, None, None
    parts = (raw.split(",") + ["", "", ""])[:3]
    return tuple(p.strip() or None for p in parts)  # type: ignore[return-value]


def _parse_value(code: str, element: ClimateElement, row: dict | None) -> DailyValue:
    unit = NORMALIZED_UNITS[element]
    original_unit = NOAA_METRIC_UNITS[code]
    raw = row.get(code) if row else None
    mflag, qflag, sflag = _parse_flags(row.get(f"{code}_ATTRIBUTES") if row else None)
    if raw is None or str(raw).strip() == "":
        return DailyValue(
            status=ObservationStatus.MISSING,
            value=None,
            unit=unit,
            original_value=None,
            original_unit=original_unit,
            measurement_flag=mflag,
            quality_flag=qflag,
            source_flag=sflag,
        )
    try:
        value = float(raw)
    except ValueError as exc:
        raise InvalidResponseError(
            SourceId.NOAA_GHCN_DAILY.value, f"non-numeric {code} value {raw!r}"
        ) from exc

    if element in ACCUMULATION_ELEMENTS:
        if value < 0:
            raise InvalidResponseError(
                SourceId.NOAA_GHCN_DAILY.value, f"negative accumulation {code}={value}"
            )
        if value > 0:
            status = ObservationStatus.MEASURED
        elif mflag == "T":
            status = ObservationStatus.TRACE
        else:
            status = ObservationStatus.ZERO
    else:
        status = ObservationStatus.MEASURED  # negative temperatures are valid measurements

    return DailyValue(
        status=status,
        value=value,
        unit=unit,
        original_value=str(raw),
        original_unit=original_unit,
        measurement_flag=mflag,
        quality_flag=qflag,
        source_flag=sflag,
    )


def parse_response(
    body: bytes,
    req: SourceRequest,
    *,
    retrieved_at: datetime,
    freshness: Freshness,
) -> ClimateDataset:
    src = SourceId.NOAA_GHCN_DAILY.value
    try:
        rows = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidResponseError(src, f"invalid JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise InvalidResponseError(src, f"expected a JSON array, got {type(rows).__name__}")
    if not rows:
        raise InvalidResponseError(
            src, "empty response (unknown station, or no data at all for the period)"
        )

    station = req.params["stations"]
    start = date.fromisoformat(req.params["startDate"])
    end = date.fromisoformat(req.params["endDate"])
    codes = req.params["dataTypes"].split(",")

    by_date: dict[date, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or "DATE" not in row:
            raise InvalidResponseError(src, "row without DATE")
        if row.get("STATION") != station:
            raise InvalidResponseError(src, f"unexpected station {row.get('STATION')!r}")
        try:
            d = date.fromisoformat(row["DATE"])
        except ValueError as exc:
            raise InvalidResponseError(src, f"bad DATE {row['DATE']!r}") from exc
        if not (start <= d <= end):
            raise InvalidResponseError(src, f"date {d} outside requested range")
        if d in by_date:
            raise InvalidResponseError(src, f"duplicate row for {d}")
        by_date[d] = row

    elements = [NOAA_ELEMENTS[c] for c in codes]
    records = [
        DailyRecord(
            date=d,
            values={
                NOAA_ELEMENTS[c]: _parse_value(c, NOAA_ELEMENTS[c], by_date.get(d)) for c in codes
            },
        )
        for d in iter_dates(start, end)
    ]
    provenance = Provenance(
        source_id=SourceId.NOAA_GHCN_DAILY,
        dataset_name="GHCN-Daily (NCEI Access Data Service daily-summaries)",
        dataset_version=None,  # ADS does not version responses; retrieval time is recorded
        data_kind=DataKind.OBSERVED,
        request_url=req.url,
        query_params=req.params,
        retrieved_at=retrieved_at,
        freshness=freshness,
        geographic_resolution=GeoResolution.STATION,
        location_id=station,
        license=LICENSE,
        attribution=ATTRIBUTION,
    )
    return ClimateDataset(
        provenance=provenance,
        start=start,
        end=end,
        elements=elements,
        records=records,
        metadata={"station_id": station, "rows_returned": len(rows)},
    )
