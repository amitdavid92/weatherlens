"""Normalized, source-agnostic data contracts for the data layer.

Design rules (see docs/DECISIONS.md):
- Missing, not-applicable, insufficient-data and observed-zero are distinct states; nothing is
  coerced to zero.
- Every dataset carries exactly one Provenance; NOAA and Open-Meteo values are never mixed in a
  single dataset.
- No heuristic scoring here. Only factual coverage counts.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from weather_risk.data.periods import iter_dates


class SourceId(StrEnum):
    NOAA_GHCN_DAILY = "noaa_ghcn_daily"
    OPEN_METEO_ARCHIVE = "open_meteo_archive"
    FEMA_NRI = "fema_nri"


class GeoResolution(StrEnum):
    STATION = "station"
    GRID_CELL = "grid_cell"
    COUNTY = "county"


class Freshness(StrEnum):
    LIVE = "live"  # fetched from the source during this request
    CACHE = "cache"  # served from a non-expired cache entry
    STALE_CACHE = "stale_cache"  # expired cache entry used because the source failed
    SNAPSHOT = "snapshot"  # committed snapshot used because the source failed


class DataKind(StrEnum):
    OBSERVED = "observed"  # station measurements
    MODELED_REANALYSIS = "modeled_reanalysis"  # ERA5 reanalysis grid
    DERIVED_INDEX = "derived_index"  # FEMA NRI modeled frequencies


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: SourceId
    dataset_name: str
    dataset_version: str | None = None
    data_kind: DataKind
    request_url: str
    query_params: dict[str, str] = Field(default_factory=dict)
    retrieved_at: datetime
    freshness: Freshness
    geographic_resolution: GeoResolution
    location_id: str  # station id, "lat,lon" of grid cell, or county FIPS
    license: str
    attribution: str


# --------------------------------------------------------------------------- climate


class ObservationStatus(StrEnum):
    MEASURED = "measured"  # a reported value (for accumulations: > 0; for others: any value)
    ZERO = "zero"  # accumulation element reported as exactly 0 with no trace flag
    TRACE = "trace"  # accumulation element flagged as trace (non-measurable amount)
    MISSING = "missing"  # no value reported for this date/element


class ClimateElement(StrEnum):
    """Normalized element names, shared by NOAA and Open-Meteo (values never mixed)."""

    SNOWFALL = "snowfall"  # mm of new snow per day
    PRECIPITATION = "precipitation"  # mm liquid equivalent per day
    TMIN = "tmin"  # °C
    TMAX = "tmax"  # °C
    WIND_SPEED_MAX = "wind_speed_max"  # m/s (Open-Meteo daily max 10 m wind)
    WIND_AVG = "wind_avg"  # m/s (NOAA AWND daily average wind)
    WIND_GUST_MAX = "wind_gust_max"  # m/s (NOAA WSF5 fastest 5-s gust / Open-Meteo max gust)


# Only accumulation elements have zero/trace semantics. Temperatures (including negative values
# and exactly 0 °C) and winds are simply measured or missing.
ACCUMULATION_ELEMENTS: frozenset[ClimateElement] = frozenset(
    {ClimateElement.SNOWFALL, ClimateElement.PRECIPITATION}
)

NORMALIZED_UNITS: dict[ClimateElement, str] = {
    ClimateElement.SNOWFALL: "mm",
    ClimateElement.PRECIPITATION: "mm",
    ClimateElement.TMIN: "degC",
    ClimateElement.TMAX: "degC",
    ClimateElement.WIND_SPEED_MAX: "m/s",
    ClimateElement.WIND_AVG: "m/s",
    ClimateElement.WIND_GUST_MAX: "m/s",
}


class DailyValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ObservationStatus
    value: float | None = None  # normalized unit; None iff status == MISSING
    unit: str
    original_value: str | None = None  # exactly as returned by the source
    original_unit: str
    measurement_flag: str | None = None
    quality_flag: str | None = None
    source_flag: str | None = None

    @property
    def quality_flagged(self) -> bool:
        return bool(self.quality_flag)

    @model_validator(mode="after")
    def _value_matches_status(self) -> DailyValue:
        if self.status is ObservationStatus.MISSING and self.value is not None:
            raise ValueError("missing observations must not carry a value")
        if self.status is not ObservationStatus.MISSING and self.value is None:
            raise ValueError(f"status {self.status} requires a value")
        return self


class DailyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    values: dict[ClimateElement, DailyValue]


class CoverageReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    element: ClimateElement
    expected_days: int
    reported_days: int
    missing_days: int
    quality_flagged_days: int
    missing_dates_sample: list[date] = Field(default_factory=list)  # first 31 missing dates

    @property
    def completeness(self) -> float:
        return self.reported_days / self.expected_days if self.expected_days else 0.0


class ClimateDataset(BaseModel):
    """Daily observations for ONE location from ONE source over a contiguous date range."""

    model_config = ConfigDict(frozen=True)

    provenance: Provenance
    start: date
    end: date
    elements: list[ClimateElement]
    records: list[DailyRecord]
    metadata: dict[str, str | float | None] = Field(default_factory=dict)
    # When assembled from several canonical (calendar-year) requests, the provenance of each
    # component; `provenance` then summarizes them (oldest retrieval, least-fresh state).
    components: list[Provenance] = Field(default_factory=list)

    @model_validator(mode="after")
    def _contiguous_and_complete(self) -> ClimateDataset:
        expected = list(iter_dates(self.start, self.end))
        got = [r.date for r in self.records]
        if got != expected:
            raise ValueError(
                "records must cover every date from start to end exactly once, in order"
            )
        for r in self.records:
            if set(r.values) != set(self.elements):
                raise ValueError(f"record {r.date} does not carry exactly the declared elements")
        return self

    def coverage(self, element: ClimateElement) -> CoverageReport:
        missing = [
            r.date for r in self.records if r.values[element].status is ObservationStatus.MISSING
        ]
        flagged = sum(1 for r in self.records if r.values[element].quality_flagged)
        return CoverageReport(
            element=element,
            expected_days=len(self.records),
            reported_days=len(self.records) - len(missing),
            missing_days=len(missing),
            quality_flagged_days=flagged,
            missing_dates_sample=missing[:31],
        )

    def status_counts(self, element: ClimateElement) -> dict[ObservationStatus, int]:
        counts = {s: 0 for s in ObservationStatus}
        for r in self.records:
            counts[r.values[element].status] += 1
        return counts

    def slice(self, start: date, end: date) -> ClimateDataset:
        if start < self.start or end > self.end or start > end:
            raise ValueError("slice outside dataset range")
        recs = [r for r in self.records if start <= r.date <= end]
        return self.model_copy(update={"start": start, "end": end, "records": recs})


# --------------------------------------------------------------------------- hazards


class HazardCode(StrEnum):
    """FEMA NRI hazard prefixes used in this project (weather-related only)."""

    HURRICANE = "HRCN"
    COASTAL_FLOODING = "CFLD"
    INLAND_FLOODING = "IFLD"
    WINTER_WEATHER = "WNTW"
    ICE_STORM = "ISTM"
    COLD_WAVE = "CWAV"
    TORNADO = "TRND"
    HAIL = "HAIL"
    STRONG_WIND = "SWND"
    HEAT_WAVE = "HWAV"


class HazardStatus(StrEnum):
    """Per-hazard data state, derived from AFREQ + the EAL rating label.

    Mapping (verified empirically over all 3,232 NRI v1.20 records, 2026-11-25, and against
    NRI Technical Documentation Dec 2025 §3.2 Table 2):
      AFREQ null + EALR "Not Applicable"            -> NOT_APPLICABLE ("not considered at risk")
      AFREQ null + EALR "Insufficient Data"         -> INSUFFICIENT_DATA ("source data not available")
      AFREQ == 0 + EALR "No Expected Annual Losses" -> OBSERVED_ZERO (frequency is zero)
      AFREQ > 0  + any rating label                 -> OBSERVED
      anything else                                 -> UNKNOWN (conservative; never coerced)
    """

    OBSERVED = "observed"
    OBSERVED_ZERO = "observed_zero"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_DATA = "insufficient_data"
    UNKNOWN = "unknown"


class HazardValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    hazard: HazardCode
    status: HazardStatus
    annualized_frequency: float | None  # raw AFREQ exactly as published (None = null)
    events: float | None  # raw *_EVNTS (recorded events/event-days in period of record)
    eal_rating: str | None  # raw *_EALR label
    risk_rating: str | None  # raw *_RISKR label (Risk Index; includes SoVI/resilience) — context
    risk_score: float | None  # raw *_RISKS national percentile — context only, not used to rank

    @property
    def usable_frequency(self) -> float | None:
        """Frequency usable as a fact: only for OBSERVED/OBSERVED_ZERO states."""
        if self.status in (HazardStatus.OBSERVED, HazardStatus.OBSERVED_ZERO):
            return self.annualized_frequency
        return None


class CountyHazardRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    county_fips: str
    county_name: str
    state_abbrev: str
    nri_version: str
    hazards: dict[HazardCode, HazardValue]
    provenance: Provenance

    @field_validator("county_fips")
    @classmethod
    def _fips5(cls, v: str) -> str:
        if len(v) != 5 or not v.isdigit():
            raise ValueError(f"county FIPS must be a 5-digit string, got {v!r}")
        return v


TERRITORY_STATE_ABBREVS: frozenset[str] = frozenset({"PR", "GU", "AS", "MP", "VI"})


class HazardReferencePopulation(BaseModel):
    """National NRI county table (compact) used later for percentile normalization.

    `records` holds ALL counties returned by the source (states, DC and territories). The
    reference population for normalization is `reference_records` (50 states + DC).
    """

    model_config = ConfigDict(frozen=True)

    nri_version: str
    total_count: int
    records: list[CountyHazardRecord]
    provenance: Provenance

    @model_validator(mode="after")
    def _validate(self) -> HazardReferencePopulation:
        if len(self.records) != self.total_count:
            raise ValueError(f"expected {self.total_count} records, got {len(self.records)}")
        fips = [r.county_fips for r in self.records]
        if len(set(fips)) != len(fips):
            raise ValueError("duplicate county FIPS in reference population")
        versions = {r.nri_version for r in self.records}
        if versions != {self.nri_version}:
            raise ValueError(f"mixed NRI versions in reference population: {sorted(versions)}")
        return self

    @property
    def reference_records(self) -> list[CountyHazardRecord]:
        return [r for r in self.records if r.state_abbrev not in TERRITORY_STATE_ABBREVS]

    @property
    def excluded_records(self) -> list[CountyHazardRecord]:
        return [r for r in self.records if r.state_abbrev in TERRITORY_STATE_ABBREVS]

    def get(self, fips: str) -> CountyHazardRecord | None:
        for r in self.records:
            if r.county_fips == fips:
                return r
        return None

    def status_counts(self, hazard: HazardCode, reference_only: bool = True) -> dict[str, int]:
        recs = self.reference_records if reference_only else self.records
        counts: dict[str, int] = {s.value: 0 for s in HazardStatus}
        for r in recs:
            counts[r.hazards[hazard].status.value] += 1
        return counts


# --------------------------------------------------------------------------- snapshot


class SnapshotEntry(BaseModel):
    key: str  # deterministic request key (same as cache key)
    file: str  # path relative to snapshot dir
    source_id: SourceId
    url: str
    params: dict[str, str]
    retrieved_at: datetime
    dataset_version: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    location_id: str | None = None
    body_sha256: str  # sha256 of the uncompressed response body
    bytes_uncompressed: int


class SnapshotManifest(BaseModel):
    schema_version: Literal[1] = 1
    generated_at: datetime
    generator: str
    description: str
    licenses: dict[str, str]
    entries: list[SnapshotEntry]


class CacheEntryMeta(BaseModel):
    key: str
    source_id: str
    url: str
    fetched_at: datetime
    expires_at: datetime
    dataset_version: str | None = None
    body_sha256: str
