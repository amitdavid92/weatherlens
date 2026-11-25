from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from tests.conftest import load_fixture
from weather_risk.data.adapters import fema_nri
from weather_risk.data.errors import (
    DatasetVersionMismatchError,
    InvalidRequestError,
    InvalidResponseError,
)
from weather_risk.data.models import Freshness, HazardStatus
from weather_risk.data.models import HazardCode as H

AT = datetime(2026, 11, 25, tzinfo=UTC)


def county(name: str):
    req, body = load_fixture(name)
    return fema_nri.parse_county(body, req, retrieved_at=AT, freshness=Freshness.LIVE)


def edge(name: str):
    req, body = load_fixture(name)
    recs, _ = fema_nri.parse_features(body, req, retrieved_at=AT, freshness=Freshness.LIVE)
    assert len(recs) == 1
    return recs[0]


def test_miami_vs_houston_hurricane_and_flood_fields_present():
    miami, houston = county("nri_county_12086"), county("nri_county_48201")
    for rec in (miami, houston):
        for h in (H.HURRICANE, H.COASTAL_FLOODING, H.INLAND_FLOODING):
            v = rec.hazards[h]
            assert v.status is HazardStatus.OBSERVED
            assert v.annualized_frequency and v.annualized_frequency > 0
    assert miami.nri_version == houston.nri_version


def test_inland_county_hurricane_is_not_applicable_not_zero():
    denver = county("nri_county_08031")
    v = denver.hazards[H.HURRICANE]
    assert v.status is HazardStatus.NOT_APPLICABLE
    assert v.annualized_frequency is None
    assert v.usable_frequency is None


def test_dallas_has_all_weather_hazard_records():
    dallas = county("nri_county_48113")
    assert set(dallas.hazards) == set(H)
    assert dallas.hazards[H.COASTAL_FLOODING].status is HazardStatus.NOT_APPLICABLE
    for h in (H.TORNADO, H.HAIL, H.STRONG_WIND, H.INLAND_FLOODING, H.ICE_STORM, H.HEAT_WAVE):
        assert dallas.hazards[h].status is HazardStatus.OBSERVED


def test_real_observed_zero_record():
    rec = edge("nri_edge_hrcn_zero")
    v = rec.hazards[H.HURRICANE]
    assert v.status is HazardStatus.OBSERVED_ZERO
    assert v.annualized_frequency == 0.0
    assert v.usable_frequency == 0.0
    assert v.eal_rating == "No Expected Annual Losses"


def test_real_insufficient_data_records_are_not_zero():
    guam = edge("nri_edge_territory")
    assert guam.state_abbrev == "GU"
    assert guam.hazards[H.TORNADO].status is HazardStatus.INSUFFICIENT_DATA
    assert guam.hazards[H.TORNADO].usable_frequency is None
    alaska = edge("nri_edge_alaska_hwav")
    assert alaska.hazards[H.HEAT_WAVE].status is HazardStatus.INSUFFICIENT_DATA
    assert alaska.hazards[H.HURRICANE].status is HazardStatus.NOT_APPLICABLE


@pytest.mark.parametrize(
    "afreq,ealr,expected",
    [
        (None, "Not Applicable", HazardStatus.NOT_APPLICABLE),
        (None, "Insufficient Data", HazardStatus.INSUFFICIENT_DATA),
        (None, "Very High", HazardStatus.UNKNOWN),
        (None, None, HazardStatus.UNKNOWN),
        (0.0, "No Expected Annual Losses", HazardStatus.OBSERVED_ZERO),
        (0.0, "Very Low", HazardStatus.UNKNOWN),
        (0.0, None, HazardStatus.UNKNOWN),
        (0.3, "Very High", HazardStatus.OBSERVED),
        (0.3, "No Expected Annual Losses", HazardStatus.OBSERVED),  # zero exposure, freq > 0
        (0.3, "Insufficient Data", HazardStatus.UNKNOWN),
        (0.3, None, HazardStatus.UNKNOWN),
        (-1.0, "Very Low", HazardStatus.UNKNOWN),
    ],
)
def test_status_derivation_is_conservative(afreq, ealr, expected):
    assert fema_nri.derive_status(afreq, ealr) is expected


def _page(req_offset: int, records: list[dict], exceeded: bool = False) -> tuple:
    req = fema_nri.build_page_request(req_offset, page_size=3)
    body = json.dumps(
        {"features": [{"attributes": a} for a in records], "exceededTransferLimit": exceeded}
    ).encode()
    return req, body


def _real_page_records(name: str) -> list[dict]:
    _, body = load_fixture(name)
    return [f["attributes"] for f in json.loads(body)["features"]]


def test_pagination_assembles_and_validates_real_pages():
    p0 = _real_page_records("nri_page_size3_offset0")
    p1 = _real_page_records("nri_page_size3_offset3")
    pages = []
    for off, recs in ((0, p0), (3, p1)):
        req, body = _page(off, recs, exceeded=(off == 0))
        parsed, exceeded = fema_nri.parse_features(
            body, req, retrieved_at=AT, freshness=Freshness.LIVE
        )
        assert exceeded is (off == 0)
        pages.append(parsed)
    ref = fema_nri.assemble_reference(
        pages, expected_count=6, first_req=req, retrieved_at=AT, freshness=Freshness.LIVE
    )
    assert ref.total_count == 6
    assert [r.county_fips for r in ref.records] == sorted(r.county_fips for r in ref.records)
    assert ref.provenance.location_id == "national"


def test_pagination_count_mismatch_rejected():
    recs = _real_page_records("nri_page_size3_offset0")
    req, body = _page(0, recs)
    parsed, _ = fema_nri.parse_features(body, req, retrieved_at=AT, freshness=Freshness.LIVE)
    with pytest.raises(InvalidResponseError, match="expected 6"):
        fema_nri.assemble_reference(
            [parsed], expected_count=6, first_req=req, retrieved_at=AT, freshness=Freshness.LIVE
        )


def test_duplicate_fips_across_pages_rejected():
    recs = _real_page_records("nri_page_size3_offset0")
    req, body = _page(0, recs)
    parsed, _ = fema_nri.parse_features(body, req, retrieved_at=AT, freshness=Freshness.LIVE)
    with pytest.raises(InvalidResponseError, match="duplicate"):
        fema_nri.assemble_reference(
            [parsed, parsed], expected_count=6, first_req=req, retrieved_at=AT,
            freshness=Freshness.LIVE,
        )  # fmt: skip


def test_mixed_versions_across_pages_rejected():
    p0 = _real_page_records("nri_page_size3_offset0")
    p1 = _real_page_records("nri_page_size3_offset3")
    for a in p1:
        a["NRI_VER"] = "March 2023"
    pages = []
    for off, recs in ((0, p0), (3, p1)):
        req, body = _page(off, recs)
        pages.append(
            fema_nri.parse_features(body, req, retrieved_at=AT, freshness=Freshness.LIVE)[0]
        )
    with pytest.raises(DatasetVersionMismatchError):
        fema_nri.assemble_reference(
            pages, expected_count=6, first_req=req, retrieved_at=AT, freshness=Freshness.LIVE
        )


def test_county_and_reference_version_must_match():
    rec = county("nri_county_48113")
    p0 = _real_page_records("nri_page_size3_offset0")
    for a in p0:
        a["NRI_VER"] = "March 2023"
    req, body = _page(0, p0)
    parsed, _ = fema_nri.parse_features(body, req, retrieved_at=AT, freshness=Freshness.LIVE)
    ref = fema_nri.assemble_reference(
        [parsed], expected_count=3, first_req=req, retrieved_at=AT, freshness=Freshness.LIVE
    )
    with pytest.raises(DatasetVersionMismatchError):
        fema_nri.ensure_same_version(rec, ref)


def test_reference_population_excludes_territories_from_reference_records():
    gu = edge("nri_edge_territory")
    ak = edge("nri_edge_alaska_hwav")
    req = fema_nri.build_page_request(0)
    ref = fema_nri.assemble_reference(
        [[gu, ak]], expected_count=2, first_req=req, retrieved_at=AT, freshness=Freshness.LIVE
    )
    assert [r.state_abbrev for r in ref.reference_records] == ["AK"]
    assert [r.state_abbrev for r in ref.excluded_records] == ["GU"]
    counts = ref.status_counts(H.HEAT_WAVE)
    assert counts["insufficient_data"] == 1  # Alaska stays in the population, flagged per hazard


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda a: a.update(STCOFIPS=8031), "bad STCOFIPS"),
        (lambda a: a.update(STCOFIPS="8031"), "bad STCOFIPS"),
        (lambda a: a.update(NRI_VER=""), "bad NRI_VER"),
        (lambda a: a.pop("HRCN_AFREQ"), "missing field"),
        (lambda a: a.update(HRCN_AFREQ="0.3"), "non-numeric"),
        (lambda a: a.pop("COUNTY"), "missing fields"),
    ],
)
def test_invalid_records_rejected(mutate, match):
    attrs = _real_page_records("nri_page_size3_offset0")[0]
    mutate(attrs)
    req, body = _page(0, [attrs])
    with pytest.raises(InvalidResponseError, match=match):
        fema_nri.parse_features(body, req, retrieved_at=AT, freshness=Freshness.LIVE)


def test_arcgis_error_payload_and_html_rejected():
    req = fema_nri.build_county_request("48113")
    with pytest.raises(InvalidResponseError, match="ArcGIS error"):
        fema_nri.parse_county(
            b'{"error":{"code":400,"message":"bad"}}', req, retrieved_at=AT,
            freshness=Freshness.LIVE,
        )  # fmt: skip
    with pytest.raises(InvalidResponseError, match="invalid JSON"):
        fema_nri.parse_county(b"<html>", req, retrieved_at=AT, freshness=Freshness.LIVE)


def test_county_query_must_return_exactly_the_requested_fips():
    req = fema_nri.build_county_request("48201")
    _, body = load_fixture("nri_county_48113")
    with pytest.raises(InvalidResponseError, match="FIPS mismatch"):
        fema_nri.parse_county(body, req, retrieved_at=AT, freshness=Freshness.LIVE)
    with pytest.raises(InvalidResponseError, match="exactly 1"):
        fema_nri.parse_county(b'{"features":[]}', req, retrieved_at=AT, freshness=Freshness.LIVE)


def test_count_parsing():
    _, body = load_fixture("nri_count")
    assert fema_nri.parse_count(body) > 3000
    with pytest.raises(InvalidResponseError):
        fema_nri.parse_count(b'{"count": 0}')


@pytest.mark.parametrize("fips", ["8031", "080310", "abcde", 8031])
def test_fips_request_validation(fips):
    with pytest.raises(InvalidRequestError):
        fema_nri.build_county_request(fips)
