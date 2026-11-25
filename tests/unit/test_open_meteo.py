from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from tests.conftest import load_fixture
from weather_risk.data.adapters import open_meteo
from weather_risk.data.errors import InvalidRequestError, InvalidResponseError
from weather_risk.data.models import ClimateElement as E
from weather_risk.data.models import DataKind, Freshness, GeoResolution, ObservationStatus

AT = datetime(2026, 11, 25, tzinfo=UTC)


def test_parse_real_response_units_and_metadata():
    req, body = load_fixture("openmeteo_denver_2025-01-01_05")
    ds = open_meteo.parse_response(body, req, retrieved_at=AT, freshness=Freshness.LIVE)
    raw = json.loads(body)
    assert len(ds.records) == 5
    first_snow_cm = raw["daily"]["snowfall_sum"][0]
    v = ds.records[0].values[E.SNOWFALL]
    assert v.original_unit == "cm" and v.unit == "mm"
    assert v.value == pytest.approx(first_snow_cm * 10)
    assert v.original_value == str(first_snow_cm)
    assert ds.records[0].values[E.WIND_GUST_MAX].unit == "m/s"
    assert ds.provenance.data_kind is DataKind.MODELED_REANALYSIS
    assert ds.provenance.geographic_resolution is GeoResolution.GRID_CELL
    assert ds.provenance.dataset_version == "era5"
    assert ds.metadata["model"] == "era5"
    assert ds.metadata["grid_latitude"] == raw["latitude"]
    assert "Open-Meteo" in ds.provenance.attribution


def _body(**overrides) -> bytes:
    req = open_meteo.build_request(39.7, -105.0, date(2025, 1, 1), date(2025, 1, 2), "UTC")
    daily = {"time": ["2025-01-01", "2025-01-02"]}
    units = {"time": "iso8601"}
    for var, (_, unit, _) in open_meteo.OM_VARIABLES.items():
        daily[var] = [0.0, 1.5]
        units[var] = unit
    payload = {"latitude": 39.75, "longitude": -105.0, "daily": daily, "daily_units": units}
    for k, v in overrides.items():
        payload[k] = v(payload) if callable(v) else v
    return req, json.dumps(payload).encode()


def test_null_is_missing_and_zero_snow_is_zero():
    req, body = _body()
    payload = json.loads(body)
    payload["daily"]["snowfall_sum"] = [None, 0.0]
    payload["daily"]["temperature_2m_min"] = [-12.3, 0.0]
    ds = open_meteo.parse_response(
        json.dumps(payload).encode(), req, retrieved_at=AT, freshness=Freshness.LIVE
    )
    assert ds.records[0].values[E.SNOWFALL].status is ObservationStatus.MISSING
    assert ds.records[1].values[E.SNOWFALL].status is ObservationStatus.ZERO
    assert ds.records[0].values[E.TMIN].status is ObservationStatus.MEASURED
    assert ds.records[1].values[E.TMIN].status is ObservationStatus.MEASURED  # 0 °C


def test_unit_mismatch_rejected():
    req, body = _body()
    payload = json.loads(body)
    payload["daily_units"]["temperature_2m_max"] = "°F"
    with pytest.raises(InvalidResponseError, match="unit mismatch"):
        open_meteo.parse_response(
            json.dumps(payload).encode(), req, retrieved_at=AT, freshness=Freshness.LIVE
        )


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda p: p.update(error=True, reason="bad"), "API error"),
        (lambda p: p.pop("daily"), "missing daily"),
        (lambda p: p["daily"].pop("snowfall_sum"), "missing from response"),
        (lambda p: p["daily"].update(time=["2025-01-01"]), "time axis"),
        (lambda p: p["daily"].update(precipitation_sum=[1.0]), "length mismatch"),
        (lambda p: p["daily"].update(precipitation_sum=["x", 1.0]), "non-numeric"),
    ],
)
def test_invalid_payloads(mutate, match):
    req, body = _body()
    payload = json.loads(body)
    mutate(payload)
    with pytest.raises(InvalidResponseError, match=match):
        open_meteo.parse_response(
            json.dumps(payload).encode(), req, retrieved_at=AT, freshness=Freshness.LIVE
        )


def test_request_pins_model_and_units():
    req = open_meteo.build_request(39.7, -105.0, date(2025, 1, 1), date(2025, 1, 2), "UTC")
    assert req.params["models"] == "era5"
    assert req.params["temperature_unit"] == "celsius"
    assert req.params["precipitation_unit"] == "mm"
    assert req.params["wind_speed_unit"] == "ms"


def test_bad_coordinates_rejected():
    with pytest.raises(InvalidRequestError):
        open_meteo.build_request(95.0, -105.0, date(2025, 1, 1), date(2025, 1, 2), "UTC")
