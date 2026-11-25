"""Deterministic historical day-count statistics on ONE ClimateDataset (one source, one location).

Definitions (thresholds from config/scoring.yaml):
  valid observation  = element reported (not MISSING) and, if configured, no NOAA quality flag
  excluded           = reported but quality-flagged (reason recorded as "quality_flag:<Q>")
  coverage           = valid / expected days in the period
  event_days         = valid observations satisfying the metric predicate
  percent_of_valid   = 100 · event_days / valid
  annual_average     = (event_days / valid) · (expected_days / n_years)   [observed-rate scaling]

Missing days are never treated as zero. If coverage < min_coverage the statistic is reported with
status "insufficient_coverage" and NO value (counts are still reported for transparency).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from weather_risk.analytics.config import ClimateMetric, Thresholds
from weather_risk.analytics.periods import Period
from weather_risk.data.models import (
    ClimateDataset,
    ClimateElement,
    DailyValue,
    DataKind,
    ObservationStatus,
    SourceId,
)

METRIC_ELEMENT: dict[ClimateMetric, ClimateElement] = {
    ClimateMetric.SNOW_DAYS_MEASURABLE: ClimateElement.SNOWFALL,
    ClimateMetric.SNOW_DAYS_TRACE_INCLUSIVE: ClimateElement.SNOWFALL,
    ClimateMetric.HEAVY_SNOW_DAYS: ClimateElement.SNOWFALL,
    ClimateMetric.FREEZING_DAYS: ClimateElement.TMIN,
    ClimateMetric.EXTREME_HEAT_DAYS: ClimateElement.TMAX,
}


def metric_definition(metric: ClimateMetric, t: Thresholds) -> str:
    return {
        ClimateMetric.SNOW_DAYS_MEASURABLE: "days with measurable new snowfall (reported > 0; "
        "trace excluded)",
        ClimateMetric.SNOW_DAYS_TRACE_INCLUSIVE: "days with measurable OR trace snowfall",
        ClimateMetric.HEAVY_SNOW_DAYS: f"days with new snowfall ≥ {t.heavy_snow_mm:g} mm "
        f"({t.heavy_snow_mm / 25.4:.1f} in)",
        ClimateMetric.FREEZING_DAYS: f"days with minimum temperature ≤ {t.freezing_tmin_c:g} °C",
        ClimateMetric.EXTREME_HEAT_DAYS: f"days with maximum temperature ≥ "
        f"{t.extreme_heat_tmax_c:g} °C ({t.extreme_heat_tmax_c * 9 / 5 + 32:g} °F)",
    }[metric]


def _predicate(metric: ClimateMetric, t: Thresholds) -> Callable[[DailyValue], bool]:
    M, T = ObservationStatus.MEASURED, ObservationStatus.TRACE
    match metric:
        case ClimateMetric.SNOW_DAYS_MEASURABLE:
            return lambda v: v.status is M
        case ClimateMetric.SNOW_DAYS_TRACE_INCLUSIVE:
            return lambda v: v.status in (M, T)
        case ClimateMetric.HEAVY_SNOW_DAYS:
            return lambda v: v.status is M and v.value is not None and v.value >= t.heavy_snow_mm
        case ClimateMetric.FREEZING_DAYS:
            return lambda v: v.value is not None and v.value <= t.freezing_tmin_c
        case ClimateMetric.EXTREME_HEAT_DAYS:
            return lambda v: v.value is not None and v.value >= t.extreme_heat_tmax_c
    raise ValueError(metric)  # pragma: no cover


class DayCountStatistic(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: ClimateMetric
    definition: str
    element: ClimateElement
    source_id: SourceId
    data_kind: DataKind
    location_id: str
    period: Period
    expected_days: int
    reported_days: int
    missing_days: int
    excluded_days: int
    excluded_reasons: dict[str, int]
    valid_days: int
    coverage: float
    min_coverage: float
    status: Literal["ok", "insufficient_coverage"]
    event_days: int | None
    percent_of_valid_days: float | None
    annual_average: float | None  # days per year

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def compute_day_count(
    dataset: ClimateDataset,
    metric: ClimateMetric,
    period: Period,
    thresholds: Thresholds,
    *,
    min_coverage: float,
    exclude_quality_flagged: bool = True,
) -> DayCountStatistic:
    if period.start < dataset.start or period.end > dataset.end:
        raise ValueError(f"dataset {dataset.start}..{dataset.end} does not cover {period.key}")
    element = METRIC_ELEMENT[metric]
    if element not in dataset.elements:
        raise ValueError(f"dataset lacks element {element}")
    data = dataset.slice(period.start, period.end)
    pred = _predicate(metric, thresholds)

    expected = len(data.records)
    missing = 0
    excluded: Counter[str] = Counter()
    valid = 0
    events = 0
    for rec in data.records:
        v = rec.values[element]
        if v.status is ObservationStatus.MISSING:
            missing += 1
            continue
        if exclude_quality_flagged and v.quality_flagged:
            excluded[f"quality_flag:{v.quality_flag}"] += 1
            continue
        valid += 1
        if pred(v):
            events += 1

    coverage = valid / expected if expected else 0.0
    ok = expected > 0 and coverage >= min_coverage and valid > 0
    pct = 100.0 * events / valid if ok else None
    annual = (events / valid) * (expected / period.n_years) if ok else None
    return DayCountStatistic(
        metric=metric,
        definition=metric_definition(metric, thresholds),
        element=element,
        source_id=dataset.provenance.source_id,
        data_kind=dataset.provenance.data_kind,
        location_id=dataset.provenance.location_id,
        period=period,
        expected_days=expected,
        reported_days=expected - missing,
        missing_days=missing,
        excluded_days=sum(excluded.values()),
        excluded_reasons=dict(sorted(excluded.items())),
        valid_days=valid,
        coverage=coverage,
        min_coverage=min_coverage,
        status="ok" if ok else "insufficient_coverage",
        event_days=events if ok else None,
        percent_of_valid_days=pct,
        annual_average=annual,
    )
