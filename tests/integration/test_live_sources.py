"""Opt-in live tests against the real public APIs:  `uv run pytest -m live`.

They use a throwaway cache and no snapshot, so every assertion is about the live source.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from weather_risk.catalog import load_catalog
from weather_risk.config import PROJECT_ROOT
from weather_risk.data.adapters import fema_nri, noaa_ghcn
from weather_risk.data.cache import ResponseCache
from weather_risk.data.http import USER_AGENT, HttpFetcher
from weather_risk.data.models import ClimateElement as E
from weather_risk.data.models import Freshness, HazardCode, HazardStatus, ObservationStatus
from weather_risk.data.repository import DataRepository

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> DataRepository:
    from weather_risk.config import Settings

    tmp = tmp_path_factory.mktemp("live")
    settings = Settings(WEATHER_RISK_CACHE_PATH=tmp / "c.db", _env_file=None)
    return DataRepository(
        fetcher=HttpFetcher(timeout_seconds=60, max_attempts=3),
        cache=ResponseCache(tmp / "c.db"),
        snapshot=None,
        settings=settings,
    )


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(PROJECT_ROOT / "config" / "hubs.yaml")


def test_noaa_denver_2025_snow_statuses(repo):
    ds = repo.get_station_daily("USW00003017", date(2025, 1, 1), date(2025, 12, 31))
    assert ds.provenance.freshness is Freshness.LIVE
    assert len(ds.records) == 365
    c = ds.status_counts(E.SNOWFALL)
    assert sum(c.values()) == 365
    assert c[ObservationStatus.MEASURED] > 0 and c[ObservationStatus.TRACE] > 0
    # temperatures: every reported value is MEASURED, including negatives
    tmin = [r.values[E.TMIN] for r in ds.records if r.values[E.TMIN].value is not None]
    assert any(v.value < 0 for v in tmin)
    assert {v.status for v in tmin} == {ObservationStatus.MEASURED}


def test_noaa_metric_units_match_standard_units():
    """With units=metric the service returns mm and °C (checked against units=standard)."""
    base = noaa_ghcn.build_request("USW00003017", date(2025, 1, 25), date(2025, 1, 25))
    std_params = {**base.params, "units": "standard"}
    h = {"User-Agent": USER_AGENT}
    metric = httpx.get(base.url, params=base.params, timeout=60, headers=h).json()[0]
    standard = httpx.get(base.url, params=std_params, timeout=60, headers=h).json()[0]
    assert float(metric["SNOW"]) == pytest.approx(float(standard["SNOW"]) * 25.4, abs=1.5)
    assert float(metric["TMAX"]) == pytest.approx((float(standard["TMAX"]) - 32) * 5 / 9, abs=0.6)


def test_all_catalog_stations_return_data(repo, catalog):
    for hub in catalog.hubs:
        ds = repo.get_station_daily(hub.noaa_station.id, date(2025, 1, 1), date(2025, 1, 31))
        assert ds.coverage(E.TMAX).completeness > 0.9, hub.id


def test_open_meteo_denver(repo):
    ds = repo.get_open_meteo_daily(39.73915, -104.9847, "America/Denver",
                                   date(2025, 1, 1), date(2025, 1, 31))  # fmt: skip
    assert ds.metadata["model"] == "era5"
    assert ds.coverage(E.SNOWFALL).completeness == 1.0


def test_nri_hub_counties_and_reference_share_version(repo, catalog):
    ref = repo.get_hazard_reference()
    assert ref.total_count > 3000
    assert len(ref.reference_records) == ref.total_count - len(ref.excluded_records)
    for hub in catalog.hubs:
        rec, ref2 = repo.get_county_with_reference(hub.hazard_county.fips)
        assert rec.nri_version == ref2.nri_version
        assert rec.county_fips == hub.hazard_county.fips
        assert all(v.status is not HazardStatus.UNKNOWN for v in rec.hazards.values()), hub.id
    for h in HazardCode:
        assert ref.status_counts(h, reference_only=False)["unknown"] == 0, h


def test_nri_count_matches_layer(repo):
    count = fema_nri.parse_count(repo.fetcher.get(fema_nri.build_count_request()).body)
    assert count == repo.get_hazard_reference().total_count
