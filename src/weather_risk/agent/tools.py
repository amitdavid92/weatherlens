"""Typed agent tools wrapping the deterministic AnalyticsEngine.

Each tool: Pydantic-validated arguments -> engine call -> (a) authoritative typed result for the
API payload, (b) a compact LLM-facing payload in which every number is a registered fact
reference {"fact": id, "value": display}. The LLM never receives a bare number to copy.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from weather_risk.agent.facts import FactRegistry
from weather_risk.analytics.config import ClimateMetric, Hazard
from weather_risk.analytics.engine import AnalyticsEngine
from weather_risk.analytics.models import (
    ComparisonResult,
    Explanation,
    HubProfile,
    RankingResult,
    WeatherStatResult,
)
from weather_risk.catalog import Region
from weather_risk.data.errors import (
    AmbiguousHubError,
    DataLayerError,
    DataUnavailableError,
    UnsupportedHubError,
)
from weather_risk.data.models import SourceId

MAX_TOOL_PAYLOAD_CHARS = 24_000
log = logging.getLogger("weather_risk.tools")

HazardName = Literal["winter", "hurricane", "flood", "severe_convective", "extreme_heat"]
RegionName = Literal["Midwest", "South", "West", "Northeast"]
MetricName = Literal[
    "snow_days_measurable",
    "snow_days_trace_inclusive",
    "heavy_snow_days",
    "freezing_days",
    "extreme_heat_days",
]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ListHubsArgs(_Args):
    region: RegionName | None = Field(None, description="Optional US Census region filter.")


class HubArgs(_Args):
    hub: str = Field(..., min_length=1, max_length=80,
                     description="Hub id, name, city or alias (e.g. 'Dallas', 'miami_fl').")  # fmt: skip


class RankHubsArgs(_Args):
    hazard: HazardName | None = Field(None, description="Rank by one hazard; omit for overall.")
    region: RegionName | None = Field(None, description="Restrict to a US Census region.")
    hubs: list[str] | None = Field(None, max_length=12, description="Restrict to these hubs.")


class CompareHubsArgs(_Args):
    hubs: list[str] = Field(..., min_length=2, max_length=6, description="Two to six hubs.")
    hazards: list[HazardName] | None = Field(None, description="Hazards to compare; omit = all.")


class WeatherStatArgs(_Args):
    hub: str = Field(..., min_length=1, max_length=80)
    metric: MetricName = Field(..., description=(
        "snow_days_measurable = days with measurable snowfall (default meaning of 'snowfall'); "
        "snow_days_trace_inclusive = measurable OR trace; heavy_snow_days (>=4 in); "
        "freezing_days (Tmin <= 0 C); extreme_heat_days (Tmax >= 95 F)."))  # fmt: skip
    period: str = Field("last year", max_length=40, description=(
        "'last year' (previous completed calendar year), 'YYYY', 'YYYY-YYYY', 'last N years', "
        "'past 12 months' or 'climatology' (2016-2025)."))  # fmt: skip
    source: Literal["noaa_ghcn_daily", "open_meteo_archive"] = Field(
        "noaa_ghcn_daily", description="NOAA station observations (default) or modeled ERA5."
    )


class ExplainArgs(_Args):
    hub: str = Field(..., min_length=1, max_length=80)
    claimed_band: Literal["Low", "Moderate", "High"] | None = Field(
        None, description="If the user asserts an exposure level (e.g. 'why is X high'), pass it "
        "so the premise is checked.")  # fmt: skip


TOOL_ARGS: dict[str, type[_Args]] = {
    "list_hubs": ListHubsArgs,
    "get_hub_profile": HubArgs,
    "rank_hubs": RankHubsArgs,
    "compare_hubs": CompareHubsArgs,
    "get_weather_stat": WeatherStatArgs,
    "explain_hub_score": ExplainArgs,
}

TOOL_DESCRIPTIONS = {
    "list_hubs": "List the supported (illustrative) distribution hubs, optionally by region.",
    "get_hub_profile": "Full weather-hazard exposure profile of one hub: overall index, band, "
    "five hazard scores, indicators, sources and limitations.",
    "rank_hubs": "Rank hubs by overall exposure or by one hazard, optionally within a region. "
    "Returns ranked hubs and hubs excluded with reasons.",
    "compare_hubs": "Compare 2-6 hubs on selected hazards (scores, leader, FEMA frequencies).",
    "get_weather_stat": "Historical day-count statistic for one hub and period from daily "
    "observations (percent of valid days, day counts, coverage, missing days).",
    "explain_hub_score": "Explain a hub's overall score: hazard-level drivers, top indicators, "
    "rank, and a premise check of a claimed band.",
}


class ToolExecution(BaseModel):
    name: str
    args: dict[str, Any]
    ok: bool
    error: str | None = None
    error_type: str | None = None
    latency_ms: float
    payload: dict[str, Any] = Field(default_factory=dict)  # compact, LLM-facing
    result: Any = None  # authoritative typed engine result (not sent to the LLM)


def function_declarations() -> list[dict[str, Any]]:
    """Provider-neutral tool declarations (name, description, JSON schema of arguments)."""
    out = []
    for name, model in TOOL_ARGS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        out.append({"name": name, "description": TOOL_DESCRIPTIONS[name], "parameters": schema})
    return out


class ToolBox:
    def __init__(self, engine: AnalyticsEngine, registry: FactRegistry) -> None:
        self.engine = engine
        self.reg = registry

    # ---------------------------------------------------------------- dispatch
    def execute(self, name: str, raw_args: dict[str, Any] | None) -> ToolExecution:
        t0 = time.perf_counter()
        args = dict(raw_args or {})

        def done(**kw: Any) -> ToolExecution:
            return ToolExecution(name=name, args=args,
                                 latency_ms=round((time.perf_counter() - t0) * 1000, 1), **kw)  # fmt: skip

        if name not in TOOL_ARGS:
            return done(ok=False, error=f"unknown tool {name!r}", error_type="unknown_tool",
                        payload={"error": f"unknown tool {name!r}"})  # fmt: skip
        try:
            parsed = TOOL_ARGS[name].model_validate(args)
        except ValidationError as exc:
            msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            return done(ok=False, error=f"invalid arguments: {msg}", error_type="invalid_arguments",
                        payload={"error": f"invalid arguments: {msg}"})  # fmt: skip
        try:
            payload, result = getattr(self, f"_{name}")(parsed)
        except AmbiguousHubError as exc:
            return done(ok=False, error=str(exc), error_type="ambiguous_hub",
                        payload={"error": str(exc), "candidates": exc.candidates,
                                 "action": "ask the user which hub they mean"})  # fmt: skip
        except UnsupportedHubError as exc:
            return done(ok=False, error=str(exc), error_type="unsupported_hub",
                        payload={"error": str(exc), "suggestions": exc.suggestions,
                                 "supported_hubs": exc.supported})  # fmt: skip
        except DataUnavailableError as exc:
            return done(ok=False, error=str(exc), error_type="data_unavailable",
                        payload={"error": "data unavailable from live sources, cache and "
                                 "snapshot; do not estimate"})  # fmt: skip
        except DataLayerError as exc:  # invalid period/hazard/region etc.
            return done(ok=False, error=str(exc), error_type="invalid_request",
                        payload={"error": str(exc)})  # fmt: skip
        except Exception:  # noqa: BLE001 - a tool bug must not become an HTTP 500
            log.exception("tool_internal_error", extra={"tool": name})
            return done(ok=False, error="internal tool error", error_type="internal_error",
                        payload={"error": "internal tool error; do not estimate"})  # fmt: skip
        text = json.dumps(payload, default=str)
        if len(text) > MAX_TOOL_PAYLOAD_CHARS:
            return done(ok=False, error="tool payload too large", error_type="payload_too_large",
                        payload={"error": "result too large; narrow the request"})  # fmt: skip
        return done(ok=True, payload=payload, result=result)

    # ---------------------------------------------------------------- helpers
    def _score(self, hub_id: str, topic: str, score: float | None, status: str, tool: str,
               period: str | None = None) -> dict:  # fmt: skip
        label = "overall exposure index" if topic == "overall" else f"{topic} exposure score"
        return self.reg.add(f"{hub_id}.{topic}.score", label=f"{hub_id} {label} (0-100)",
                            value=score, kind="score", unit="index 0–100", hub_id=hub_id,
                            topic=topic, period=period, status=status, tool=tool,
                            source_ids=["noaa_ghcn_daily", "fema_nri"])  # fmt: skip

    def _hub_card(self, hub_id: str) -> dict:
        h = self.engine.hub(hub_id)
        return {"hub_id": h.id, "name": h.display_name, "city": f"{h.city}, {h.state}",
                "region": h.region.value}  # fmt: skip

    def _profile_payload(self, p: HubProfile, tool: str) -> dict:
        hz = {}
        for k, r in p.hazards.items():
            inds = []
            for i in r.indicators:
                fid = f"{p.hub_id}.{k.value}.{i.indicator_id}"
                inds.append({
                    "indicator": i.indicator_id, "status": i.raw_status,
                    "raw": self.reg.add(f"{fid}.raw", label=f"{p.hub_id} {i.label}",
                                        value=i.raw_value, unit=i.raw_unit,
                                        kind="frequency" if i.kind == "nri_percentile" else "statistic",
                                        hub_id=p.hub_id, topic=k.value, period=i.period,
                                        source_ids=[s.value for s in i.source_ids],
                                        status=i.raw_status, tool=tool,
                                        display=_raw_display(i.raw_value, i.raw_unit, i.kind)),
                    "score": self.reg.add(f"{fid}.score", label=f"{p.hub_id} {i.indicator_id} score",
                                          value=i.score, kind="score", unit="index 0–100",
                                          hub_id=p.hub_id, topic=k.value, period=i.period,
                                          status=i.raw_status, tool=tool),
                })  # fmt: skip
            hz[k.value] = {"score": self._score(p.hub_id, k.value, r.score, r.status, tool,
                                                p.climate_period),
                           "band": r.band, "status": r.status, "indicators": inds,
                           "notes": r.notes}  # fmt: skip
        return {
            "hub": self._hub_card(p.hub_id),
            "overall": self._score(p.hub_id, "overall", p.overall_score, p.overall_status, tool,
                                   p.climate_period),
            "overall_band": p.overall_band, "overall_status": p.overall_status,
            "hazards": hz,
            "ranking_eligibility": {k: v.model_dump() for k, v in p.ranking_eligibility.items()},
            "climate_period": p.climate_period, "fema_period_note": p.fema_period_note,
            "methodology_version": p.methodology_version, "nri_version": p.nri_version,
            "limitations": p.limitations[:3],
        }  # fmt: skip

    # ---------------------------------------------------------------- tools
    def _list_hubs(self, a: ListHubsArgs) -> tuple[dict, list]:
        hubs = self.engine.catalog.in_region(a.region) if a.region else self.engine.catalog.hubs
        cards = [self._hub_card(h.id) for h in hubs]
        return {"illustrative": True, "note": "Assumed example hubs, not real facilities.",
                "hubs": cards}, cards  # fmt: skip

    def _get_hub_profile(self, a: HubArgs) -> tuple[dict, HubProfile]:
        p = self.engine.get_hub_profile(a.hub)
        return self._profile_payload(p, "get_hub_profile"), p

    def _rank_hubs(self, a: RankHubsArgs) -> tuple[dict, RankingResult]:
        r = self.engine.rank_hubs(hazard=a.hazard, region=a.region, hubs=a.hubs)
        topic = r.hazard.value if r.hazard else "overall"
        # ranks depend on the hub set, so an explicit subset is part of the fact id
        subset = "custom-" + "-".join(sorted(r.hub_ids)) if a.hubs else None
        scope = f"{topic}.{subset or r.region or 'all'}"

        def entry(e) -> dict:
            p = self.engine.get_hub_profile(e.hub_id)
            item = {"hub": self._hub_card(e.hub_id),
                    "score": self._score(e.hub_id, topic, e.score, e.status, "rank_hubs",
                                         r.climate_period),
                    "band": e.band, "status": e.status}  # fmt: skip
            if e.rank is not None:
                item["rank"] = self.reg.add(f"rank.{scope}.{e.hub_id}",
                                            label=f"{e.hub_id} rank ({scope})", value=e.rank,
                                            kind="rank", hub_id=e.hub_id, topic=topic,
                                            tool="rank_hubs")  # fmt: skip
            else:
                item["excluded_reason"] = e.exclusion_reason
                # the incomplete hazard and its available indicator weight, as verified facts
                partial = [h for h in p.hazards.values() if h.status != "complete"]
                if r.hazard is not None:
                    partial = [p.hazards[r.hazard]]
                if partial:
                    h = partial[0]
                    item["incomplete_hazard"] = h.hazard.value
                    item["available_weight"] = self.reg.add(
                        f"{e.hub_id}.{h.hazard.value}.available_weight",
                        label=f"{e.hub_id} share of {h.hazard.value} indicator weight with data",
                        value=round(100 * h.available_weight_fraction), unit="%", kind="statistic",
                        hub_id=e.hub_id, topic=h.hazard.value, tool="rank_hubs",
                        display=f"{round(100 * h.available_weight_fraction)}%")  # fmt: skip
            if r.hazard is None:
                drivers = sorted(p.hazards.values(),
                                 key=lambda h: -(h.contribution_to_overall or 0))[:2]  # fmt: skip
                item["top_hazards"] = [{"hazard": h.hazard.value,
                                        "score": self._score(e.hub_id, h.hazard.value, h.score,
                                                             h.status, "rank_hubs")}
                                       for h in drivers]  # fmt: skip
            else:
                hz = p.hazards[r.hazard]
                inds = sorted(hz.indicators, key=lambda i: -i.contribution)[:2]
                item["top_indicators"] = [
                    {"indicator": i.indicator_id,
                     "score": self.reg.add(f"{e.hub_id}.{topic}.{i.indicator_id}.score",
                                           label=f"{e.hub_id} {i.indicator_id} score",
                                           value=i.score, kind="score", unit="index 0–100",
                                           hub_id=e.hub_id, topic=topic, status=i.raw_status,
                                           tool="rank_hubs")}
                    for i in inds if i.score is not None]  # fmt: skip
            return item

        payload = {
            "scope": r.scope, "hazard": topic, "region": r.region,
            "ranked": [entry(e) for e in r.ranked],
            "not_ranked": [entry(e) for e in r.not_ranked],
            "tie_break": r.tie_break, "methodology_version": r.methodology_version,
            "climate_period": r.climate_period, "nri_version": r.nri_version,
        }  # fmt: skip
        return payload, r

    def _compare_hubs(self, a: CompareHubsArgs) -> tuple[dict, ComparisonResult]:
        c = self.engine.compare_hubs(a.hubs, a.hazards)
        rows = []
        for row in c.rows:
            hz = row.hazard.value
            item = {"hazard": hz,
                    "scores": {hid: self._score(hid, hz, s, row.hub_status[hid], "compare_hubs")
                               for hid, s in row.hub_scores.items()},
                    "status": row.hub_status, "leader": row.leader}  # fmt: skip
            if row.difference is not None:
                ordered = sorted((s, h) for h, s in row.hub_scores.items() if s is not None)
                pair = f"{ordered[-1][1]}_vs_{ordered[-2][1]}"
                item["difference"] = self.reg.add(
                    f"compare.{hz}.{pair}.difference", label=f"{hz} score difference ({pair})",
                    value=row.difference, kind="score", unit="index 0–100", hub_id=None,
                    topic=hz, tool="compare_hubs")  # fmt: skip
            rows.append(item)
        nri = {}
        for hid, codes in c.nri_raw.items():
            nri[hid] = {}
            for code, v in codes.items():
                nri[hid][code.name.lower()] = {
                    "status": v["status"],
                    "annualized_frequency": self.reg.add(
                        f"{hid}.nri.{code.value}.afreq",
                        label=f"{hid} FEMA NRI {code.name.lower()} annualized frequency",
                        value=v["afreq"], kind="frequency", unit="per year", hub_id=hid,
                        topic=code.name.lower(), period=f"NRI {c.nri_version} period of record",
                        source_ids=["fema_nri"], status=str(v["status"]), tool="compare_hubs",
                        display=_raw_display(v["afreq"], "per year", "nri_percentile")),
                }  # fmt: skip
        return {"hubs": [self._hub_card(h) for h in c.hub_ids], "rows": rows,
                "fema_annualized_frequencies": nri, "nri_version": c.nri_version,
                "methodology_version": c.methodology_version,
                "limitations": c.limitations[-2:]}, c  # fmt: skip

    def _get_weather_stat(self, a: WeatherStatArgs) -> tuple[dict, WeatherStatResult]:
        s = self.engine.get_weather_stat(a.hub, ClimateMetric(a.metric), a.period,
                                         source=SourceId(a.source))  # fmt: skip
        base = f"{s.hub_id}.stat.{s.metric.value}.{s.period.key}.{s.source_id.value}"
        meta = dict(hub_id=s.hub_id, topic=s.metric.value, period=s.period.label,
                    source_ids=[s.source_id.value], tool="get_weather_stat")  # fmt: skip
        cov = s.coverage
        R = self.reg.add  # noqa: N806
        payload = {
            "hub": self._hub_card(s.hub_id), "metric": s.metric.value, "definition": s.definition,
            "status": s.status, "source": s.source_id.value, "data_kind": s.data_kind,
            "station_or_grid": s.location_id,
            "period": R(f"{base}.period", label=f"observation period: {s.period.label}",
                        value=s.period.label, kind="label", **meta,
                        display=(str(s.period.start.year) if s.period.kind == "calendar_year"
                                 else f"{s.period.start.isoformat()} to {s.period.end.isoformat()}"
                                 if s.period.kind == "trailing"
                                 else f"{s.period.start.year}–{s.period.end.year}")),
            "percent_of_valid_days": R(f"{base}.percent", label=f"% of valid days: {s.definition}",
                                       value=s.value_percent_of_valid_days, unit="%",
                                       kind="statistic", status=s.status, **meta),
            "event_days": R(f"{base}.event_days", label=s.definition, value=s.event_days,
                            unit="days", kind="count", status=s.status, **meta),
            "valid_days": R(f"{base}.valid_days", label="days with a valid observation",
                            value=cov.valid_days, unit="days", kind="count", **meta),
            "expected_days": R(f"{base}.expected_days", label="days in period",
                               value=cov.expected_days, unit="days", kind="count", **meta),
            "missing_days": R(f"{base}.missing_days", label="days without a reported value",
                              value=cov.missing_days, unit="days", kind="count", **meta),
            "excluded_days": R(f"{base}.excluded_days", label="days excluded by quality flags",
                               value=cov.excluded_days, unit="days", kind="count", **meta),
            "coverage": R(f"{base}.coverage", label="valid-observation coverage",
                          value=round(100 * cov.coverage, 2), unit="%", kind="statistic", **meta),
            "annual_average": R(f"{base}.annual_average", label=f"annual average: {s.definition}",
                                value=s.annual_average_days, unit="days/yr", kind="statistic",
                                status=s.status, **meta),
            "assumptions": s.assumptions[:3], "limitations": s.limitations[-2:],
            "freshness": s.sources[0].freshness if s.sources else None,
        }  # fmt: skip
        missing_dates = [d.isoformat() for d in self._missing_dates(s)]
        if missing_dates:
            payload["missing_dates"] = R(f"{base}.missing_dates", label="dates without a value",
                                         value=", ".join(missing_dates), kind="label", **meta)  # fmt: skip
        return payload, s

    def _missing_dates(self, s: WeatherStatResult) -> list:
        h = self.engine.hub(s.hub_id)
        ds = self.engine.climate_dataset(h, s.period, s.source_id)
        from weather_risk.analytics.stats import METRIC_ELEMENT

        cov = ds.slice(s.period.start, s.period.end).coverage(METRIC_ELEMENT[s.metric])
        return cov.missing_dates_sample[:10]

    def _explain_hub_score(self, a: ExplainArgs) -> tuple[dict, Explanation]:
        e = self.engine.explain_hub_score(a.hub, claimed_band=a.claimed_band)
        hub = e.hub_id
        R = self.reg.add  # noqa: N806
        payload = {
            "hub": self._hub_card(hub),
            "overall": self._score(hub, "overall", e.overall_score, e.overall_status,
                                   "explain_hub_score"),
            "overall_band": e.overall_band, "overall_status": e.overall_status,
            "band_thresholds": "Low < 40 <= Moderate < 70 <= High (heuristic labels)",
            "primary_driver_hazard": e.primary_driver,
            "hazards_by_contribution": [
                {"hazard": h.hazard.value, "band": h.band,
                 "score": self._score(hub, h.hazard.value, h.score, h.status, "explain_hub_score"),
                 "contribution_to_overall": R(f"{hub}.{h.hazard.value}.contribution_to_overall",
                                              label=f"{hub} {h.hazard.value} points of the overall "
                                              "index", value=h.contribution_to_overall,
                                              kind="statistic", unit="points", hub_id=hub,
                                              topic=h.hazard.value, tool="explain_hub_score",
                                              display=_pts(h.contribution_to_overall))}  # noqa: E501
                for h in e.hazards_by_contribution],
            "top_indicators": [
                {"hazard": i.hazard.value, "indicator": i.indicator_id, "label": i.label,
                 "raw": R(f"{hub}.{i.hazard.value}.{i.indicator_id}.raw", label=f"{hub} {i.label}",
                          value=i.raw_value, unit=i.raw_unit, kind="statistic", hub_id=hub,
                          topic=i.hazard.value, tool="explain_hub_score",
                          display=_raw_display(i.raw_value, i.raw_unit,
                                               "nri_percentile" if "NRI" in i.raw_unit else "x")),
                 "score": R(f"{hub}.{i.hazard.value}.{i.indicator_id}.score",
                            label=f"{hub} {i.indicator_id} score", value=i.score, kind="score",
                            unit="index 0–100", hub_id=hub, topic=i.hazard.value,
                            tool="explain_hub_score"),
                 "contribution_to_overall": R(
                     f"{hub}.{i.hazard.value}.{i.indicator_id}.contribution_to_overall",
                     label=f"{hub} {i.indicator_id} points of the overall index",
                     value=i.contribution_to_overall, kind="statistic", unit="points",
                     hub_id=hub, topic=i.hazard.value, tool="explain_hub_score",
                     display=_pts(i.contribution_to_overall))}
                for i in e.top_indicators],
            "indicator_contribution_note": e.indicator_contribution_note,
            "not_applicable": e.not_applicable, "unavailable": e.unavailable,
            "methodology_version": e.methodology_version,
            "framing": "Weather-hazard EXPOSURE index, not operational disruption risk.",
        }  # fmt: skip
        if e.rank_among_catalog is not None:
            payload["rank_overall"] = R(f"rank.overall.all.{hub}", label=f"{hub} overall rank",
                                        value=e.rank_among_catalog, kind="rank", hub_id=hub,
                                        topic="overall", tool="explain_hub_score")  # fmt: skip
            payload["ranked_hub_count"] = R("rank.overall.all.count",
                                            label="number of hubs in the overall ranking",
                                            value=e.catalog_size_ranked, kind="count",
                                            tool="explain_hub_score")  # fmt: skip
        if e.premise_check is not None:
            pc = e.premise_check
            payload["premise_check"] = {"claim": pc.claim, "supported": pc.supported,
                                        "reasoning_facts_above": True}  # fmt: skip
        return payload, e


def _pts(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}"


def _raw_display(value: float | None, unit: str, kind: str) -> str:
    if value is None:
        return "n/a"
    if kind == "nri_percentile" or "NRI" in unit or unit == "per year":
        per = f" (about 1 in {1 / value:.0f} years)" if 0 < value <= 0.5 else ""
        return f"{value:.3g} per year{per}"
    if unit == "days/yr":
        return f"{value:.1f}"
    return f"{value:.4g}"


ALL_TOOL_NAMES = list(TOOL_ARGS)
HazardEnum = Hazard
RegionEnum = Region
