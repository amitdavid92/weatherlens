"""Data access with explicit availability semantics.

Resolution order for every canonical request:
  1. fresh cache entry  -> Freshness.CACHE
  2. live fetch         -> Freshness.LIVE (validated by the parser BEFORE it is cached)
  3. on failure: stale cache entry -> Freshness.STALE_CACHE
  4. committed snapshot -> Freshness.SNAPSHOT
  5. otherwise raise DataUnavailableError (never fabricated, never filled)

Climate data is requested in canonical calendar-year chunks so that cache and snapshot entries
can serve any sub-range (e.g. Denver 2025 from a 2016–2025 snapshot).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import TypeVar

from weather_risk.config import Settings
from weather_risk.data.adapters import fema_nri, noaa_ghcn, open_meteo
from weather_risk.data.cache import ResponseCache
from weather_risk.data.errors import (
    DataUnavailableError,
    ExternalDataError,
    InvalidRequestError,
    InvalidResponseError,
)
from weather_risk.data.http import HttpFetcher, SourceRequest
from weather_risk.data.models import (
    ClimateDataset,
    CountyHazardRecord,
    Freshness,
    HazardReferencePopulation,
    Provenance,
)
from weather_risk.data.periods import canonical_year_chunk, validate_range
from weather_risk.data.snapshot import SnapshotStore

log = logging.getLogger("weather_risk.repository")
T = TypeVar("T")

_FRESHNESS_ORDER = [Freshness.LIVE, Freshness.CACHE, Freshness.STALE_CACHE, Freshness.SNAPSHOT]
RECENT_WINDOW_DAYS = 30


def least_fresh(values: list[Freshness]) -> Freshness:
    return max(values, key=_FRESHNESS_ORDER.index)


class DataRepository:
    def __init__(
        self,
        *,
        fetcher: HttpFetcher,
        cache: ResponseCache,
        snapshot: SnapshotStore | None,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.fetcher = fetcher
        self.cache = cache
        self.snapshot = snapshot
        self.settings = settings
        self._clock = clock

    # ------------------------------------------------------------------ helpers
    def today(self) -> date:
        return self._clock().date()

    def _climate_ttl(self, chunk_end: date) -> int:
        if chunk_end >= self.today() - timedelta(days=RECENT_WINDOW_DAYS):
            return self.settings.ttl_recent_seconds
        return self.settings.ttl_historical_seconds

    def _resolve(
        self,
        req: SourceRequest,
        parse: Callable[[bytes, datetime, Freshness], T],
        *,
        ttl_seconds: int,
        what: str,
        version_of: Callable[[T], str | None] = lambda _: None,
    ) -> T:
        now = self._clock()
        causes: list[str] = []

        cached = self.cache.get(req)
        if cached is not None and cached.is_fresh(now):
            try:
                result = parse(cached.body, cached.fetched_at, Freshness.CACHE)
                log.info("cache_hit", extra={"source": req.source_id, "what": what})
                return result
            except ExternalDataError as exc:
                log.warning("cache_entry_invalid", extra={"what": what, "error": str(exc)})
                self.cache.delete(req)
                causes.append(f"cached entry invalid: {exc}")
                cached = None

        if self.settings.offline:
            causes.append("offline mode: live fetch skipped")
        else:
            try:
                resp = self.fetcher.get(req)
                result = parse(resp.body, now, Freshness.LIVE)  # validate before caching
                self.cache.put(
                    req,
                    resp.body,
                    ttl_seconds=ttl_seconds,
                    dataset_version=version_of(result),
                    now=now,
                )
                return result
            except ExternalDataError as exc:
                causes.append(f"live fetch failed: {exc}")
                log.warning("live_fetch_failed", extra={"what": what, "error": str(exc)})

        if cached is not None:
            try:
                result = parse(cached.body, cached.fetched_at, Freshness.STALE_CACHE)
                log.warning("serving_stale_cache", extra={"what": what})
                return result
            except ExternalDataError as exc:
                causes.append(f"stale cache invalid: {exc}")

        if self.snapshot is not None:
            hit = self.snapshot.get(req)
            if hit is not None:
                body, entry = hit
                try:
                    result = parse(body, entry.retrieved_at, Freshness.SNAPSHOT)
                    log.warning("serving_snapshot", extra={"what": what, "file": entry.file})
                    return result
                except ExternalDataError as exc:
                    causes.append(f"snapshot invalid: {exc}")
            else:
                causes.append("no snapshot entry")
        else:
            causes.append("no snapshot configured")

        raise DataUnavailableError(what, causes)

    @staticmethod
    def _combine(chunks: list[ClimateDataset], start: date, end: date) -> ClimateDataset:
        sliced = []
        for c in chunks:
            s, e = max(start, c.start), min(end, c.end)
            sliced.append(c.slice(s, e))
        components = [c.provenance for c in chunks]
        first = components[0]
        summary = first.model_copy(
            update={
                "retrieved_at": min(p.retrieved_at for p in components),
                "freshness": least_fresh([p.freshness for p in components]),
                "query_params": {
                    **{k: v for k, v in first.query_params.items()},
                    **_range_params(first, start, end),
                },
            }
        )
        return ClimateDataset(
            provenance=summary,
            start=start,
            end=end,
            elements=chunks[0].elements,
            records=[r for c in sliced for r in c.records],
            metadata=chunks[0].metadata,
            components=components,
        )

    # ------------------------------------------------------------------ climate
    def noaa_year_request(self, station_id: str, year: int) -> SourceRequest:
        s, e = canonical_year_chunk(year, today=self.today())
        return noaa_ghcn.build_request(station_id, s, e)

    def get_station_daily(self, station_id: str, start: date, end: date) -> ClimateDataset:
        """NOAA GHCN-Daily observations (primary climate source)."""
        noaa_ghcn.validate_station_id(station_id)
        validate_range(start, end, today=self.today(), earliest=noaa_ghcn.EARLIEST)
        chunks = []
        for year in range(start.year, end.year + 1):
            req = self.noaa_year_request(station_id, year)

            def parse(body: bytes, at: datetime, fr: Freshness, req: SourceRequest = req):
                return noaa_ghcn.parse_response(body, req, retrieved_at=at, freshness=fr)

            chunks.append(
                self._resolve(
                    req,
                    parse,
                    ttl_seconds=self._climate_ttl(date.fromisoformat(req.params["endDate"])),
                    what=f"NOAA {station_id} {year}",
                )
            )
        return self._combine(chunks, start, end)

    def open_meteo_year_request(
        self, latitude: float, longitude: float, timezone: str, year: int
    ) -> SourceRequest:
        s, e = canonical_year_chunk(year, today=self.today())
        return open_meteo.build_request(latitude, longitude, s, e, timezone)

    def get_open_meteo_daily(
        self, latitude: float, longitude: float, timezone: str, start: date, end: date
    ) -> ClimateDataset:
        """Open-Meteo ERA5 reanalysis (alternative, clearly labeled modeled source)."""
        validate_range(start, end, today=self.today(), earliest=open_meteo.EARLIEST)
        chunks = []
        for year in range(start.year, end.year + 1):
            req = self.open_meteo_year_request(latitude, longitude, timezone, year)

            def parse(body: bytes, at: datetime, fr: Freshness, req: SourceRequest = req):
                return open_meteo.parse_response(body, req, retrieved_at=at, freshness=fr)

            chunks.append(
                self._resolve(
                    req,
                    parse,
                    ttl_seconds=self._climate_ttl(date.fromisoformat(req.params["end_date"])),
                    what=f"Open-Meteo {latitude},{longitude} {year}",
                    version_of=lambda _: open_meteo.MODEL,
                )
            )
        return self._combine(chunks, start, end)

    # ------------------------------------------------------------------ hazards
    def get_county_hazards(self, fips: str) -> CountyHazardRecord:
        req = fema_nri.build_county_request(fips)

        def parse(body: bytes, at: datetime, fr: Freshness) -> CountyHazardRecord:
            return fema_nri.parse_county(body, req, retrieved_at=at, freshness=fr)

        return self._resolve(
            req,
            parse,
            ttl_seconds=self.settings.ttl_nri_seconds,
            what=f"NRI county {fips}",
            version_of=lambda r: r.nri_version,
        )

    def get_hazard_reference(self) -> HazardReferencePopulation:
        """All NRI county records (paged), validated for count, uniqueness and version."""
        count_req = fema_nri.build_count_request()
        count = self._resolve(
            count_req,
            lambda body, at, fr: fema_nri.parse_count(body),
            ttl_seconds=self.settings.ttl_nri_seconds,
            what="NRI county count",
        )
        pages, freshness = [], []
        retrieved: list[datetime] = []
        first_req: SourceRequest | None = None
        for offset in range(0, count, fema_nri.PAGE_SIZE):
            req = fema_nri.build_page_request(offset)
            first_req = first_req or req

            def parse(body: bytes, at: datetime, fr: Freshness, req: SourceRequest = req):
                recs, _ = fema_nri.parse_features(body, req, retrieved_at=at, freshness=fr)
                if not recs:
                    raise InvalidResponseError(
                        fema_nri.SOURCE, f"empty page ({req.params['resultOffset']})"
                    )
                return recs

            recs = self._resolve(
                req,
                parse,
                ttl_seconds=self.settings.ttl_nri_seconds,
                what=f"NRI page offset={offset}",
                version_of=lambda rs: rs[0].nri_version if rs else None,
            )
            pages.append(recs)
            freshness.append(recs[0].provenance.freshness)
            retrieved.append(recs[0].provenance.retrieved_at)
        assert first_req is not None
        return fema_nri.assemble_reference(
            pages,
            expected_count=count,
            first_req=first_req,
            retrieved_at=min(retrieved),
            freshness=least_fresh(freshness),
        )

    def get_county_with_reference(
        self, fips: str
    ) -> tuple[CountyHazardRecord, HazardReferencePopulation]:
        """County record + national reference, guaranteed to share one NRI version.

        If the directly fetched county record and the reference come from different NRI
        releases (e.g. live county vs. older snapshot reference), the county record is taken
        from the reference itself so both are consistent; the mismatch is logged.
        """
        reference = self.get_hazard_reference()
        try:
            record = self.get_county_hazards(fips)
        except DataUnavailableError:
            record = None
        if record is None or record.nri_version != reference.nri_version:
            if record is not None:
                log.warning(
                    "nri_version_mismatch_using_reference_record",
                    extra={
                        "fips": fips,
                        "county": record.nri_version,
                        "ref": reference.nri_version,
                    },
                )
            record = reference.get(fips)
            if record is None:
                raise DataUnavailableError(f"NRI county {fips}", ["not in reference population"])
        fema_nri.ensure_same_version(record, reference)
        return record, reference


def _range_params(p: Provenance, start: date, end: date) -> dict[str, str]:
    if "startDate" in p.query_params:
        return {"startDate": start.isoformat(), "endDate": end.isoformat()}
    if "start_date" in p.query_params:
        return {"start_date": start.isoformat(), "end_date": end.isoformat()}
    return {}


def build_repository(settings: Settings, *, use_snapshot: bool = True) -> DataRepository:
    if settings.http_max_attempts < 1:
        raise InvalidRequestError("http_max_attempts must be >= 1")
    return DataRepository(
        fetcher=HttpFetcher(
            timeout_seconds=settings.http_timeout_seconds, max_attempts=settings.http_max_attempts
        ),
        cache=ResponseCache(settings.cache_path),
        snapshot=SnapshotStore(settings.snapshot_dir) if use_snapshot else None,
        settings=settings,
    )
