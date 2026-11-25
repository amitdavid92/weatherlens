"""Typed result contracts for the analytics engine (future LLM tool outputs).

Every result carries stable `Fact`s (fact_id -> value + unit + source + period) so Phase 3 can
render critical numbers deterministically from fact ids instead of trusting LLM prose.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from weather_risk.analytics.config import ClimateMetric, Hazard
from weather_risk.analytics.periods import Period
from weather_risk.data.models import HazardCode, SourceId

STANDARD_CAVEAT = (
    "Weather Hazard Exposure Index: a heuristic 0–100 measure of weather-hazard exposure at the "
    "hub's county/station. It is not a probability of disruption, not a loss prediction, and has "
    "not been validated against operational outcomes."
)


class Fact(BaseModel):
    model_config = ConfigDict(frozen=True)

    fact_id: str
    label: str
    value: float | int | str | None
    unit: str | None = None
    kind: Literal["statistic", "count", "frequency", "percentile", "score", "rank", "label"]
    source_ids: list[SourceId] = Field(default_factory=list)
    period: str | None = None  # human-readable; FEMA facts use "NRI <version> period of record"
    status: str = "ok"


class SourceRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: SourceId
    dataset: str
    version: str | None
    location_id: str
    freshness: str
    retrieved_at: str
    attribution: str


class CoverageInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    expected_days: int
    valid_days: int
    missing_days: int
    excluded_days: int
    excluded_reasons: dict[str, int]
    coverage: float
    min_coverage: float
    status: Literal["ok", "insufficient_coverage"]


class IndicatorResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    indicator_id: str
    hazard: Hazard
    kind: Literal["climate_anchor", "nri_percentile"]
    label: str
    raw_value: float | None
    raw_unit: str
    raw_status: str  # ok / insufficient_coverage / observed / observed_zero / not_applicable / ...
    score: float | None  # 0–100, None = unavailable
    weight: float  # configured weight within the hazard
    effective_weight: float  # weight renormalized over available indicators (0 if unavailable)
    contribution: float  # points contributed to the hazard score (effective_weight · score)
    normalization: str
    period: str
    source_ids: list[SourceId]
    fact_ids: list[str]
    coverage: CoverageInfo | None = None


class HazardResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    hazard: Hazard
    label: str
    score: float | None
    band: str | None
    status: Literal["complete", "partial", "unavailable"]
    available_weight_fraction: float
    weight_in_overall: float
    contribution_to_overall: float | None
    indicators: list[IndicatorResult]
    notes: list[str] = Field(default_factory=list)


class RankingEligibility(BaseModel):
    """Whether a score may enter a ranking, and why not (explicit, per scope)."""

    model_config = ConfigDict(frozen=True)

    scope: str  # "overall" or a hazard value
    eligible: bool
    status: str
    reason: str | None = None


class IndicatorContribution(BaseModel):
    """One indicator's contribution, at both levels (to its hazard and to the overall index)."""

    model_config = ConfigDict(frozen=True)

    hazard: Hazard
    indicator_id: str
    label: str
    raw_value: float | None
    raw_unit: str
    score: float | None
    effective_weight_in_hazard: float
    contribution_to_hazard: float  # points of the hazard score
    contribution_to_overall: float  # points of the overall index = hazard weight × the above


class HubProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    hub_id: str
    display_name: str
    region: str
    illustrative: bool = True
    methodology_version: str
    nri_version: str
    climate_source: SourceId
    climate_period: str
    fema_period_note: str
    overall_score: float | None
    overall_band: str | None
    overall_status: Literal["complete", "partial", "unavailable"]
    hazards: dict[Hazard, HazardResult]
    ranking_eligibility: dict[str, RankingEligibility]
    facts: list[Fact]
    sources: list[SourceRef]
    assumptions: list[str]
    limitations: list[str]


class WeatherStatResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    hub_id: str
    metric: ClimateMetric
    definition: str
    period: Period
    source_id: SourceId
    data_kind: str
    location_id: str
    status: Literal["ok", "insufficient_coverage"]
    value_percent_of_valid_days: float | None
    event_days: int | None
    annual_average_days: float | None
    coverage: CoverageInfo
    facts: list[Fact]
    sources: list[SourceRef]
    methodology_version: str
    assumptions: list[str]
    limitations: list[str]


class RankingEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    rank: int | None
    hub_id: str
    display_name: str
    score: float | None
    band: str | None
    status: str
    top_contributors: list[str]
    fact_id: str
    eligible: bool = True
    exclusion_reason: str | None = None


class RankingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: Literal["overall", "hazard"]
    hazard: Hazard | None
    region: str | None
    hub_ids: list[str]
    ranked: list[RankingEntry]
    not_ranked: list[RankingEntry]
    tie_break: str
    methodology_version: str
    nri_version: str
    climate_period: str
    facts: list[Fact]
    assumptions: list[str]
    limitations: list[str]


class ComparisonRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    hazard: Hazard
    hub_scores: dict[str, float | None]
    hub_status: dict[str, str]
    leader: str | None  # hub with the higher score, None if tie/unavailable
    difference: float | None  # absolute score difference between the top two
    indicators: dict[str, list[IndicatorResult]]


class ComparisonResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    hub_ids: list[str]
    hazards: list[Hazard]
    rows: list[ComparisonRow]
    nri_raw: dict[str, dict[HazardCode, dict[str, float | str | None]]]
    methodology_version: str
    nri_version: str
    facts: list[Fact]
    assumptions: list[str]
    limitations: list[str]


class PremiseCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim: str
    supported: bool | None
    reasoning: str


class Explanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    hub_id: str
    overall_score: float | None
    overall_band: str | None
    overall_status: str
    rank_among_catalog: int | None
    catalog_size_ranked: int
    primary_driver: str | None  # hazard with the largest contribution to the overall index
    hazards_by_contribution: list[HazardResult]  # hazard-level contributions (sum = overall)
    top_indicators: list[IndicatorContribution]  # indicator-level; see contribution_to_overall
    indicator_contribution_note: str
    not_applicable: list[str]
    unavailable: list[str]
    premise_check: PremiseCheck | None
    methodology_version: str
    facts: list[Fact]
    assumptions: list[str]
    limitations: list[str]
