"""Load and validate `config/scoring.yaml` (weights, anchors, thresholds, coverage policy)."""

from __future__ import annotations

import math
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from weather_risk.data.models import HazardCode, SourceId

WEIGHT_TOLERANCE = 1e-3


class Hazard(StrEnum):
    WINTER = "winter"
    HURRICANE = "hurricane"
    FLOOD = "flood"
    SEVERE_CONVECTIVE = "severe_convective"
    EXTREME_HEAT = "extreme_heat"


class ClimateMetric(StrEnum):
    SNOW_DAYS_MEASURABLE = "snow_days_measurable"
    SNOW_DAYS_TRACE_INCLUSIVE = "snow_days_trace_inclusive"
    HEAVY_SNOW_DAYS = "heavy_snow_days"
    FREEZING_DAYS = "freezing_days"
    EXTREME_HEAT_DAYS = "extreme_heat_days"


class Anchor(BaseModel):
    model_config = ConfigDict(frozen=True)
    low: float
    high: float

    @model_validator(mode="after")
    def _order(self) -> Anchor:
        if not self.high > self.low:
            raise ValueError(f"anchor high ({self.high}) must exceed low ({self.low})")
        return self


class IndicatorConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    kind: Literal["climate_anchor", "nri_percentile"]
    weight: float = Field(gt=0, le=1)
    metric: ClimateMetric | None = None
    anchor: Anchor | None = None
    unit: str | None = None
    nri_hazard: HazardCode | None = None

    @model_validator(mode="after")
    def _kind_fields(self) -> IndicatorConfig:
        if self.kind == "climate_anchor":
            if self.metric is None or self.anchor is None:
                raise ValueError(f"{self.id}: climate_anchor needs metric and anchor")
            if self.nri_hazard is not None:
                raise ValueError(f"{self.id}: climate_anchor must not set nri_hazard")
        else:
            if self.nri_hazard is None:
                raise ValueError(f"{self.id}: nri_percentile needs nri_hazard")
            if self.metric is not None or self.anchor is not None:
                raise ValueError(f"{self.id}: nri_percentile must not set metric/anchor")
        return self


class HazardConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    label: str
    indicators: list[IndicatorConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _weights(self) -> HazardConfig:
        total = sum(i.weight for i in self.indicators)
        if not math.isclose(total, 1.0, abs_tol=WEIGHT_TOLERANCE):
            raise ValueError(f"indicator weights for '{self.label}' sum to {total}, expected 1.0")
        ids = [i.id for i in self.indicators]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate indicator ids in '{self.label}'")
        return self


class Band(BaseModel):
    model_config = ConfigDict(frozen=True)
    label: str
    min: float = Field(ge=0, le=100)


class ClimateConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: SourceId
    period: dict[str, int]
    min_coverage: float = Field(gt=0, le=1)
    exclude_quality_flagged: bool = True

    @field_validator("source")
    @classmethod
    def _climate_source(cls, v: SourceId) -> SourceId:
        if v is SourceId.FEMA_NRI:
            raise ValueError("climate source must be a climate dataset")
        return v

    @model_validator(mode="after")
    def _period(self) -> ClimateConfig:
        if set(self.period) != {"start_year", "end_year"}:
            raise ValueError("climate.period needs start_year and end_year")
        if self.period["start_year"] > self.period["end_year"]:
            raise ValueError("climate.period start_year > end_year")
        return self


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True)
    heavy_snow_mm: float = Field(gt=0)
    freezing_tmin_c: float
    extreme_heat_tmax_c: float


class CoveragePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    min_hazard_weight_fraction: float = Field(gt=0, le=1)
    rank_partial_results: bool = False


class NriNormalization(BaseModel):
    """How FEMA AFREQ values become 0–100 indicator scores (see SCORING_METHODOLOGY.md §3.2)."""

    model_config = ConfigDict(frozen=True)
    method: Literal["percentile", "conditional_percentile", "hybrid"] = "percentile"
    relative_weight: float = Field(default=0.5, ge=0, le=1)  # hybrid only
    absolute_anchor: Anchor = Anchor(low=0.01, high=1.0)  # events/yr, log10 scale (hybrid only)
    absolute_anchor_by_hazard: dict[HazardCode, Anchor] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _positive(self) -> NriNormalization:
        anchors = [self.absolute_anchor, *self.absolute_anchor_by_hazard.values()]
        if any(a.low <= 0 for a in anchors):
            raise ValueError("log-scale absolute anchors must be > 0")
        return self

    def anchor_for(self, hazard: HazardCode) -> Anchor:
        return self.absolute_anchor_by_hazard.get(hazard, self.absolute_anchor)


class ScoringConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    methodology_version: str
    climate: ClimateConfig
    thresholds: Thresholds
    coverage: CoveragePolicy
    bands: list[Band] = Field(min_length=1)
    nri_normalization: NriNormalization = NriNormalization()
    hazard_weights: dict[Hazard, float]
    hazards: dict[Hazard, HazardConfig]

    @model_validator(mode="after")
    def _consistency(self) -> ScoringConfig:
        if set(self.hazards) != set(Hazard) or set(self.hazard_weights) != set(Hazard):
            raise ValueError("hazards and hazard_weights must define exactly the five hazards")
        if any(w <= 0 for w in self.hazard_weights.values()):
            raise ValueError("hazard weights must be positive")
        total = sum(self.hazard_weights.values())
        if not math.isclose(total, 1.0, abs_tol=WEIGHT_TOLERANCE):
            raise ValueError(f"hazard weights sum to {total}, expected 1.0")
        mins = [b.min for b in self.bands]
        if mins != sorted(mins) or mins[0] != 0 or len(set(mins)) != len(mins):
            raise ValueError("bands must start at 0 and be strictly increasing")
        all_ids = [i.id for h in self.hazards.values() for i in h.indicators]
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("indicator ids must be unique across hazards")
        return self

    def band_for(self, score: float | None) -> str | None:
        if score is None:
            return None
        label = self.bands[0].label
        for b in self.bands:
            if score >= b.min:
                label = b.label
        return label


def load_scoring_config(path: Path) -> ScoringConfig:
    from weather_risk.analytics.formatting import configure_bands

    with path.open() as f:
        cfg = ScoringConfig.model_validate(yaml.safe_load(f))
    configure_bands([b.min for b in cfg.bands])  # display rounding uses the same bands
    return cfg
