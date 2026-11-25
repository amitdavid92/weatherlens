from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from tests.conftest import load_fixture
from weather_risk.data.adapters import noaa_ghcn
from weather_risk.data.errors import InvalidRequestError, InvalidResponseError
from weather_risk.data.models import ClimateElement as E
from weather_risk.data.models import (
    DataKind,
    Freshness,
    GeoResolution,
    ObservationStatus,
    SourceId,
)

AT = datetime(2026, 11, 25, tzinfo=UTC)


def parse(name: str):
    req, body = load_fixture(name)
    return noaa_ghcn.parse_response(body, req, retrieved_at=AT, freshness=Freshness.LIVE)


def test_trace_vs_measurable_snowfall_real_denver_data():
    ds = parse("noaa_denver_2025-01-24_26")
    snow = {r.date: r.values[E.SNOWFALL] for r in ds.records}
    assert snow[date(2025, 1, 24)].status is ObservationStatus.TRACE
    assert snow[date(2025, 1, 24)].value == 0.0
    assert snow[date(2025, 1, 24)].measurement_flag == "T"
    assert snow[date(2025, 1, 25)].status is ObservationStatus.MEASURED
    assert snow[date(2025, 1, 25)].value == 104.0  # mm (≈ 4.1 in)
    assert snow[date(2025, 1, 25)].unit == "mm"
    assert snow[date(2025, 1, 26)].status is ObservationStatus.TRACE


def test_precipitation_trace_flag_is_preserved():
    ds = parse("noaa_denver_2025-01-24_26")
    prcp = ds.records[0].values[E.PRECIPITATION]
    assert prcp.status is ObservationStatus.TRACE
    assert prcp.measurement_flag == "T"


def test_missing_snow_key_is_missing_not_zero():
    ds = parse("noaa_denver_2025-05-20_22")
    by_date = {r.date: r for r in ds.records}
    v = by_date[date(2025, 5, 21)].values[E.SNOWFALL]
    assert v.status is ObservationStatus.MISSING
    assert v.value is None
    # other elements that day are present
    assert by_date[date(2025, 5, 21)].values[E.TMAX].status is ObservationStatus.MEASURED
    assert by_date[date(2025, 5, 20)].values[E.SNOWFALL].status is ObservationStatus.ZERO
    cov = ds.coverage(E.SNOWFALL)
    assert (cov.expected_days, cov.reported_days, cov.missing_days) == (3, 2, 1)
    assert cov.missing_dates_sample == [date(2025, 5, 21)]


def test_negative_and_zero_temperatures_are_measurements_leap_day_included():
    ds = parse("noaa_msp_2024-02-27_03-02")
    assert len(ds.records) == 5  # Feb 27, 28, 29, Mar 1, Mar 2 (leap year)
    by_date = {r.date: r for r in ds.records}
    leap = by_date[date(2024, 2, 29)].values[E.TMIN]
    assert leap.status is ObservationStatus.MEASURED and leap.value == -10.5
    zero_c = by_date[date(2024, 3, 2)].values[E.TMIN]
    assert zero_c.status is ObservationStatus.MEASURED  # 0 °C is a value, not "zero"/missing
    assert zero_c.value == 0.0
    statuses = {r.values[E.TMIN].status for r in ds.records}
    assert statuses == {ObservationStatus.MEASURED}


def test_unreported_miami_snow_is_missing_for_every_day():
    ds = parse("noaa_miami_2019-01-01_10")
    counts = ds.status_counts(E.SNOWFALL)
    assert counts[ObservationStatus.MISSING] == 10
    assert counts[ObservationStatus.ZERO] == 0
    assert ds.coverage(E.TMAX).completeness == 1.0


def test_dates_absent_from_response_become_missing_for_all_elements():
    req = noaa_ghcn.build_request("USW00003017", date(2025, 1, 1), date(2025, 1, 3))
    body = json.dumps(
        [
            {"DATE": "2025-01-01", "STATION": "USW00003017", "TMIN": "-3.0", "SNOW": "0.0"},
            {"DATE": "2025-01-03", "STATION": "USW00003017", "TMIN": "-1.0", "SNOW": "5.0"},
        ]
    ).encode()
    ds = noaa_ghcn.parse_response(body, req, retrieved_at=AT, freshness=Freshness.LIVE)
    jan2 = ds.records[1]
    assert jan2.date == date(2025, 1, 2)
    assert all(v.status is ObservationStatus.MISSING for v in jan2.values.values())


def test_quality_flag_is_preserved_and_value_kept():
    req = noaa_ghcn.build_request("USW00003017", date(2025, 1, 1), date(2025, 1, 1))
    body = json.dumps(
        [{"DATE": "2025-01-01", "STATION": "USW00003017", "TMAX": "45.0",
          "TMAX_ATTRIBUTES": ",X,W,2400"}]
    ).encode()  # fmt: skip
    ds = noaa_ghcn.parse_response(body, req, retrieved_at=AT, freshness=Freshness.LIVE)
    v = ds.records[0].values[E.TMAX]
    assert v.quality_flag == "X" and v.quality_flagged and v.value == 45.0
    assert ds.coverage(E.TMAX).quality_flagged_days == 1


def test_provenance_is_complete():
    ds = parse("noaa_denver_2025-01-24_26")
    p = ds.provenance
    assert p.source_id is SourceId.NOAA_GHCN_DAILY
    assert p.data_kind is DataKind.OBSERVED
    assert p.geographic_resolution is GeoResolution.STATION
    assert p.location_id == "USW00003017"
    assert p.query_params["units"] == "metric"
    assert "Public domain" in p.license and p.attribution
    assert p.retrieved_at == AT and p.freshness is Freshness.LIVE


@pytest.mark.parametrize(
    "body,match",
    [
        (b"<html>Service Unavailable</html>", "invalid JSON"),
        (b"{}", "JSON array"),
        (b"[]", "empty response"),
        (b'[{"DATE":"2025-01-01","STATION":"USW00003017","SNOW":"abc"}]', "non-numeric"),
        (b'[{"DATE":"2025-01-01","STATION":"USW00003017","SNOW":"-1"}]', "negative"),
        (b'[{"DATE":"2025-01-01","STATION":"OTHER0000000"}]', "unexpected station"),
        (b'[{"DATE":"2025-01-09","STATION":"USW00003017"}]', "outside requested range"),
        (
            b'[{"DATE":"2025-01-01","STATION":"USW00003017"},'
            b'{"DATE":"2025-01-01","STATION":"USW00003017"}]',
            "duplicate",
        ),
    ],
)
def test_invalid_responses_raise_typed_errors(body, match):
    req = noaa_ghcn.build_request("USW00003017", date(2025, 1, 1), date(2025, 1, 2))
    with pytest.raises(InvalidResponseError, match=match):
        noaa_ghcn.parse_response(body, req, retrieved_at=AT, freshness=Freshness.LIVE)


@pytest.mark.parametrize("station", ["ORD", "usw00003017", "USW0000301", "", "USW00003017; DROP"])
def test_station_id_validation(station):
    with pytest.raises(InvalidRequestError):
        noaa_ghcn.build_request(station, date(2025, 1, 1), date(2025, 1, 2))


def test_inverted_range_rejected():
    with pytest.raises(InvalidRequestError):
        noaa_ghcn.build_request("USW00003017", date(2025, 2, 1), date(2025, 1, 1))
