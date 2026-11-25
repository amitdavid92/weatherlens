"""AnalyticsEngine: the deterministic, LLM-free analytical interface.

    get_weather_stat(hub, metric, period)      historical day-count statistic for one hub
    get_hub_profile(hub)                       full exposure profile (5 hazards + overall)
    rank_hubs(hazard=None, region=None, hubs)  ranking (overall or one hazard)
    compare_hubs(hubs, hazards=None)           side-by-side hazard comparison
    explain_hub_score(hub, claimed_band=None)  drivers of a hub's score + premise check

All numbers come from the data layer and pure scoring functions; nothing here calls an LLM.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from weather_risk.analytics.config import ClimateMetric, Hazard, ScoringConfig
from weather_risk.analytics.models import (
    STANDARD_CAVEAT,
    ComparisonResult,
    ComparisonRow,
    Explanation,
    Fact,
    HazardResult,
    HubProfile,
    IndicatorResult,
    PremiseCheck,
    RankingEntry,
    RankingResult,
    SourceRef,
    WeatherStatResult,
)
from weather_risk.analytics.percentiles import NationalPercentiles
from weather_risk.analytics.periods import Period, UnsupportedPeriodError, resolve_period
from weather_risk.analytics.scoring import HubInputs, coverage_info, score_hub
from weather_risk.analytics.stats import DayCountStatistic, compute_day_count
from weather_risk.catalog import Hub, HubCatalog, Region
from weather_risk.data.errors import (
    DatasetVersionMismatchError,
    DataUnavailableError,
    InvalidRequestError,
)
from weather_risk.data.models import (
    ClimateDataset,
    CountyHazardRecord,
    DataKind,
    HazardCode,
    Provenance,
    SourceId,
)
from weather_risk.data.repository import DataRepository


class UnsupportedHazardError(InvalidRequestError):
    pass


class UnsupportedRegionError(InvalidRequestError):
    pass


FEMA_PERIOD_NOTE = (
    "FEMA NRI annualized frequencies summarize each hazard's own multi-decade period of record "
    "(differs by hazard); they are NOT specific to any user-selected calendar year."
)

HAZARD_ALIASES: dict[str, Hazard] = {
    "winter": Hazard.WINTER, "winter weather": Hazard.WINTER, "snow": Hazard.WINTER,
    "cold": Hazard.WINTER, "ice": Hazard.WINTER,
    "hurricane": Hazard.HURRICANE, "hurricanes": Hazard.HURRICANE,
    "tropical cyclone": Hazard.HURRICANE,
    "flood": Hazard.FLOOD, "flooding": Hazard.FLOOD, "floods": Hazard.FLOOD,
    "severe convective": Hazard.SEVERE_CONVECTIVE, "severe convective storms":
        Hazard.SEVERE_CONVECTIVE, "severe storms": Hazard.SEVERE_CONVECTIVE,
    "thunderstorms": Hazard.SEVERE_CONVECTIVE, "tornado": Hazard.SEVERE_CONVECTIVE,
    "hail": Hazard.SEVERE_CONVECTIVE,
    "extreme heat": Hazard.EXTREME_HEAT, "heat": Hazard.EXTREME_HEAT,
    "heat wave": Hazard.EXTREME_HEAT,
}  # fmt: skip


def resolve_hazard(value: Hazard | str) -> Hazard:
    if isinstance(value, Hazard):
        return value
    key = value.strip().lower().replace("_", " ").replace("-", " ")
    if key in HAZARD_ALIASES:
        return HAZARD_ALIASES[key]
    try:
        return Hazard(value)
    except ValueError:
        raise UnsupportedHazardError(
            f"unsupported hazard {value!r}; supported: {[h.value for h in Hazard]}"
        ) from None


def _round(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


def _source_ref(p: Provenance) -> SourceRef:
    return SourceRef(
        source_id=p.source_id,
        dataset=p.dataset_name,
        version=p.dataset_version,
        location_id=p.location_id,
        freshness=p.freshness.value,
        retrieved_at=p.retrieved_at.isoformat(),
        attribution=p.attribution,
    )


class AnalyticsEngine:
    def __init__(
        self,
        repo: DataRepository,
        catalog: HubCatalog,
        config: ScoringConfig,
        *,
        today: date | None = None,
    ) -> None:
        self.repo = repo
        self.catalog = catalog
        self.cfg = config
        self._today = today
        self._pct: NationalPercentiles | None = None
        self._counties: dict[str, CountyHazardRecord] = {}
        self._climate: dict[tuple[str, str, str], ClimateDataset] = {}
        self._profiles: dict[str, HubProfile] = {}

    # ------------------------------------------------------------------ basics
    @property
    def today(self) -> date:
        return self._today or datetime.now(UTC).date()

    @property
    def climatology(self) -> Period:
        p = self.cfg.climate.period
        return resolve_period("climatology", today=self.today,
                              climatology=(p["start_year"], p["end_year"]))  # fmt: skip

    def resolve_period(self, spec: str | Period) -> Period:
        if isinstance(spec, Period):
            return spec
        p = self.cfg.climate.period
        return resolve_period(spec, today=self.today,
                              climatology=(p["start_year"], p["end_year"]))  # fmt: skip

    def hub(self, hub: str | Hub) -> Hub:
        return hub if isinstance(hub, Hub) else self.catalog.resolve(hub)

    def percentiles(self) -> NationalPercentiles:
        if self._pct is None:
            self._pct = NationalPercentiles(self.repo.get_hazard_reference())
        return self._pct

    def county(self, hub: Hub) -> CountyHazardRecord:
        """County record guaranteed to share the reference population's NRI version."""
        fips = hub.hazard_county.fips
        if fips not in self._counties:
            pct = self.percentiles()
            try:
                rec = self.repo.get_county_hazards(fips)
            except DataUnavailableError:
                rec = None
            if rec is None or rec.nri_version != pct.nri_version:
                ref = self.repo.get_hazard_reference()
                rec = ref.get(fips)
                if rec is None:
                    raise DataUnavailableError(f"NRI county {fips}", ["not in reference"])
            if rec.nri_version != pct.nri_version:
                raise DatasetVersionMismatchError(
                    f"county {fips} is NRI '{rec.nri_version}', reference '{pct.nri_version}'"
                )
            self._counties[fips] = rec
        return self._counties[fips]

    def climate_dataset(self, hub: Hub, period: Period, source: SourceId) -> ClimateDataset:
        key = (hub.id, period.key, source.value)
        if key not in self._climate:
            if source is SourceId.NOAA_GHCN_DAILY:
                ds = self.repo.get_station_daily(hub.noaa_station.id, period.start, period.end)
            elif source is SourceId.OPEN_METEO_ARCHIVE:
                ds = self.repo.get_open_meteo_daily(
                    hub.latitude, hub.longitude, hub.timezone, period.start, period.end
                )
            else:
                raise InvalidRequestError(f"{source} is not a climate source")
            self._climate[key] = ds
        return self._climate[key]

    def _stat(
        self, hub: Hub, metric: ClimateMetric, period: Period, source: SourceId
    ) -> tuple[DayCountStatistic, ClimateDataset]:
        ds = self.climate_dataset(hub, period, source)
        stat = compute_day_count(
            ds, metric, period, self.cfg.thresholds,
            min_coverage=self.cfg.climate.min_coverage,
            exclude_quality_flagged=self.cfg.climate.exclude_quality_flagged,
        )  # fmt: skip
        return stat, ds

    def _base_limitations(self) -> list[str]:
        return [
            STANDARD_CAVEAT,
            "Hubs are illustrative examples, not actual company facilities.",
            "Exposure at the county (FEMA) or airport-station (NOAA) level is not site-specific.",
            FEMA_PERIOD_NOTE,
        ]

    # ------------------------------------------------------------------ 1. weather stat
    def get_weather_stat(
        self,
        hub: str | Hub,
        metric: ClimateMetric | str,
        period: str | Period = "last_year",
        source: SourceId = SourceId.NOAA_GHCN_DAILY,
    ) -> WeatherStatResult:
        h = self.hub(hub)
        try:
            m = ClimateMetric(metric)
        except ValueError:
            raise InvalidRequestError(
                f"unsupported metric {metric!r}; supported: {[x.value for x in ClimateMetric]}"
            ) from None
        p = self.resolve_period(period)
        stat, ds = self._stat(h, m, p, source)
        base = f"{h.id}.stat.{m.value}.{p.key}.{source.value}"
        cov = coverage_info(stat)
        facts = [
            Fact(fact_id=f"{base}.percent", label=f"% of valid days: {stat.definition}",
                 value=_round(stat.percent_of_valid_days, 2), unit="%", kind="statistic",
                 source_ids=[source], period=p.label, status=stat.status),
            Fact(fact_id=f"{base}.event_days", label=f"number of {stat.definition}",
                 value=stat.event_days, unit="days", kind="count", source_ids=[source],
                 period=p.label, status=stat.status),
            Fact(fact_id=f"{base}.valid_days", label="valid observation days",
                 value=stat.valid_days, unit="days", kind="count", source_ids=[source],
                 period=p.label),
            Fact(fact_id=f"{base}.expected_days", label="days in period",
                 value=stat.expected_days, unit="days", kind="count", source_ids=[source],
                 period=p.label),
            Fact(fact_id=f"{base}.missing_days", label="days without a reported value",
                 value=stat.missing_days, unit="days", kind="count", source_ids=[source],
                 period=p.label),
            Fact(fact_id=f"{base}.excluded_days", label="days excluded by NOAA quality flags",
                 value=stat.excluded_days, unit="days", kind="count", source_ids=[source],
                 period=p.label),
            Fact(fact_id=f"{base}.coverage", label="valid-observation coverage",
                 value=_round(100 * stat.coverage, 2), unit="%", kind="statistic",
                 source_ids=[source], period=p.label),
            Fact(fact_id=f"{base}.annual_average", label=f"annual average: {stat.definition}",
                 value=_round(stat.annual_average, 2), unit="days/yr", kind="statistic",
                 source_ids=[source], period=p.label, status=stat.status),
        ]  # fmt: skip
        assumptions = [
            f"Observations from {'NOAA station ' + h.noaa_station.id if source is SourceId.NOAA_GHCN_DAILY else 'Open-Meteo ERA5 grid cell'} represent the {h.display_name}.",  # noqa: E501
            "Percentages use days with a valid observation as the denominator; missing and "
            "quality-flagged days are excluded, never counted as zero.",
            *h.assumptions,
        ]
        if m in (ClimateMetric.SNOW_DAYS_MEASURABLE, ClimateMetric.SNOW_DAYS_TRACE_INCLUSIVE):
            assumptions.append("Measurable snowfall = reported amount > 0; trace (NOAA flag 'T') "
                               "is counted only in the trace-inclusive definition.")  # fmt: skip
        limitations = self._base_limitations()[1:3]
        if ds.provenance.data_kind is DataKind.MODELED_REANALYSIS:
            limitations.append("Open-Meteo values are modeled ERA5 reanalysis, not observations; "
                               "do not compare directly with NOAA station statistics.")  # fmt: skip
        if stat.status != "ok":
            limitations.append(
                f"Insufficient coverage: {stat.coverage:.1%} valid observations < required "
                f"{stat.min_coverage:.0%}; no value is reported."
            )
        return WeatherStatResult(
            hub_id=h.id, metric=m, definition=stat.definition, period=p, source_id=source,
            data_kind=ds.provenance.data_kind.value, location_id=ds.provenance.location_id,
            status=stat.status, value_percent_of_valid_days=stat.percent_of_valid_days,
            event_days=stat.event_days, annual_average_days=stat.annual_average, coverage=cov,
            facts=facts, sources=[_source_ref(ds.provenance)],
            methodology_version=self.cfg.methodology_version,
            assumptions=assumptions, limitations=limitations,
        )  # fmt: skip

    # ------------------------------------------------------------------ 2. profile
    def get_hub_profile(self, hub: str | Hub) -> HubProfile:
        h = self.hub(hub)
        if h.id in self._profiles:
            return self._profiles[h.id]
        pct = self.percentiles()
        county = self.county(h)
        period = self.climatology
        source = self.cfg.climate.source
        stats: dict[ClimateMetric, DayCountStatistic] = {}
        ds = None
        needed = {
            i.metric
            for hc in self.cfg.hazards.values()
            for i in hc.indicators
            if i.kind == "climate_anchor"
        }
        for metric in sorted(needed, key=lambda x: x.value):
            stats[metric], ds = self._stat(h, metric, period, source)
        inputs = HubInputs(hub_id=h.id, county=county, climate_stats=stats,
                           climate_period_label=period.label, climate_source=source)  # fmt: skip
        hazards, overall, status = score_hub(inputs, pct, self.cfg)

        facts = [
            Fact(fact_id=f"{h.id}.overall.score", label="Weather Hazard Exposure Index (overall)",
                 value=_round(overall, 2), unit="index 0–100", kind="score",
                 source_ids=[source, SourceId.FEMA_NRI], period=period.label, status=status),
            Fact(fact_id=f"{h.id}.overall.band", label="overall band (heuristic)",
                 value=self.cfg.band_for(overall), kind="label", status=status),
        ]  # fmt: skip
        for hz in hazards.values():
            facts.append(Fact(fact_id=f"{h.id}.{hz.hazard.value}.score",
                              label=f"{hz.label} exposure score", value=_round(hz.score, 2),
                              unit="index 0–100", kind="score", status=hz.status))  # fmt: skip
            for ind in hz.indicators:
                facts.append(Fact(fact_id=ind.fact_ids[0], label=ind.label,
                                  value=_round(ind.raw_value, 4), unit=ind.raw_unit,
                                  kind="frequency" if ind.kind == "nri_percentile" else "statistic",
                                  source_ids=ind.source_ids, period=ind.period,
                                  status=ind.raw_status))  # fmt: skip
                facts.append(Fact(fact_id=ind.fact_ids[1], label=f"{ind.indicator_id} score",
                                  value=_round(ind.score, 2), unit="index 0–100",
                                  kind="percentile" if ind.kind == "nri_percentile" else "score",
                                  source_ids=ind.source_ids, period=ind.period,
                                  status=ind.raw_status))  # fmt: skip
        sources = [_source_ref(county.provenance)]
        if ds is not None:
            sources.append(_source_ref(ds.provenance))
        assumptions = [
            f"Hazard frequencies use {h.hazard_county.name} (FIPS {h.hazard_county.fips}); "
            f"climate statistics use NOAA station {h.noaa_station.id} ({h.noaa_station.name}).",
            "Equal hazard weights are a transparent default, not validated operational priorities.",
            *h.assumptions,
        ]
        profile = HubProfile(
            hub_id=h.id, display_name=h.display_name, region=h.region.value,
            methodology_version=self.cfg.methodology_version, nri_version=pct.nri_version,
            climate_source=source, climate_period=period.label, fema_period_note=FEMA_PERIOD_NOTE,
            overall_score=overall, overall_band=self.cfg.band_for(overall), overall_status=status,
            hazards=hazards, facts=facts, sources=sources, assumptions=assumptions,
            limitations=self._base_limitations(),
        )  # fmt: skip
        self._profiles[h.id] = profile
        return profile

    # ------------------------------------------------------------------ 3. rank
    def _select_hubs(self, region: Region | str | None, hubs: list[str] | None) -> list[Hub]:
        selected = [self.hub(x) for x in hubs] if hubs else list(self.catalog.hubs)
        if region is not None:
            try:
                r = Region(region) if not isinstance(region, Region) else region
            except ValueError:
                raise UnsupportedRegionError(
                    f"unsupported region {region!r}; supported: {[x.value for x in Region]}"
                ) from None
            selected = [h for h in selected if h.region is r]
            if not selected:
                raise UnsupportedRegionError(f"no catalog hubs in region {r.value}")
        ids = [h.id for h in selected]
        if len(set(ids)) != len(ids):
            raise InvalidRequestError("duplicate hubs requested")
        return selected

    def rank_hubs(
        self,
        hazard: Hazard | str | None = None,
        region: Region | str | None = None,
        hubs: list[str] | None = None,
    ) -> RankingResult:
        hz = resolve_hazard(hazard) if hazard is not None else None
        selected = self._select_hubs(region, hubs)
        profiles = [self.get_hub_profile(h) for h in selected]
        versions = {p.nri_version for p in profiles}
        periods = {p.climate_period for p in profiles}
        sources = {p.climate_source for p in profiles}
        if len(versions) != 1 or len(periods) != 1 or len(sources) != 1:
            raise InvalidRequestError(
                "profiles are not comparable (mixed versions/periods/sources)"
            )

        rows = []
        for p in profiles:
            if hz is None:
                score, status, band = p.overall_score, p.overall_status, p.overall_band
                ordered = sorted(p.hazards.values(),
                                 key=lambda r: (-(r.contribution_to_overall or 0), r.hazard.value))  # fmt: skip
                top = [
                    f"{r.hazard.value} ({r.score:.1f})" for r in ordered[:2] if r.score is not None
                ]
                fid = f"{p.hub_id}.overall.score"
            else:
                r = p.hazards[hz]
                score, status, band = r.score, r.status, r.band
                inds = sorted(r.indicators, key=lambda i: (-i.contribution, i.indicator_id))
                top = [f"{i.indicator_id} ({i.score:.1f})" for i in inds[:2] if i.score is not None]
                fid = f"{p.hub_id}.{hz.value}.score"
            rows.append((p, score, status, band, top, fid))

        def rankable(status: str, score: float | None) -> bool:
            if score is None:
                return False
            return status == "complete" or (status == "partial" and
                                            self.cfg.coverage.rank_partial_results)  # fmt: skip

        ranked_rows = sorted(
            [r for r in rows if rankable(r[2], r[1])],
            key=lambda r: (-round(r[1], 9), r[0].hub_id),
        )
        ranked: list[RankingEntry] = []
        prev_score, prev_rank = None, 0
        for i, (p, score, status, band, top, fid) in enumerate(ranked_rows, start=1):
            rank = prev_rank if prev_score is not None and round(score, 9) == prev_score else i
            prev_score, prev_rank = round(score, 9), rank
            ranked.append(RankingEntry(rank=rank, hub_id=p.hub_id, display_name=p.display_name,
                                       score=score, band=band, status=status,
                                       top_contributors=top, fact_id=fid))  # fmt: skip
        not_ranked = [
            RankingEntry(rank=None, hub_id=p.hub_id, display_name=p.display_name, score=score,
                         band=band, status=status, top_contributors=top, fact_id=fid)
            for (p, score, status, band, top, fid) in sorted(rows, key=lambda r: r[0].hub_id)
            if not rankable(status, score)
        ]  # fmt: skip
        scope_key = hz.value if hz else "overall"
        region_key = (Region(region).value if region else "all") if not hubs else "custom"
        facts = [
            Fact(fact_id=f"rank.{scope_key}.{region_key}.{e.hub_id}", label=f"rank ({scope_key})",
                 value=e.rank, kind="rank", status=e.status)
            for e in ranked
        ]  # fmt: skip
        limitations = self._base_limitations()
        if not_ranked:
            limitations.append(
                "Hubs with partial or unavailable results are listed separately and not ranked, "
                "because their scores are not directly comparable: "
                + ", ".join(f"{e.hub_id} ({e.status})" for e in not_ranked)
            )
        return RankingResult(
            scope="hazard" if hz else "overall", hazard=hz,
            region=Region(region).value if region else None,
            hub_ids=[h.id for h in selected], ranked=ranked, not_ranked=not_ranked,
            tie_break="score descending; exact ties share a rank; listed by hub_id ascending",
            methodology_version=self.cfg.methodology_version, nri_version=versions.pop(),
            climate_period=periods.pop(), facts=facts,
            assumptions=["Equal hazard weights (overall ranking)." if not hz else
                         f"Ranking by the {hz.value} hazard score only."],
            limitations=limitations,
        )  # fmt: skip

    # ------------------------------------------------------------------ 4. compare
    def compare_hubs(
        self, hubs: list[str], hazards: list[Hazard | str] | None = None
    ) -> ComparisonResult:
        selected = self._select_hubs(None, hubs)
        if len(selected) < 2:
            raise InvalidRequestError("compare_hubs needs at least two distinct hubs")
        hz_list = [resolve_hazard(x) for x in hazards] if hazards else list(Hazard)
        profiles = {h.id: self.get_hub_profile(h) for h in selected}
        rows = []
        for hz in hz_list:
            scores = {hid: p.hazards[hz].score for hid, p in profiles.items()}
            status = {hid: p.hazards[hz].status for hid, p in profiles.items()}
            avail = sorted(((s, hid) for hid, s in scores.items() if s is not None),
                           key=lambda t: (-t[0], t[1]))  # fmt: skip
            leader = diff = None
            if len(avail) >= 2:
                diff = avail[0][0] - avail[1][0]
                leader = avail[0][1] if diff > 1e-9 else None
            rows.append(ComparisonRow(
                hazard=hz, hub_scores=scores, hub_status=status, leader=leader, difference=diff,
                indicators={hid: p.hazards[hz].indicators for hid, p in profiles.items()},
            ))  # fmt: skip
        nri_raw: dict[str, dict[HazardCode, dict[str, float | str | None]]] = {}
        nri_codes = {i.nri_hazard for hz in hz_list for i in self.cfg.hazards[hz].indicators
                     if i.nri_hazard}  # fmt: skip
        for h in selected:
            rec = self.county(h)
            nri_raw[h.id] = {
                code: {"afreq": rec.hazards[code].annualized_frequency,
                       "events": rec.hazards[code].events,
                       "status": rec.hazards[code].status.value}
                for code in sorted(nri_codes, key=lambda c: c.value)
            }  # fmt: skip
        facts = [f for p in profiles.values() for f in p.facts
                 if any(f.fact_id.startswith(f"{p.hub_id}.{hz.value}.") for hz in hz_list)]  # fmt: skip
        return ComparisonResult(
            hub_ids=[h.id for h in selected], hazards=hz_list, rows=rows, nri_raw=nri_raw,
            methodology_version=self.cfg.methodology_version,
            nri_version=self.percentiles().nri_version, facts=facts,
            assumptions=[a for p in profiles.values() for a in p.assumptions[:1]],
            limitations=self._base_limitations()
            + ["Flood exposure uses FEMA coastal and inland flooding frequencies, not rainfall.",
               "Hurricane exposure uses FEMA hurricane frequency, not observed wind speeds."],
        )  # fmt: skip

    # ------------------------------------------------------------------ 5. explain
    def explain_hub_score(self, hub: str | Hub, claimed_band: str | None = None) -> Explanation:
        p = self.get_hub_profile(hub)
        ranking = self.rank_hubs()
        rank = next((e.rank for e in ranking.ranked if e.hub_id == p.hub_id), None)
        by_contrib = sorted(p.hazards.values(),
                            key=lambda r: (-(r.contribution_to_overall or -1), r.hazard.value))  # fmt: skip
        # indicator contribution to the OVERALL score = hazard weight · indicator contribution
        weighted: list[tuple[float, IndicatorResult]] = []
        for hz in p.hazards.values():
            for ind in hz.indicators:
                if ind.score is not None and hz.score is not None:
                    weighted.append((hz.weight_in_overall * ind.contribution, ind))
        top = [i for _, i in sorted(weighted, key=lambda t: (-t[0], t[1].indicator_id))[:5]]
        na = [f"{hz.hazard.value}.{i.indicator_id}" for hz in p.hazards.values()
              for i in hz.indicators if i.raw_status == "not_applicable"]  # fmt: skip
        unavailable = [f"{hz.hazard.value}.{i.indicator_id} ({i.raw_status})"
                       for hz in p.hazards.values() for i in hz.indicators if i.score is None]  # fmt: skip

        premise = None
        if claimed_band is not None:
            claim = claimed_band.strip().capitalize()
            labels = [b.label for b in self.cfg.bands]
            if claim not in labels:
                raise InvalidRequestError(f"claimed band must be one of {labels}")
            if p.overall_score is None:
                premise = PremiseCheck(claim=f"overall exposure is {claim}", supported=None,
                                       reasoning="overall score unavailable; cannot evaluate")  # fmt: skip
            else:
                supported = p.overall_band == claim
                premise = PremiseCheck(
                    claim=f"overall exposure is {claim}",
                    supported=supported,
                    reasoning=(
                        f"overall index {p.overall_score:.1f} is in band '{p.overall_band}' "
                        f"(bands: "
                        + ", ".join(f"{b.label} ≥ {b.min:g}" for b in self.cfg.bands)
                        + f"); rank {rank} of {len(ranking.ranked)} ranked catalog hubs."
                    ),
                )
        return Explanation(
            hub_id=p.hub_id, overall_score=p.overall_score, overall_band=p.overall_band,
            overall_status=p.overall_status, rank_among_catalog=rank,
            catalog_size_ranked=len(ranking.ranked), hazards_by_contribution=by_contrib,
            top_indicators=top, not_applicable=na, unavailable=unavailable,
            premise_check=premise, methodology_version=p.methodology_version, facts=p.facts,
            assumptions=p.assumptions, limitations=p.limitations,
        )  # fmt: skip


__all__ = [
    "AnalyticsEngine",
    "UnsupportedHazardError",
    "UnsupportedRegionError",
    "UnsupportedPeriodError",
    "resolve_hazard",
    "HazardResult",
]
