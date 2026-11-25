"""Builders for small synthetic datasets with hand-computable expectations."""

from __future__ import annotations

from datetime import UTC, date, datetime

from weather_risk.data.models import (
    NORMALIZED_UNITS,
    ClimateDataset,
    ClimateElement,
    CountyHazardRecord,
    DailyRecord,
    DailyValue,
    DataKind,
    Freshness,
    GeoResolution,
    HazardCode,
    HazardReferencePopulation,
    HazardStatus,
    HazardValue,
    ObservationStatus,
    Provenance,
    SourceId,
)
from weather_risk.data.periods import iter_dates

AT = datetime(2026, 11, 25, tzinfo=UTC)


def prov(source: SourceId = SourceId.NOAA_GHCN_DAILY, location: str = "TEST") -> Provenance:
    kind = {
        SourceId.NOAA_GHCN_DAILY: (DataKind.OBSERVED, GeoResolution.STATION),
        SourceId.OPEN_METEO_ARCHIVE: (DataKind.MODELED_REANALYSIS, GeoResolution.GRID_CELL),
        SourceId.FEMA_NRI: (DataKind.DERIVED_INDEX, GeoResolution.COUNTY),
    }[source]
    return Provenance(
        source_id=source, dataset_name="test", data_kind=kind[0], request_url="https://t",
        retrieved_at=AT, freshness=Freshness.LIVE, geographic_resolution=kind[1],
        location_id=location, license="test", attribution="test",
    )  # fmt: skip


def dv(element: ClimateElement, spec) -> DailyValue:
    """spec: None -> missing; ("T",) -> trace; ("Q", v) -> quality-flagged value; number -> value."""
    unit = NORMALIZED_UNITS[element]
    accumulation = element in (ClimateElement.SNOWFALL, ClimateElement.PRECIPITATION)
    if spec is None:
        return DailyValue(status=ObservationStatus.MISSING, unit=unit, original_unit=unit)
    if spec == ("T",):
        return DailyValue(status=ObservationStatus.TRACE, value=0.0, unit=unit,
                          original_unit=unit, measurement_flag="T")  # fmt: skip
    qflag = None
    if isinstance(spec, tuple) and spec[0] == "Q":
        qflag, spec = "X", spec[1]
    v = float(spec)
    status = ObservationStatus.MEASURED
    if accumulation and v == 0:
        status = ObservationStatus.ZERO
    return DailyValue(status=status, value=v, unit=unit, original_unit=unit, quality_flag=qflag)


def dataset(
    start: date,
    end: date,
    columns: dict[ClimateElement, list],
    source: SourceId = SourceId.NOAA_GHCN_DAILY,
) -> ClimateDataset:
    dates = list(iter_dates(start, end))
    for el, vals in columns.items():
        assert len(vals) == len(dates), (el, len(vals), len(dates))
    records = [
        DailyRecord(date=d, values={el: dv(el, columns[el][i]) for el in columns})
        for i, d in enumerate(dates)
    ]
    return ClimateDataset(provenance=prov(source), start=start, end=end,
                          elements=list(columns), records=records)  # fmt: skip


def hv(hazard: HazardCode, spec) -> HazardValue:
    """spec: number -> observed (>0) / observed_zero (0); 'NA' | 'ID' | 'UNK' -> states."""
    if spec == "NA":
        return HazardValue(hazard=hazard, status=HazardStatus.NOT_APPLICABLE,
                           annualized_frequency=None, events=None, eal_rating="Not Applicable",
                           risk_rating=None, risk_score=None)  # fmt: skip
    if spec == "ID":
        return HazardValue(hazard=hazard, status=HazardStatus.INSUFFICIENT_DATA,
                           annualized_frequency=None, events=None, eal_rating="Insufficient Data",
                           risk_rating=None, risk_score=None)  # fmt: skip
    if spec == "UNK":
        return HazardValue(hazard=hazard, status=HazardStatus.UNKNOWN, annualized_frequency=None,
                           events=None, eal_rating=None, risk_rating=None, risk_score=None)  # fmt: skip
    v = float(spec)
    return HazardValue(
        hazard=hazard,
        status=HazardStatus.OBSERVED if v > 0 else HazardStatus.OBSERVED_ZERO,
        annualized_frequency=v, events=None,
        eal_rating="Very Low" if v > 0 else "No Expected Annual Losses",
        risk_rating=None, risk_score=None,
    )  # fmt: skip


def county(fips: str, spec_by_hazard: dict[HazardCode, object] | object, state: str = "TX",
           version: str = "December 2025") -> CountyHazardRecord:  # fmt: skip
    specs = (spec_by_hazard if isinstance(spec_by_hazard, dict)
             else {h: spec_by_hazard for h in HazardCode})  # fmt: skip
    return CountyHazardRecord(
        county_fips=fips, county_name=f"C{fips}", state_abbrev=state, nri_version=version,
        hazards={h: hv(h, specs.get(h, 1.0)) for h in HazardCode},
        provenance=prov(SourceId.FEMA_NRI, fips),
    )  # fmt: skip


def population(records: list[CountyHazardRecord], version: str = "December 2025"):
    return HazardReferencePopulation(nri_version=version, total_count=len(records),
                                     records=records, provenance=prov(SourceId.FEMA_NRI, "national"))  # fmt: skip


# Canonical small population used across tests (same spec for every hazard):
#   A=0 (observed_zero), B=NA, C=1.0, D=2.0, E=2.0, F=3.0, G=insufficient_data, PR territory=5.0
# Eligible N = 6 (A..F), no-exposure tier Z = 2 (A, B). Hand-computed mid-rank percentiles:
#   C: 100·(2+0+0.5)/6 = 41.6667   D,E: 100·(2+1+1)/6 = 66.6667   F: 100·(2+3+0.5)/6 = 91.6667
CANONICAL_SPECS = {"00001": 0, "00002": "NA", "00003": 1.0, "00004": 2.0, "00005": 2.0,
                   "00006": 3.0, "00007": "ID"}  # fmt: skip


def canonical_population(version: str = "December 2025"):
    recs = [county(f, s, version=version) for f, s in CANONICAL_SPECS.items()]
    recs.append(county("72001", 5.0, state="PR", version=version))
    return population(recs, version)
