"""Fallback chain: fresh cache -> live -> stale cache -> snapshot -> DataUnavailableError."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from tests.conftest import FIXED_NOW, FakeFetcher, load_fixture
from weather_risk.data.adapters import fema_nri, noaa_ghcn
from weather_risk.data.cache import ResponseCache
from weather_risk.data.errors import (
    DataUnavailableError,
    InvalidRequestError,
    SourceTimeoutError,
)
from weather_risk.data.models import ClimateElement as E
from weather_risk.data.models import Freshness, ObservationStatus, SourceId
from weather_risk.data.repository import DataRepository
from weather_risk.data.snapshot import SnapshotStore, SnapshotWriter

STATION = "USW00003017"


def noaa_year_body(year: int, *, snow_on: dict[str, str] | None = None) -> bytes:
    """Synthetic but schema-faithful NOAA year: every day reported, SNOW=0 unless overridden."""
    from weather_risk.data.periods import iter_dates

    rows = []
    for d in iter_dates(date(year, 1, 1), date(year, 12, 31)):
        iso = d.isoformat()
        row = {"DATE": iso, "STATION": STATION, "TMIN": "-2.0", "TMAX": "8.0", "PRCP": "0.0",
               "SNOW": (snow_on or {}).get(iso, "0.0")}  # fmt: skip
        rows.append(row)
    return json.dumps(rows).encode()


def make_repo(settings, cache, fetcher, snapshot=None, offline=False) -> DataRepository:
    s = settings.model_copy(update={"offline": offline})
    return DataRepository(
        fetcher=fetcher, cache=cache, snapshot=snapshot, settings=s, clock=lambda: FIXED_NOW
    )


def year_req(repo: DataRepository, year: int):
    return repo.noaa_year_request(STATION, year)


def test_live_then_cache_hit_avoids_second_call(settings, cache, fake_fetcher):
    repo = make_repo(settings, cache, fake_fetcher)
    fake_fetcher.add(year_req(repo, 2025), noaa_year_body(2025))
    ds1 = repo.get_station_daily(STATION, date(2025, 1, 1), date(2025, 12, 31))
    ds2 = repo.get_station_daily(STATION, date(2025, 3, 1), date(2025, 3, 31))
    assert ds1.provenance.freshness is Freshness.LIVE
    assert ds2.provenance.freshness is Freshness.CACHE
    assert len(fake_fetcher.calls) == 1
    assert len(ds2.records) == 31 and ds2.start == date(2025, 3, 1)


def test_multi_year_request_uses_year_chunks_and_records_components(settings, cache, fake_fetcher):
    repo = make_repo(settings, cache, fake_fetcher)
    fake_fetcher.add(year_req(repo, 2023), noaa_year_body(2023))
    fake_fetcher.add(year_req(repo, 2024), noaa_year_body(2024))
    ds = repo.get_station_daily(STATION, date(2023, 12, 30), date(2024, 1, 2))
    assert [r.date.isoformat() for r in ds.records] == [
        "2023-12-30", "2023-12-31", "2024-01-01", "2024-01-02"]  # fmt: skip
    assert len(ds.components) == 2
    assert ds.provenance.query_params["startDate"] == "2023-12-30"


def test_leap_year_dataset_has_366_days(settings, cache, fake_fetcher):
    repo = make_repo(settings, cache, fake_fetcher)
    fake_fetcher.add(year_req(repo, 2024), noaa_year_body(2024))
    ds = repo.get_station_daily(STATION, date(2024, 1, 1), date(2024, 12, 31))
    assert len(ds.records) == 366


def test_invalid_live_response_is_not_cached(settings, cache, fake_fetcher):
    repo = make_repo(settings, cache, fake_fetcher)
    fake_fetcher.add(year_req(repo, 2025), b"<html>maintenance</html>")
    with pytest.raises(DataUnavailableError) as exc:
        repo.get_station_daily(STATION, date(2025, 1, 1), date(2025, 1, 31))
    assert "invalid JSON" in str(exc.value)
    assert cache.count() == 0


def test_stale_cache_used_when_source_fails(settings, cache, fake_fetcher):
    repo = make_repo(settings, cache, fake_fetcher)
    req = year_req(repo, 2025)
    cache.put(req, noaa_year_body(2025), ttl_seconds=1, now=FIXED_NOW - timedelta(days=60))
    fake_fetcher.add(req, SourceTimeoutError("noaa_ghcn_daily", "timeout"))
    ds = repo.get_station_daily(STATION, date(2025, 1, 1), date(2025, 12, 31))
    assert ds.provenance.freshness is Freshness.STALE_CACHE
    assert ds.provenance.retrieved_at == FIXED_NOW - timedelta(days=60)
    assert len(fake_fetcher.calls) == 1


def test_expired_cache_is_refreshed_when_source_is_up(settings, cache, fake_fetcher):
    repo = make_repo(settings, cache, fake_fetcher)
    req = year_req(repo, 2025)
    cache.put(req, noaa_year_body(2025), ttl_seconds=1, now=FIXED_NOW - timedelta(days=60))
    fake_fetcher.add(req, noaa_year_body(2025, snow_on={"2025-01-05": "12.0"}))
    ds = repo.get_station_daily(STATION, date(2025, 1, 5), date(2025, 1, 5))
    assert ds.provenance.freshness is Freshness.LIVE
    assert ds.records[0].values[E.SNOWFALL].value == 12.0


def _snapshot_with(tmp_path, req, body) -> SnapshotStore:
    w = SnapshotWriter(tmp_path / "snap", description="test", generator="pytest")
    w.add(req, body, relative_file="noaa/x.json.gz", retrieved_at=FIXED_NOW - timedelta(days=5))
    w.write_manifest()
    return SnapshotStore(tmp_path / "snap")


def test_snapshot_used_when_source_fails_and_no_cache(settings, cache, fake_fetcher, tmp_path):
    probe = make_repo(settings, cache, fake_fetcher)
    req = year_req(probe, 2025)
    snap = _snapshot_with(tmp_path, req, noaa_year_body(2025))
    repo = make_repo(settings, cache, fake_fetcher, snapshot=snap)
    fake_fetcher.add(req, SourceTimeoutError("noaa_ghcn_daily", "timeout"))
    ds = repo.get_station_daily(STATION, date(2025, 6, 1), date(2025, 6, 30))
    assert ds.provenance.freshness is Freshness.SNAPSHOT
    assert len(ds.records) == 30


def test_offline_mode_never_calls_source(settings, cache, fake_fetcher, tmp_path):
    probe = make_repo(settings, cache, fake_fetcher)
    req = year_req(probe, 2025)
    snap = _snapshot_with(tmp_path, req, noaa_year_body(2025))
    repo = make_repo(settings, cache, fake_fetcher, snapshot=snap, offline=True)
    ds = repo.get_station_daily(STATION, date(2025, 1, 1), date(2025, 1, 31))
    assert ds.provenance.freshness is Freshness.SNAPSHOT
    assert fake_fetcher.calls == []


def test_unavailable_when_nothing_works(settings, cache, fake_fetcher):
    repo = make_repo(settings, cache, fake_fetcher, snapshot=None)
    fake_fetcher.add(year_req(repo, 2025), SourceTimeoutError("noaa_ghcn_daily", "timeout"))
    with pytest.raises(DataUnavailableError) as exc:
        repo.get_station_daily(STATION, date(2025, 1, 1), date(2025, 1, 31))
    msg = str(exc.value)
    assert "live fetch failed" in msg and "no snapshot configured" in msg


def test_corrupted_snapshot_file_is_not_used(settings, cache, fake_fetcher, tmp_path):
    probe = make_repo(settings, cache, fake_fetcher)
    req = year_req(probe, 2025)
    snap = _snapshot_with(tmp_path, req, noaa_year_body(2025))
    (tmp_path / "snap" / "noaa/x.json.gz").write_bytes(b"not gzip")
    snap = SnapshotStore(tmp_path / "snap")
    assert snap.verify() == ["unreadable noaa/x.json.gz"]
    repo = make_repo(settings, cache, fake_fetcher, snapshot=snap, offline=True)
    with pytest.raises(DataUnavailableError):
        repo.get_station_daily(STATION, date(2025, 1, 1), date(2025, 1, 31))


def test_snapshot_manifest_records_provenance_and_hashes(tmp_path):
    req = noaa_ghcn.build_request(STATION, date(2025, 1, 1), date(2025, 12, 31))
    w = SnapshotWriter(tmp_path, description="d", generator="g")
    entry = w.add(req, b"[1]", relative_file="a.json.gz", retrieved_at=FIXED_NOW,
                  dataset_version=None)  # fmt: skip
    w.write_manifest()
    store = SnapshotStore(tmp_path)
    assert store.verify() == []
    assert entry.period_start == date(2025, 1, 1) and entry.location_id == STATION
    assert entry.params["units"] == "metric"
    assert set(store.manifest.licenses) == {s.value for s in SourceId}
    body, got = store.get(req)
    assert body == b"[1]" and got.body_sha256 == entry.body_sha256


def test_snapshot_gzip_is_deterministic(tmp_path):
    req = noaa_ghcn.build_request(STATION, date(2025, 1, 1), date(2025, 1, 2))
    for d in ("a", "b"):
        w = SnapshotWriter(tmp_path / d, description="d", generator="g")
        w.add(req, b"[1,2,3]", relative_file="f.json.gz", retrieved_at=FIXED_NOW)
    assert (tmp_path / "a/f.json.gz").read_bytes() == (tmp_path / "b/f.json.gz").read_bytes()


def test_invalid_request_raises_before_any_fetch(settings, cache, fake_fetcher):
    repo = make_repo(settings, cache, fake_fetcher)
    with pytest.raises(InvalidRequestError):
        repo.get_station_daily(STATION, date(2026, 11, 1), date(2026, 11, 30))  # includes future
    with pytest.raises(InvalidRequestError):
        repo.get_station_daily("BAD", date(2025, 1, 1), date(2025, 1, 2))
    assert fake_fetcher.calls == []


def test_real_denver_fixture_through_repository_cache(settings, cache, fake_fetcher):
    """Real recorded body served via the cache path keeps trace/missing semantics."""
    req, body = load_fixture("noaa_denver_2025-05-20_22")
    cache.put(req, body, ttl_seconds=3600, now=FIXED_NOW)
    repo = make_repo(settings, cache, fake_fetcher)
    ds = repo._resolve(
        req,
        lambda b, at, fr: noaa_ghcn.parse_response(b, req, retrieved_at=at, freshness=fr),
        ttl_seconds=60,
        what="fixture",
    )
    assert ds.provenance.freshness is Freshness.CACHE
    assert ds.status_counts(E.SNOWFALL)[ObservationStatus.MISSING] == 1


# ------------------------------------------------------------------ NRI via repository


def _nri_reference_setup(fetcher: FakeFetcher, version_override: str | None = None):
    _, count_body = load_fixture("nri_count")
    page0 = json.loads(load_fixture("nri_page_size3_offset0")[1])
    page1 = json.loads(load_fixture("nri_page_size3_offset3")[1])
    if version_override:
        for p in (page0, page1):
            for f in p["features"]:
                f["attributes"]["NRI_VER"] = version_override
    fetcher.add(fema_nri.build_count_request(), b'{"count": 6}')
    fetcher.add(fema_nri.build_page_request(0, 2000), json.dumps(page0).encode())
    return count_body, page0, page1


def test_reference_population_pagination_via_repository(settings, cache, monkeypatch):
    monkeypatch.setattr(fema_nri, "PAGE_SIZE", 3)
    fetcher = FakeFetcher()
    _, page0, page1 = _nri_reference_setup(fetcher)
    fetcher.add(fema_nri.build_page_request(0, 3), json.dumps(page0).encode())
    fetcher.add(fema_nri.build_page_request(3, 3), json.dumps(page1).encode())
    repo = make_repo(settings, cache, fetcher)
    ref = repo.get_hazard_reference()
    assert ref.total_count == 6 and len(ref.records) == 6
    assert ref.provenance.freshness is Freshness.LIVE
    assert len(fetcher.calls) == 3  # count + 2 pages


def test_county_with_reference_uses_reference_record_on_version_mismatch(
    settings, cache, monkeypatch
):
    monkeypatch.setattr(fema_nri, "PAGE_SIZE", 3)
    fetcher = FakeFetcher()
    _, page0, page1 = _nri_reference_setup(fetcher, version_override="March 2023")
    fetcher.add(fema_nri.build_page_request(0, 3), json.dumps(page0).encode())
    fetcher.add(fema_nri.build_page_request(3, 3), json.dumps(page1).encode())
    target = page0["features"][0]["attributes"]["STCOFIPS"]
    live_county = json.loads(json.dumps(page0))
    live_county["features"] = live_county["features"][:1]
    for f in live_county["features"]:
        f["attributes"]["NRI_VER"] = "December 2025"
    fetcher.add(fema_nri.build_county_request(target), json.dumps(live_county).encode())
    repo = make_repo(settings, cache, fetcher)
    record, ref = repo.get_county_with_reference(target)
    assert record.nri_version == ref.nri_version == "March 2023"


def test_county_hazards_snapshot_fallback(settings, cache, tmp_path):
    req, body = load_fixture("nri_county_48113")
    canonical = fema_nri.build_county_request("48113")
    assert canonical.key == req.key  # fixture recorded with the canonical request
    w = SnapshotWriter(tmp_path / "s", description="d", generator="g")
    w.add(canonical, body, relative_file="nri/48113.json.gz", retrieved_at=FIXED_NOW)
    w.write_manifest()
    repo = make_repo(settings, cache, FakeFetcher(), snapshot=SnapshotStore(tmp_path / "s"))
    rec = repo.get_county_hazards("48113")
    assert rec.provenance.freshness is Freshness.SNAPSHOT
    assert rec.county_fips == "48113"


def test_cache_corruption_triggers_refetch(settings, tmp_path, fake_fetcher):
    cache = ResponseCache(tmp_path / "c.db")
    repo = make_repo(settings, cache, fake_fetcher)
    req = year_req(repo, 2025)
    cache.put(req, noaa_year_body(2025), ttl_seconds=3600, now=FIXED_NOW)
    cache._corrupt(req)
    fake_fetcher.add(req, noaa_year_body(2025))
    ds = repo.get_station_daily(STATION, date(2025, 1, 1), date(2025, 1, 2))
    assert ds.provenance.freshness is Freshness.LIVE
    assert len(fake_fetcher.calls) == 1
