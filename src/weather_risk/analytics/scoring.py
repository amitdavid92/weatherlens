"""Pure, deterministic scoring: indicators -> hazard scores -> overall index.

Formulas (see docs/SCORING_METHODOLOGY.md):
  climate indicator   s = 100 · clip((x − low) / (high − low), 0, 1)
  NRI indicator       s = national mid-rank percentile (analytics.percentiles)
  hazard score        H = Σ_avail w_i·s_i / Σ_avail w_i         (available weight fraction ≥ f_min)
  overall index       O = Σ_h W_h·H_h                            (only if every hazard is available)
Not-applicable NRI indicators score 0 and stay in every denominator (no inflation by removal).
Unavailable indicators (insufficient coverage / insufficient data / unknown) are never scored 0.
"""

from __future__ import annotations

from dataclasses import dataclass

from weather_risk.analytics.config import (
    ClimateMetric,
    Hazard,
    HazardConfig,
    IndicatorConfig,
    ScoringConfig,
)
from weather_risk.analytics.models import CoverageInfo, HazardResult, IndicatorResult
from weather_risk.analytics.percentiles import NationalPercentiles
from weather_risk.analytics.stats import DayCountStatistic
from weather_risk.data.models import CountyHazardRecord, HazardStatus, SourceId


def anchor_score(x: float, low: float, high: float) -> float:
    if not high > low:
        raise ValueError("anchor high must exceed low")
    return 100.0 * min(max((x - low) / (high - low), 0.0), 1.0)


@dataclass(frozen=True)
class HubInputs:
    hub_id: str
    county: CountyHazardRecord
    climate_stats: dict[ClimateMetric, DayCountStatistic]
    climate_period_label: str
    climate_source: SourceId


def coverage_info(stat: DayCountStatistic) -> CoverageInfo:
    return CoverageInfo(
        expected_days=stat.expected_days,
        valid_days=stat.valid_days,
        missing_days=stat.missing_days,
        excluded_days=stat.excluded_days,
        excluded_reasons=stat.excluded_reasons,
        coverage=stat.coverage,
        min_coverage=stat.min_coverage,
        status=stat.status,
    )


def _indicator_raw(
    ind: IndicatorConfig, hazard: Hazard, inputs: HubInputs, pct: NationalPercentiles
) -> dict:
    """Return raw/score fields for one indicator (before weight normalization)."""
    if ind.kind == "climate_anchor":
        assert ind.metric is not None and ind.anchor is not None
        stat = inputs.climate_stats[ind.metric]
        score = None
        raw = stat.annual_average
        if stat.ok and raw is not None:
            score = anchor_score(raw, ind.anchor.low, ind.anchor.high)
        return dict(
            label=stat.definition,
            raw_value=raw,
            raw_unit=ind.unit or "days/yr",
            raw_status=stat.status,
            score=score,
            normalization=f"fixed anchors: {ind.anchor.low:g} -> 0, {ind.anchor.high:g} -> 100 "
            "(linear, clipped)",
            period=inputs.climate_period_label,
            source_ids=[inputs.climate_source],
            coverage=coverage_info(stat),
        )
    assert ind.nri_hazard is not None
    pr = pct.score(inputs.county, ind.nri_hazard)
    value = inputs.county.hazards[ind.nri_hazard]
    if pr.status in (HazardStatus.OBSERVED_ZERO, HazardStatus.NOT_APPLICABLE):
        norm = f"{pr.status.value}: no-exposure tier -> 0"
    elif pr.score is None:
        norm = f"{pr.status.value}: unavailable, not scored"
    else:
        norm = f"national mid-rank percentile among {pr.n_eligible} eligible counties"
    return dict(
        label=f"FEMA NRI {ind.nri_hazard.name.replace('_', ' ').lower()} annualized frequency",
        raw_value=value.annualized_frequency,
        raw_unit="events or event-days per year (NRI AFREQ)",
        raw_status=pr.status.value,
        score=pr.score,
        normalization=norm,
        period=f"NRI {inputs.county.nri_version}, hazard-specific period of record",
        source_ids=[SourceId.FEMA_NRI],
        coverage=None,
    )


def score_hazard(
    hazard: Hazard,
    hcfg: HazardConfig,
    inputs: HubInputs,
    pct: NationalPercentiles,
    cfg: ScoringConfig,
) -> HazardResult:
    raws = [(ind, _indicator_raw(ind, hazard, inputs, pct)) for ind in hcfg.indicators]
    total_w = sum(ind.weight for ind, _ in raws)
    avail_w = sum(ind.weight for ind, r in raws if r["score"] is not None)
    frac = avail_w / total_w
    computable = frac >= cfg.coverage.min_hazard_weight_fraction and avail_w > 0

    indicators: list[IndicatorResult] = []
    for ind, r in raws:
        eff = ind.weight / avail_w if (computable and r["score"] is not None) else 0.0
        contribution = eff * r["score"] if eff else 0.0
        fid = f"{inputs.hub_id}.{hazard.value}.{ind.id}"
        indicators.append(
            IndicatorResult(
                indicator_id=ind.id,
                hazard=hazard,
                kind=ind.kind,
                weight=ind.weight,
                effective_weight=eff,
                contribution=contribution,
                fact_ids=[f"{fid}.raw", f"{fid}.score"],
                **r,
            )
        )

    notes: list[str] = []
    for i in indicators:
        if i.raw_status == HazardStatus.NOT_APPLICABLE.value:
            notes.append(f"{i.indicator_id}: FEMA 'Not Applicable' (not considered at risk) -> "
                         "scored 0 and kept in the denominator")  # fmt: skip
        elif i.score is None:
            notes.append(f"{i.indicator_id}: unavailable ({i.raw_status}); not scored, never "
                         "treated as 0")  # fmt: skip

    if not computable:
        status, score = "unavailable", None
        notes.append(f"only {frac:.0%} of indicator weight available (< "
                     f"{cfg.coverage.min_hazard_weight_fraction:.0%}); hazard not scored")  # fmt: skip
    else:
        score = sum(i.contribution for i in indicators)
        score = min(max(score, 0.0), 100.0)
        status = "complete" if abs(frac - 1.0) < 1e-9 else "partial"
        if status == "partial":
            notes.append(f"partial: {frac:.0%} of indicator weight available; weights renormalized "
                         "over available indicators")  # fmt: skip
    W = cfg.hazard_weights[hazard]
    return HazardResult(
        hazard=hazard,
        label=hcfg.label,
        score=score,
        band=cfg.band_for(score),
        status=status,
        available_weight_fraction=frac,
        weight_in_overall=W,
        contribution_to_overall=W * score if score is not None else None,
        indicators=indicators,
        notes=notes,
    )


def score_overall(
    hazards: dict[Hazard, HazardResult], cfg: ScoringConfig
) -> tuple[float | None, str]:
    """Overall index; unavailable if any hazard is unavailable (no silent renormalization)."""
    if any(h.status == "unavailable" for h in hazards.values()):
        return None, "unavailable"
    total = sum(h.contribution_to_overall or 0.0 for h in hazards.values())
    status = "partial" if any(h.status == "partial" for h in hazards.values()) else "complete"
    return min(max(total, 0.0), 100.0), status


def score_hub(
    inputs: HubInputs, pct: NationalPercentiles, cfg: ScoringConfig
) -> tuple[dict[Hazard, HazardResult], float | None, str]:
    hazards = {h: score_hazard(h, cfg.hazards[h], inputs, pct, cfg) for h in Hazard}
    overall, status = score_overall(hazards, cfg)
    return hazards, overall, status
