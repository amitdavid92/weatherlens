"""National percentile normalization of FEMA NRI annualized frequencies (AFREQ).

Per hazard, the eligible reference population is the 50 states + DC (territories excluded) with
status in {observed, observed_zero, not_applicable}. `not_applicable` ("not considered at risk",
FEMA) and `observed_zero` form a no-exposure tier ranked below every positive frequency.
`insufficient_data` and `unknown` counties are excluded from that hazard's denominator.

Score of a county for hazard h (N = eligible count, Z = no-exposure count):
  no-exposure tier (observed_zero or not_applicable) -> 0       (never percentile-ranked)
  positive AFREQ x  -> 100 · (Z + L + 0.5·E) / N
                       L = eligible positives strictly below x, E = eligible positives equal to x
                       (mid-rank: ties share the average rank; deterministic, exact float compare)
  insufficient_data / unknown                         -> None (unavailable, never 0)
The result is bounded: 0 ≤ score < 100.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right

from pydantic import BaseModel, ConfigDict

from weather_risk.data.errors import DatasetVersionMismatchError
from weather_risk.data.models import (
    CountyHazardRecord,
    HazardCode,
    HazardReferencePopulation,
    HazardStatus,
)

NO_EXPOSURE = (HazardStatus.OBSERVED_ZERO, HazardStatus.NOT_APPLICABLE)


class HazardDistribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    hazard: HazardCode
    nri_version: str
    positives: list[float]  # sorted ascending
    n_observed_zero: int
    n_not_applicable: int
    n_excluded_unavailable: int  # insufficient_data + unknown within states+DC
    n_excluded_territories: int

    @property
    def n_no_exposure(self) -> int:
        return self.n_observed_zero + self.n_not_applicable

    @property
    def n_eligible(self) -> int:
        return len(self.positives) + self.n_no_exposure


class PercentileResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    hazard: HazardCode
    status: HazardStatus
    afreq: float | None
    score: float | None
    n_eligible: int
    n_below: float | None  # Z + L + 0.5·E (None if not ranked)
    method: str


def build_distribution(ref: HazardReferencePopulation, hazard: HazardCode) -> HazardDistribution:
    positives: list[float] = []
    zero = na = unavailable = 0
    for rec in ref.reference_records:
        v = rec.hazards[hazard]
        if v.status is HazardStatus.OBSERVED:
            assert v.annualized_frequency is not None and v.annualized_frequency > 0
            positives.append(v.annualized_frequency)
        elif v.status is HazardStatus.OBSERVED_ZERO:
            zero += 1
        elif v.status is HazardStatus.NOT_APPLICABLE:
            na += 1
        else:
            unavailable += 1
    return HazardDistribution(
        hazard=hazard,
        nri_version=ref.nri_version,
        positives=sorted(positives),
        n_observed_zero=zero,
        n_not_applicable=na,
        n_excluded_unavailable=unavailable,
        n_excluded_territories=len(ref.excluded_records),
    )


class NationalPercentiles:
    def __init__(self, ref: HazardReferencePopulation) -> None:
        self.nri_version = ref.nri_version
        self.total_records = ref.total_count
        self.distributions = {h: build_distribution(ref, h) for h in HazardCode}

    def score(self, record: CountyHazardRecord, hazard: HazardCode) -> PercentileResult:
        if record.nri_version != self.nri_version:
            raise DatasetVersionMismatchError(
                f"county {record.county_fips} is NRI '{record.nri_version}', reference is "
                f"'{self.nri_version}'"
            )
        dist = self.distributions[hazard]
        v = record.hazards[hazard]
        method = "national mid-rank percentile among eligible counties (50 states + DC)"
        if v.status in NO_EXPOSURE:
            return PercentileResult(hazard=hazard, status=v.status, afreq=v.annualized_frequency,
                                    score=0.0, n_eligible=dist.n_eligible, n_below=None,
                                    method="no-exposure tier -> 0")  # fmt: skip
        if v.status is not HazardStatus.OBSERVED:
            return PercentileResult(hazard=hazard, status=v.status, afreq=v.annualized_frequency,
                                    score=None, n_eligible=dist.n_eligible, n_below=None,
                                    method="unavailable (not ranked)")  # fmt: skip
        x = v.annualized_frequency
        assert x is not None
        lo = bisect_left(dist.positives, x)
        hi = bisect_right(dist.positives, x)
        n_below = dist.n_no_exposure + lo + 0.5 * (hi - lo)
        score = 100.0 * n_below / dist.n_eligible
        return PercentileResult(hazard=hazard, status=v.status, afreq=x,
                                score=min(max(score, 0.0), 100.0), n_eligible=dist.n_eligible,
                                n_below=n_below, method=method)  # fmt: skip
