"""FEMA National Risk Index (NRI) — county table via FEMA's ArcGIS FeatureServer (no auth).

Only the fields needed for this project are requested (per hazard: EVNTS, AFREQ, EALR, RISKR,
RISKS). `RISKS`/`RISKR` are kept for context only: they are community-risk percentiles that
blend exposure value, social vulnerability and resilience, so they are not used for ranking.

Status derivation (no coercion; see HazardStatus docstring and docs/DECISIONS.md D-006):
  AFREQ null + EALR "Not Applicable"            -> NOT_APPLICABLE
  AFREQ null + EALR "Insufficient Data"         -> INSUFFICIENT_DATA
  AFREQ == 0 + EALR "No Expected Annual Losses" -> OBSERVED_ZERO
  AFREQ > 0  + any non-empty EALR               -> OBSERVED
  anything else                                 -> UNKNOWN
"""

from __future__ import annotations

import json
import math
from datetime import datetime

from weather_risk.data.errors import (
    DatasetVersionMismatchError,
    InvalidRequestError,
    InvalidResponseError,
)
from weather_risk.data.http import SourceRequest
from weather_risk.data.models import (
    CountyHazardRecord,
    DataKind,
    Freshness,
    GeoResolution,
    HazardCode,
    HazardReferencePopulation,
    HazardStatus,
    HazardValue,
    Provenance,
    SourceId,
)

BASE_URL = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Counties/FeatureServer/0/query"
)
PAGE_SIZE = 2000  # service maxRecordCount (verified 2026-11-25)
LICENSE = "Public domain (U.S. Government work, FEMA)"
ATTRIBUTION = "FEMA National Risk Index (county level)"

ID_FIELDS = ["STCOFIPS", "COUNTY", "STATEABBRV", "NRI_VER"]
HAZARD_SUFFIXES = ["EVNTS", "AFREQ", "EALR", "RISKR", "RISKS"]
OUT_FIELDS = ID_FIELDS + [f"{h.value}_{s}" for h in HazardCode for s in HAZARD_SUFFIXES]

NOT_APPLICABLE_LABEL = "Not Applicable"
INSUFFICIENT_DATA_LABEL = "Insufficient Data"
NO_EAL_LABEL = "No Expected Annual Losses"

SOURCE = SourceId.FEMA_NRI.value
_SRC = SOURCE


def _validate_fips(fips: str) -> str:
    if not isinstance(fips, str) or len(fips) != 5 or not fips.isdigit():
        raise InvalidRequestError(f"county FIPS must be a 5-digit string, got {fips!r}")
    return fips


def build_count_request() -> SourceRequest:
    return SourceRequest(
        source_id=_SRC,
        url=BASE_URL,
        params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
        location_id="national",
    )


def build_page_request(offset: int, page_size: int | None = None) -> SourceRequest:
    page_size = page_size or PAGE_SIZE
    return SourceRequest(
        source_id=_SRC,
        url=BASE_URL,
        params={
            "where": "1=1",
            "outFields": ",".join(OUT_FIELDS),
            "orderByFields": "STCOFIPS ASC",
            "returnGeometry": "false",
            "resultOffset": str(offset),
            "resultRecordCount": str(page_size),
            "f": "json",
        },
        location_id=f"national:offset={offset}",
    )


def build_county_request(fips: str) -> SourceRequest:
    _validate_fips(fips)
    return SourceRequest(
        source_id=_SRC,
        url=BASE_URL,
        params={
            "where": f"STCOFIPS='{fips}'",
            "outFields": ",".join(OUT_FIELDS),
            "returnGeometry": "false",
            "f": "json",
        },
        location_id=fips,
    )


def _load(body: bytes) -> dict:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidResponseError(_SRC, f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidResponseError(_SRC, "expected a JSON object")
    if "error" in payload:
        raise InvalidResponseError(_SRC, f"ArcGIS error: {payload['error']}")
    return payload


def parse_count(body: bytes) -> int:
    payload = _load(body)
    count = payload.get("count")
    if not isinstance(count, int) or count <= 0:
        raise InvalidResponseError(_SRC, f"invalid count {count!r}")
    return count


def _num(v: object, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int | float) or math.isnan(float(v)):
        raise InvalidResponseError(_SRC, f"non-numeric {field}: {v!r}")
    return float(v)


def derive_status(afreq: float | None, eal_rating: str | None) -> HazardStatus:
    if afreq is None:
        if eal_rating == NOT_APPLICABLE_LABEL:
            return HazardStatus.NOT_APPLICABLE
        if eal_rating == INSUFFICIENT_DATA_LABEL:
            return HazardStatus.INSUFFICIENT_DATA
        return HazardStatus.UNKNOWN
    if afreq < 0:
        return HazardStatus.UNKNOWN
    if afreq == 0:
        return HazardStatus.OBSERVED_ZERO if eal_rating == NO_EAL_LABEL else HazardStatus.UNKNOWN
    # afreq > 0: a positive published frequency. EALR may still be "No Expected Annual Losses"
    # (zero exposure) — the frequency itself is observed.
    if eal_rating in (None, "", NOT_APPLICABLE_LABEL, INSUFFICIENT_DATA_LABEL):
        return HazardStatus.UNKNOWN
    return HazardStatus.OBSERVED


def _parse_feature(attrs: dict, provenance_for: callable) -> CountyHazardRecord:  # type: ignore[valid-type]
    missing = [f for f in ID_FIELDS if f not in attrs]
    if missing:
        raise InvalidResponseError(_SRC, f"record missing fields {missing}")
    fips = attrs["STCOFIPS"]
    if not isinstance(fips, str) or len(fips) != 5 or not fips.isdigit():
        raise InvalidResponseError(_SRC, f"bad STCOFIPS {fips!r}")
    version = attrs["NRI_VER"]
    if not isinstance(version, str) or not version.strip():
        raise InvalidResponseError(_SRC, f"bad NRI_VER for {fips}: {version!r}")

    hazards: dict[HazardCode, HazardValue] = {}
    for h in HazardCode:
        for s in HAZARD_SUFFIXES:
            if f"{h.value}_{s}" not in attrs:
                raise InvalidResponseError(_SRC, f"record {fips} missing field {h.value}_{s}")
        afreq = _num(attrs[f"{h.value}_AFREQ"], f"{h.value}_AFREQ")
        ealr = attrs[f"{h.value}_EALR"]
        hazards[h] = HazardValue(
            hazard=h,
            status=derive_status(afreq, ealr),
            annualized_frequency=afreq,
            events=_num(attrs[f"{h.value}_EVNTS"], f"{h.value}_EVNTS"),
            eal_rating=ealr,
            risk_rating=attrs[f"{h.value}_RISKR"],
            risk_score=_num(attrs[f"{h.value}_RISKS"], f"{h.value}_RISKS"),
        )
    return CountyHazardRecord(
        county_fips=fips,
        county_name=attrs["COUNTY"],
        state_abbrev=attrs["STATEABBRV"],
        nri_version=version.strip(),
        hazards=hazards,
        provenance=provenance_for(fips, version.strip()),
    )


def _provenance(
    req: SourceRequest,
    *,
    location_id: str,
    version: str | None,
    retrieved_at: datetime,
    freshness: Freshness,
) -> Provenance:
    return Provenance(
        source_id=SourceId.FEMA_NRI,
        dataset_name="FEMA National Risk Index — Counties (ArcGIS FeatureServer)",
        dataset_version=version,
        data_kind=DataKind.DERIVED_INDEX,
        request_url=req.url,
        query_params=req.params,
        retrieved_at=retrieved_at,
        freshness=freshness,
        geographic_resolution=GeoResolution.COUNTY,
        location_id=location_id,
        license=LICENSE,
        attribution=ATTRIBUTION,
    )


def parse_features(
    body: bytes, req: SourceRequest, *, retrieved_at: datetime, freshness: Freshness
) -> tuple[list[CountyHazardRecord], bool]:
    """Parse one query page. Returns (records, exceeded_transfer_limit)."""
    payload = _load(body)
    features = payload.get("features")
    if not isinstance(features, list):
        raise InvalidResponseError(_SRC, "missing features array")

    def prov(fips: str, version: str) -> Provenance:
        return _provenance(
            req, location_id=fips, version=version, retrieved_at=retrieved_at, freshness=freshness
        )

    records = []
    for f in features:
        attrs = f.get("attributes") if isinstance(f, dict) else None
        if not isinstance(attrs, dict):
            raise InvalidResponseError(_SRC, "feature without attributes")
        records.append(_parse_feature(attrs, prov))
    return records, bool(payload.get("exceededTransferLimit", False))


def parse_county(
    body: bytes, req: SourceRequest, *, retrieved_at: datetime, freshness: Freshness
) -> CountyHazardRecord:
    records, _ = parse_features(body, req, retrieved_at=retrieved_at, freshness=freshness)
    fips = req.location_id
    if len(records) != 1:
        raise InvalidResponseError(
            _SRC, f"expected exactly 1 record for {fips}, got {len(records)}"
        )
    if records[0].county_fips != fips:
        raise InvalidResponseError(
            _SRC, f"FIPS mismatch: asked {fips}, got {records[0].county_fips}"
        )
    return records[0]


def assemble_reference(
    pages: list[list[CountyHazardRecord]],
    *,
    expected_count: int,
    first_req: SourceRequest,
    retrieved_at: datetime,
    freshness: Freshness,
) -> HazardReferencePopulation:
    records = [r for page in pages for r in page]
    if len(records) != expected_count:
        raise InvalidResponseError(
            _SRC, f"pagination returned {len(records)} records, expected {expected_count}"
        )
    fips = [r.county_fips for r in records]
    dupes = sorted({f for f in fips if fips.count(f) > 1}) if len(set(fips)) != len(fips) else []
    if dupes:
        raise InvalidResponseError(_SRC, f"duplicate STCOFIPS across pages: {dupes[:10]}")
    versions = {r.nri_version for r in records}
    if len(versions) != 1:
        raise DatasetVersionMismatchError(f"NRI pages carry multiple versions: {sorted(versions)}")
    version = versions.pop()
    return HazardReferencePopulation(
        nri_version=version,
        total_count=expected_count,
        records=sorted(records, key=lambda r: r.county_fips),
        provenance=_provenance(
            first_req,
            location_id="national",
            version=version,
            retrieved_at=retrieved_at,
            freshness=freshness,
        ),
    )


def ensure_same_version(record: CountyHazardRecord, reference: HazardReferencePopulation) -> None:
    """County records and the national reference must come from the same NRI release."""
    if record.nri_version != reference.nri_version:
        raise DatasetVersionMismatchError(
            f"county {record.county_fips} is NRI '{record.nri_version}' but reference is "
            f"'{reference.nri_version}'"
        )
