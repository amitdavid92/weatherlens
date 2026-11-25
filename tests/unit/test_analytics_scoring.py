from __future__ import annotations

import copy
from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from tests.unit.analytics_helpers import canonical_population, county
from weather_risk.analytics.config import ClimateMetric as M
from weather_risk.analytics.config import Hazard, ScoringConfig, load_scoring_config
from weather_risk.analytics.percentiles import NationalPercentiles
from weather_risk.analytics.periods import Period
from weather_risk.analytics.scoring import HubInputs, anchor_score, score_hub
from weather_risk.analytics.stats import DayCountStatistic
from weather_risk.config import PROJECT_ROOT
from weather_risk.data.errors import DatasetVersionMismatchError
from weather_risk.data.models import ClimateElement as E
from weather_risk.data.models import DataKind, HazardCode, SourceId

CFG_PATH = PROJECT_ROOT / "config" / "scoring.yaml"
P = 100 / 6  # one rank step in the canonical population (N = 6)


@pytest.fixture(scope="module")
def cfg() -> ScoringConfig:
    return load_scoring_config(CFG_PATH)


@pytest.fixture(scope="module")
def pct() -> NationalPercentiles:
    return NationalPercentiles(canonical_population())


# ------------------------------------------------------------------ percentiles


@pytest.mark.parametrize(
    "fips,expected",
    [
        ("00001", 0.0),  # observed zero -> 0, not ranked
        ("00002", 0.0),  # not applicable -> 0
        ("00003", 2.5 * P),  # 41.667
        ("00004", 4.0 * P),  # tie with 00005 -> shared mid-rank 66.667
        ("00005", 4.0 * P),
        ("00006", 5.5 * P),  # 91.667, max < 100
        ("00007", None),  # insufficient data -> unavailable, never 0
    ],
)
def test_mid_rank_percentiles_hand_computed(pct, fips, expected):
    from tests.unit.analytics_helpers import CANONICAL_SPECS

    rec = county(fips, CANONICAL_SPECS[fips])
    r = pct.score(rec, HazardCode.HURRICANE)
    if expected is None:
        assert r.score is None
    else:
        assert r.score == pytest.approx(expected)
        assert 0 <= r.score < 100


def test_reference_excludes_territory_and_unavailable(pct):
    d = pct.distributions[HazardCode.HURRICANE]
    assert d.n_eligible == 6  # PR (5.0) and the insufficient-data county are excluded
    assert d.n_excluded_unavailable == 1 and d.n_excluded_territories == 1
    assert d.n_observed_zero == 1 and d.n_not_applicable == 1
    assert d.positives == [1.0, 2.0, 2.0, 3.0]


def test_many_zeros_do_not_inflate_zero_counties():
    recs = [county(f"{i:05d}", 0) for i in range(1, 100)] + [county("00100", 1.0)]
    from tests.unit.analytics_helpers import population

    p = NationalPercentiles(population(recs))
    assert p.score(recs[0], HazardCode.HAIL).score == 0.0
    assert p.score(recs[-1], HazardCode.HAIL).score == pytest.approx(100 * 99.5 / 100)


def test_unknown_status_is_unavailable(pct):
    rec = county("00099", {HazardCode.TORNADO: "UNK"})
    assert pct.score(rec, HazardCode.TORNADO).score is None


def test_version_mismatch_raises(pct):
    rec = county("00003", 1.0, version="March 2023")
    with pytest.raises(DatasetVersionMismatchError):
        pct.score(rec, HazardCode.HURRICANE)


# ------------------------------------------------------------------ anchors


@pytest.mark.parametrize("x,expected", [(-5, 0), (0, 0), (30, 50), (60, 100), (90, 100), (6, 10)])
def test_anchor_linear_and_clipped(x, expected):
    assert anchor_score(x, 0, 60) == pytest.approx(expected)


def test_anchor_requires_high_above_low():
    with pytest.raises(ValueError):
        anchor_score(1, 5, 5)


# ------------------------------------------------------------------ hub scoring

PERIOD = Period(start=date(2016, 1, 1), end=date(2025, 12, 31), label="2016–2025",
                kind="climatology")  # fmt: skip


def mkstat(metric: M, annual: float | None) -> DayCountStatistic:
    ok = annual is not None
    return DayCountStatistic(
        metric=metric, definition=metric.value, element=E.SNOWFALL,
        source_id=SourceId.NOAA_GHCN_DAILY, data_kind=DataKind.OBSERVED, location_id="S",
        period=PERIOD, expected_days=3653, reported_days=3653 if ok else 700,
        missing_days=0 if ok else 2953, excluded_days=0, excluded_reasons={},
        valid_days=3653 if ok else 700, coverage=1.0 if ok else 700 / 3653, min_coverage=0.9,
        status="ok" if ok else "insufficient_coverage", event_days=0 if ok else None,
        percent_of_valid_days=0 if ok else None, annual_average=annual,
    )  # fmt: skip


def inputs(rec, snow=30.0, heavy=3.0, freezing=90.0, heat=50.0) -> HubInputs:
    stats = {
        M.SNOW_DAYS_MEASURABLE: mkstat(M.SNOW_DAYS_MEASURABLE, snow),  # anchor 0..60 -> 50
        M.HEAVY_SNOW_DAYS: mkstat(M.HEAVY_SNOW_DAYS, heavy),  # 0..6 -> 50
        M.FREEZING_DAYS: mkstat(M.FREEZING_DAYS, freezing),  # 0..180 -> 50
        M.EXTREME_HEAT_DAYS: mkstat(M.EXTREME_HEAT_DAYS, heat),  # 0..100 -> 50
    }
    return HubInputs(hub_id="hub", county=rec, climate_stats=stats,
                     climate_period_label=PERIOD.label, climate_source=SourceId.NOAA_GHCN_DAILY)  # fmt: skip


F = 5.5 * P  # 91.667: county value 3.0 for every hazard


def test_full_hub_score_hand_computed(cfg, pct):
    rec = county("00006", 3.0)
    hazards, overall, status = score_hub(inputs(rec), pct, cfg)
    winter = 0.2 * 50 + 0.1 * 50 + 0.2 * 50 + 0.2 * F + 0.2 * F + 0.1 * F  # 70.833
    heat = 0.5 * 50 + 0.5 * F
    assert hazards[Hazard.WINTER].score == pytest.approx(winter)
    assert hazards[Hazard.HURRICANE].score == pytest.approx(F)
    assert hazards[Hazard.FLOOD].score == pytest.approx(F)
    assert hazards[Hazard.SEVERE_CONVECTIVE].score == pytest.approx(F)
    assert hazards[Hazard.EXTREME_HEAT].score == pytest.approx(heat)
    assert overall == pytest.approx(0.2 * (winter + 3 * F + heat))
    assert status == "complete"


def test_contributions_sum_to_scores(cfg, pct):
    hazards, overall, _ = score_hub(inputs(county("00004", 2.0)), pct, cfg)
    for h in hazards.values():
        assert sum(i.contribution for i in h.indicators) == pytest.approx(h.score)
        assert sum(i.effective_weight for i in h.indicators) == pytest.approx(1.0)
    assert sum(h.contribution_to_overall for h in hazards.values()) == pytest.approx(overall)


def test_not_applicable_scored_zero_and_kept_in_denominator(cfg, pct):
    rec = county("00006", {HazardCode.COASTAL_FLOODING: "NA", HazardCode.HURRICANE: "NA"} | {
        h: 3.0 for h in HazardCode if h not in (HazardCode.COASTAL_FLOODING, HazardCode.HURRICANE)})  # fmt: skip
    hazards, overall, status = score_hub(inputs(rec), pct, cfg)
    flood = hazards[Hazard.FLOOD]
    assert flood.score == pytest.approx(0.5 * F)  # NOT F (which removal would give)
    assert flood.status == "complete"
    assert hazards[Hazard.HURRICANE].score == 0.0
    assert any("Not Applicable" in n for n in flood.notes)
    assert status == "complete" and overall is not None


def test_unavailable_indicator_renormalizes_as_partial_never_zero(cfg, pct):
    rec = county("00006", 3.0)
    hz, overall, status = score_hub(inputs(rec, snow=None, heavy=None), pct, cfg)
    w = hz[Hazard.WINTER]
    expected = (0.2 * 50 + 0.2 * F + 0.2 * F + 0.1 * F) / 0.7
    assert w.status == "partial" and w.available_weight_fraction == pytest.approx(0.7)
    assert w.score == pytest.approx(expected)
    assert status == "partial"


def test_hazard_below_min_weight_is_unavailable_and_overall_unavailable(cfg, pct):
    rec = county("00006", {HazardCode.HEAT_WAVE: "ID"} | {
        h: 3.0 for h in HazardCode if h is not HazardCode.HEAT_WAVE})  # fmt: skip
    hz, overall, status = score_hub(inputs(rec, heat=None), pct, cfg)
    assert hz[Hazard.EXTREME_HEAT].status == "unavailable"
    assert hz[Hazard.EXTREME_HEAT].score is None
    assert overall is None and status == "unavailable"


def test_scores_bounded(cfg, pct):
    rec = county("00006", 3.0)
    hz, overall, _ = score_hub(inputs(rec, snow=1e6, heavy=1e6, freezing=1e6, heat=1e6), pct, cfg)
    assert all(0 <= h.score <= 100 for h in hz.values()) and 0 <= overall <= 100
    hz, overall, _ = score_hub(inputs(county("00001", 0), 0, 0, 0, 0), pct, cfg)
    assert overall == 0.0


def test_bands(cfg):
    assert [cfg.band_for(x) for x in (0, 39.99, 40, 69.99, 70, 100)] == [
        "Low", "Low", "Moderate", "Moderate", "High", "High"]  # fmt: skip
    assert cfg.band_for(None) is None


# ------------------------------------------------------------------ config validation


@pytest.fixture
def raw() -> dict:
    return yaml.safe_load(CFG_PATH.read_text())


def test_config_loads_with_version(cfg):
    assert cfg.methodology_version == "1.1.0"
    assert cfg.nri_normalization.method == "hybrid"
    assert cfg.nri_normalization.relative_weight == 0.5
    assert set(cfg.hazard_weights.values()) == {0.2}
    assert cfg.climate.min_coverage == 0.9


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda r: r["hazard_weights"].update(winter=0.5), "sum to"),
        (lambda r: r["hazard_weights"].update(winter=-0.2, hurricane=0.6), "positive"),
        (lambda r: r["hazard_weights"].pop("flood"), "five hazards"),
        (lambda r: r["hazards"]["flood"]["indicators"][0].update(weight=0.9), "sum to"),
        (lambda r: r["hazards"]["winter"]["indicators"][0]["anchor"].update(low=60), "must exceed"),
        (
            lambda r: r["hazards"]["hurricane"]["indicators"][0].pop("nri_hazard"),
            "needs nri_hazard",
        ),
        (
            lambda r: r["hazards"]["hurricane"]["indicators"][0].update(nri_hazard="ERQK"),
            "nri_hazard",
        ),
        (lambda r: r["bands"].reverse(), "bands"),
        (lambda r: r["climate"].update(min_coverage=1.5), "min_coverage"),
        (lambda r: r["climate"].update(source="fema_nri"), "climate source"),
    ],
)
def test_invalid_configs_rejected(raw, mutate, match):
    bad = copy.deepcopy(raw)
    mutate(bad)
    with pytest.raises(ValidationError, match=match):
        ScoringConfig.model_validate(bad)


# ------------------------------------------------------------------ v1.1.0 normalization methods
from weather_risk.analytics.config import NriNormalization  # noqa: E402
from weather_risk.analytics.percentiles import absolute_log_score  # noqa: E402


@pytest.mark.parametrize(
    "x,expected",
    [(0.001, 0.0), (0.01, 0.0), (0.1, 50.0), (1.0, 100.0), (10.0, 100.0), (0.0, 0.0),
     (10 ** -1.5, 25.0)],
)  # fmt: skip
def test_absolute_log_score_hand_computed(x, expected):
    assert absolute_log_score(x, 0.01, 1.0) == pytest.approx(expected)


def test_conditional_percentile_hand_computed():
    from tests.unit.analytics_helpers import CANONICAL_SPECS

    pct = NationalPercentiles(canonical_population(),
                              NriNormalization(method="conditional_percentile"))  # fmt: skip
    # positives [1, 2, 2, 3]: 1 -> 12.5, 2 -> 50 (tie), 3 -> 87.5; zero/NA -> 0
    exp = {"00001": 0.0, "00002": 0.0, "00003": 12.5, "00004": 50.0, "00005": 50.0, "00006": 87.5}
    for fips, e in exp.items():
        assert pct.score(
            county(fips, CANONICAL_SPECS[fips]), HazardCode.HAIL
        ).score == pytest.approx(e)


def test_hybrid_is_blend_and_preserves_order():
    from tests.unit.analytics_helpers import CANONICAL_SPECS

    pct = NationalPercentiles(canonical_population(),
                              NriNormalization(method="hybrid", relative_weight=0.5))  # fmt: skip
    # value 1.0/yr: relative 41.667, absolute 100 -> 70.833 ; 0/NA -> 0 ; ID -> None
    r = pct.score(county("00003", 1.0), HazardCode.HURRICANE)
    assert r.relative_score == pytest.approx(2.5 * P) and r.absolute_score == pytest.approx(100)
    assert r.score == pytest.approx(0.5 * 2.5 * P + 50)
    assert pct.score(county("00001", 0), HazardCode.HURRICANE).score == 0.0
    assert pct.score(county("00002", "NA"), HazardCode.HURRICANE).score == 0.0
    assert pct.score(county("00007", "ID"), HazardCode.HURRICANE).score is None
    scores = [pct.score(county(f, CANONICAL_SPECS[f]), HazardCode.HURRICANE).score
              for f in ("00003", "00004", "00006")]  # fmt: skip
    assert scores == sorted(scores)  # monotone in frequency -> rankings within a hazard unchanged


def test_rare_positive_frequency_no_longer_mid_scale():
    """Regression for D-021: a 1-in-87-year frequency ranked above a large no-exposure tier."""
    from tests.unit.analytics_helpers import population

    recs = [county(f"{i:05d}", "NA") for i in range(1, 51)] + [county("00051", 1 / 87)]
    recs += [county(f"{i:05d}", 0.5) for i in range(52, 101)]
    rare = recs[50]
    pctl = NationalPercentiles(population(recs)).score(rare, HazardCode.HURRICANE).score
    hyb = NationalPercentiles(population(recs), NriNormalization(method="hybrid")).score(
        rare, HazardCode.HURRICANE).score  # fmt: skip
    assert pctl == pytest.approx(50.5)  # (50 + 0.5) / 100
    assert hyb == pytest.approx(0.5 * 50.5 + 0.5 * absolute_log_score(1 / 87, 0.01, 1.0))
    assert hyb < pctl


def test_invalid_log_anchor_rejected():
    with pytest.raises(ValidationError):
        NriNormalization(method="hybrid", absolute_anchor={"low": 0, "high": 1})
