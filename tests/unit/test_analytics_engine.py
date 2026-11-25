"""Engine tests against the COMMITTED SNAPSHOT (offline, real data).

Key expectations are computed independently by reading the raw snapshot JSON directly (bypassing
adapters, stats and scoring), so the engine is not validated against its own output.
"""

from __future__ import annotations

import gzip
import json
from datetime import date

import pytest

from weather_risk.analytics.config import ClimateMetric as M
from weather_risk.analytics.config import Hazard, load_scoring_config
from weather_risk.analytics.engine import (
    AnalyticsEngine,
    UnsupportedHazardError,
    UnsupportedRegionError,
)
from weather_risk.analytics.periods import UnsupportedPeriodError
from weather_risk.catalog import load_catalog
from weather_risk.config import PROJECT_ROOT, Settings
from weather_risk.data.cache import ResponseCache
from weather_risk.data.errors import UnsupportedHubError
from weather_risk.data.http import HttpFetcher
from weather_risk.data.models import SourceId
from weather_risk.data.repository import DataRepository
from weather_risk.data.snapshot import SnapshotStore

SNAP = PROJECT_ROOT / "data" / "snapshot"
TODAY = date(2026, 11, 25)


def make_engine(tmp_path) -> AnalyticsEngine:
    settings = Settings(WEATHER_RISK_CACHE_PATH=tmp_path / "c.db", WEATHER_RISK_OFFLINE=True,
                        _env_file=None)  # fmt: skip
    repo = DataRepository(
        fetcher=HttpFetcher(max_attempts=1), cache=ResponseCache(tmp_path / "c.db"),
        snapshot=SnapshotStore(SNAP), settings=settings,
    )  # fmt: skip
    return AnalyticsEngine(
        repo, load_catalog(PROJECT_ROOT / "config" / "hubs.yaml"),
        load_scoring_config(PROJECT_ROOT / "config" / "scoring.yaml"), today=TODAY,
    )  # fmt: skip


@pytest.fixture(scope="module")
def engine(tmp_path_factory) -> AnalyticsEngine:
    return make_engine(tmp_path_factory.mktemp("engine"))


# ---------------------------------------------------------------- independent raw readers


def raw_noaa_rows(station: str, year: int) -> list[dict]:
    return json.loads(
        gzip.decompress((SNAP / "noaa_ghcn" / f"{station}_{year}.json.gz").read_bytes())
    )


def raw_snow_counts(station: str, years: range) -> tuple[int, int, int]:
    """(measurable, trace, valid) counted straight from raw rows."""
    measurable = trace = valid = 0
    for y in years:
        for r in raw_noaa_rows(station, y):
            if r.get("SNOW") in (None, ""):
                continue
            flags = (r.get("SNOW_ATTRIBUTES") or ",,").split(",")
            if len(flags) > 1 and flags[1]:
                continue  # quality-flagged
            valid += 1
            v = float(r["SNOW"])
            if v > 0:
                measurable += 1
            elif flags[0] == "T":
                trace += 1
    return measurable, trace, valid


def raw_nri(fips: str) -> dict:
    body = json.loads(gzip.decompress((SNAP / "fema_nri" / f"county_{fips}.json.gz").read_bytes()))
    return body["features"][0]["attributes"]


# ---------------------------------------------------------------- scenario 3: Denver 2025


def test_denver_2025_snow_percentages_match_raw_counts(engine):
    m, t, valid = raw_snow_counts("USW00003017", range(2025, 2026))
    meas = engine.get_weather_stat("Denver", M.SNOW_DAYS_MEASURABLE, "last year")
    incl = engine.get_weather_stat("denver_co", M.SNOW_DAYS_TRACE_INCLUSIVE, "2025")
    assert meas.period.start == date(2025, 1, 1) and meas.period.end == date(2025, 12, 31)
    assert meas.status == "ok" and meas.coverage.valid_days == valid
    assert meas.event_days == m
    assert meas.value_percent_of_valid_days == pytest.approx(100 * m / valid)
    assert incl.event_days == m + t
    assert incl.value_percent_of_valid_days == pytest.approx(100 * (m + t) / valid)
    assert meas.coverage.missing_days == 365 - valid - meas.coverage.excluded_days
    ids = {f.fact_id for f in meas.facts}
    assert (
        "denver_co.stat.snow_days_measurable.2025-01-01_2025-12-31.noaa_ghcn_daily.percent" in ids
    )
    assert meas.sources[0].source_id is SourceId.NOAA_GHCN_DAILY


def test_open_meteo_stat_is_labeled_and_separate(engine):
    r = engine.get_weather_stat("Denver", M.SNOW_DAYS_MEASURABLE, "2025",
                                 source=SourceId.OPEN_METEO_ARCHIVE)  # fmt: skip
    assert r.source_id is SourceId.OPEN_METEO_ARCHIVE and r.data_kind == "modeled_reanalysis"
    assert any("reanalysis" in x for x in r.limitations)
    assert all(f.source_ids == [SourceId.OPEN_METEO_ARCHIVE] for f in r.facts)


# ---------------------------------------------------------------- Miami insufficient coverage


def test_miami_snow_insufficient_coverage(engine):
    r = engine.get_weather_stat("Miami", M.SNOW_DAYS_MEASURABLE, "climatology")
    _, _, valid = raw_snow_counts("USW00012839", range(2016, 2026))
    assert r.status == "insufficient_coverage"
    assert r.value_percent_of_valid_days is None and r.event_days is None
    assert r.coverage.valid_days == valid and r.coverage.coverage < 0.9
    profile = engine.get_hub_profile("Miami")
    winter = profile.hazards[Hazard.WINTER]
    assert winter.status == "partial"
    snow_ind = next(i for i in winter.indicators if i.indicator_id == "snow_days_measurable")
    assert snow_ind.score is None and snow_ind.raw_status == "insufficient_coverage"
    assert profile.overall_status == "partial"
    ranking = engine.rank_hubs()
    assert "miami_fl" in [e.hub_id for e in ranking.not_ranked]
    assert "miami_fl" not in [e.hub_id for e in ranking.ranked]


# ---------------------------------------------------------------- scenario 1: Midwest winter


def test_midwest_winter_ranking(engine):
    r = engine.rank_hubs(hazard="winter", region="Midwest")
    ids = [e.hub_id for e in r.ranked]
    assert sorted(ids) == sorted(h.id for h in engine.catalog.in_region("Midwest"))
    assert len(ids) == 6 and not r.not_ranked
    scores = [e.score for e in r.ranked]
    assert scores == sorted(scores, reverse=True)
    assert [e.rank for e in r.ranked] == list(range(1, 7))
    assert all(e.top_contributors for e in r.ranked)


def test_snow_indicator_matches_independent_raw_count(engine):
    m, _, valid = raw_snow_counts("USW00014922", range(2016, 2026))  # Minneapolis
    expected_annual = (m / valid) * (3653 / 10)
    expected_score = 100 * min(max(expected_annual / 60, 0), 1)
    ind = next(i for i in engine.get_hub_profile("Minneapolis").hazards[Hazard.WINTER].indicators
               if i.indicator_id == "snow_days_measurable")  # fmt: skip
    assert ind.raw_value == pytest.approx(expected_annual)
    assert ind.score == pytest.approx(expected_score)


# ---------------------------------------------------------------- scenario 2: Miami vs Houston


def test_miami_vs_houston_hurricane_flood(engine):
    c = engine.compare_hubs(["Miami", "Houston"], ["hurricane", "flood"])
    assert c.hazards == [Hazard.HURRICANE, Hazard.FLOOD]
    miami, houston = raw_nri("12086"), raw_nri("48201")
    for code in ("HRCN", "CFLD", "IFLD"):
        from weather_risk.data.models import HazardCode

        assert c.nri_raw["miami_fl"][HazardCode(code)]["afreq"] == pytest.approx(
            miami[f"{code}_AFREQ"]
        )
        assert c.nri_raw["houston_tx"][HazardCode(code)]["afreq"] == pytest.approx(
            houston[f"{code}_AFREQ"]
        )
    hurricane = c.rows[0]
    # percentiles are monotonic in AFREQ: the leader must be the county with higher raw frequency
    expected_leader = "miami_fl" if miami["HRCN_AFREQ"] > houston["HRCN_AFREQ"] else "houston_tx"
    assert hurricane.leader == expected_leader
    assert any("not rainfall" in x for x in c.limitations)


# ---------------------------------------------------------------- scenario 4: Dallas


def test_dallas_explanation_and_premise_check(engine):
    e = engine.explain_hub_score("Dallas", claimed_band="High")
    p = engine.get_hub_profile("Dallas")
    assert e.overall_score == p.overall_score
    expected_supported = p.overall_score >= 70  # High band threshold from config
    assert e.premise_check is not None and e.premise_check.supported is expected_supported
    contribs = [h.contribution_to_overall for h in e.hazards_by_contribution]
    assert contribs == sorted(contribs, reverse=True)
    assert sum(contribs) == pytest.approx(e.overall_score)
    assert "flood.nri_coastal_flooding" in e.not_applicable  # Dallas County: CFLD not applicable
    assert len(e.top_indicators) == 5


# ---------------------------------------------------------------- all hubs, determinism


def test_all_12_hubs_profiled_and_bounded(engine):
    for h in engine.catalog.hubs:
        p = engine.get_hub_profile(h)
        assert p.nri_version == "December 2025"
        if p.overall_score is not None:
            assert 0 <= p.overall_score <= 100
        for hz in p.hazards.values():
            assert hz.score is None or 0 <= hz.score <= 100


def test_overall_ranking_ties_and_comparability(engine):
    r = engine.rank_hubs()
    assert len(r.ranked) + len(r.not_ranked) == 12
    keys = [(-e.score, e.hub_id) for e in r.ranked]
    assert keys == sorted(keys)
    assert r.nri_version == "December 2025" and r.climate_period.startswith("2016")


def test_repeatable_across_fresh_engines(tmp_path):
    a = make_engine(tmp_path / "a")
    b = make_engine(tmp_path / "b")
    (tmp_path / "a").mkdir(exist_ok=True)
    for hub in ("Dallas", "Miami", "Chicago"):
        pa, pb = a.get_hub_profile(hub), b.get_hub_profile(hub)
        da = pa.model_dump(exclude={"sources"})
        db = pb.model_dump(exclude={"sources"})
        assert da == db
    assert a.rank_hubs().model_dump() == b.rank_hubs().model_dump()


# ---------------------------------------------------------------- invalid requests


def test_unsupported_inputs(engine):
    with pytest.raises(UnsupportedHubError):
        engine.get_hub_profile("Boston")
    with pytest.raises(UnsupportedHazardError):
        engine.rank_hubs(hazard="earthquake")
    with pytest.raises(UnsupportedRegionError):
        engine.rank_hubs(region="Northeast")  # valid region, no hubs
    with pytest.raises(UnsupportedRegionError):
        engine.rank_hubs(region="Narnia")
    with pytest.raises(UnsupportedPeriodError):
        engine.get_weather_stat("Denver", M.SNOW_DAYS_MEASURABLE, "2026")
    with pytest.raises(UnsupportedPeriodError):
        engine.get_weather_stat("Denver", M.SNOW_DAYS_MEASURABLE, "next year")
    from weather_risk.data.errors import InvalidRequestError

    with pytest.raises(InvalidRequestError):
        engine.get_weather_stat("Denver", "rain_days", "2025")
    with pytest.raises(InvalidRequestError):
        engine.compare_hubs(["Dallas", "dallas_tx"])
    with pytest.raises(InvalidRequestError):
        engine.explain_hub_score("Dallas", claimed_band="Extreme")


def test_county_version_mismatch_falls_back_to_reference_row(tmp_path, monkeypatch):
    eng = make_engine(tmp_path)
    original = eng.repo.get_county_hazards

    def stale(fips):
        return original(fips).model_copy(update={"nri_version": "March 2023"})

    monkeypatch.setattr(eng.repo, "get_county_hazards", stale)
    rec = eng.county(eng.hub("Dallas"))
    assert rec.nri_version == eng.percentiles().nri_version == "December 2025"


def test_scenario_report_renders_all_sections(engine):
    from weather_risk.analytics.report import render_scenarios

    md = render_scenarios(engine, offline=True)
    for heading in ("Score table — all 12 hubs", "Scenario 1", "Scenario 2", "Scenario 3",
                    "Scenario 4", "Premise check", "Insufficient coverage"):  # fmt: skip
        assert heading in md
    for h in engine.catalog.hubs:
        assert f"| {h.id} |" in md
