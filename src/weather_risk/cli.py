"""Command-line entry points for the data layer.

    uv run weather-risk hubs                      # list the illustrative catalog
    uv run weather-risk build-snapshot            # fetch + validate + write data/snapshot/
    uv run weather-risk verify-snapshot           # check manifest hashes
    uv run weather-risk validate-data [--offline] [--out docs/PHASE_1_VALIDATION.md]

`validate-data` reports factual availability/coverage only (no scoring).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from weather_risk.catalog import HubCatalog, Region, load_catalog
from weather_risk.config import PROJECT_ROOT, Settings, get_settings
from weather_risk.data.adapters import fema_nri
from weather_risk.data.errors import DataLayerError
from weather_risk.data.models import (
    ClimateDataset,
    ClimateElement,
    Freshness,
    HazardCode,
    HazardReferencePopulation,
    ObservationStatus,
)
from weather_risk.data.repository import DataRepository, build_repository
from weather_risk.data.snapshot import SnapshotStore, SnapshotWriter
from weather_risk.logging_setup import configure_logging

CLIMATOLOGY_START_YEAR = 2016
CLIMATOLOGY_END_YEAR = 2025  # last completed calendar year at build time (2026-11-25)
OPEN_METEO_THROTTLE_SECONDS = 2.0  # stay well under the 600/min weighted rate limit


# --------------------------------------------------------------------------- snapshot


def build_snapshot(settings: Settings, catalog: HubCatalog) -> Path:
    repo = build_repository(settings.model_copy(update={"offline": False}), use_snapshot=False)
    writer = SnapshotWriter(
        settings.snapshot_dir,
        description=(
            f"Raw responses for the illustrative hub catalog: NOAA GHCN-Daily and Open-Meteo "
            f"ERA5 daily data {CLIMATOLOGY_START_YEAR}-{CLIMATOLOGY_END_YEAR} (calendar-year "
            "chunks), FEMA NRI hub county records and the national county reference table."
        ),
        generator="weather-risk build-snapshot",
    )

    def store(req, rel: str, version: str | None = None) -> None:
        cached = repo.cache.get(req)
        if cached is None:
            raise RuntimeError(f"expected cached body for {rel}")
        writer.add(req, cached.body, relative_file=rel, retrieved_at=cached.fetched_at,
                   dataset_version=version)  # fmt: skip

    years = range(CLIMATOLOGY_START_YEAR, CLIMATOLOGY_END_YEAR + 1)
    for hub in catalog.hubs:
        st = hub.noaa_station.id
        for y in years:
            repo.get_station_daily(st, date(y, 1, 1), date(y, 12, 31))
            store(repo.noaa_year_request(st, y), f"noaa_ghcn/{st}_{y}.json.gz")
        print(f"NOAA {hub.id} ok", file=sys.stderr)
    for hub in catalog.hubs:
        for y in years:
            req = repo.open_meteo_year_request(hub.latitude, hub.longitude, hub.timezone, y)
            was_cached = repo.cache.get(req) is not None
            repo.get_open_meteo_daily(
                hub.latitude, hub.longitude, hub.timezone, date(y, 1, 1), date(y, 12, 31)
            )
            store(req, f"open_meteo/{hub.id}_{y}.json.gz", "era5")
            if not was_cached:
                time.sleep(OPEN_METEO_THROTTLE_SECONDS)
        print(f"Open-Meteo {hub.id} ok", file=sys.stderr)
    for hub in catalog.hubs:
        rec = repo.get_county_hazards(hub.hazard_county.fips)
        store(
            fema_nri.build_county_request(hub.hazard_county.fips),
            f"fema_nri/county_{hub.hazard_county.fips}.json.gz",
            rec.nri_version,
        )
    ref = repo.get_hazard_reference()
    store(fema_nri.build_count_request(), "fema_nri/national_count.json.gz", ref.nri_version)
    for offset in range(0, ref.total_count, fema_nri.PAGE_SIZE):
        store(
            fema_nri.build_page_request(offset),
            f"fema_nri/national_page_{offset:05d}.json.gz",
            ref.nri_version,
        )
    path = writer.write_manifest()
    problems = SnapshotStore(settings.snapshot_dir).verify()
    if problems:
        raise RuntimeError(f"snapshot verification failed: {problems}")
    return path


# --------------------------------------------------------------------------- validation


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def _coverage_cells(ds: ClimateDataset, elements: list[ClimateElement]) -> list[str]:
    return [_pct(ds.coverage(e).reported_days, ds.coverage(e).expected_days) for e in elements]


def _fmt_freq(v: float | None) -> str:
    return "—" if v is None else f"{v:.4g}"


def validate_data(repo: DataRepository, catalog: HubCatalog) -> str:
    started = datetime.now(UTC)
    start, end = date(CLIMATOLOGY_START_YEAR, 1, 1), date(CLIMATOLOGY_END_YEAR, 12, 31)
    out: list[str] = []
    w = out.append
    freshness_seen: Counter[str] = Counter()
    failures: list[str] = []

    w("# Phase 1 — Live Data Validation (generated)\n")
    w(f"Generated by `weather-risk validate-data` at {started.isoformat(timespec='seconds')}.")
    w(f"Offline mode: `{repo.settings.offline}`. Climatology window: {start} … {end}.")
    w("All values below are retrieved/parsed by the implemented adapters — nothing hardcoded. ")
    w("This report shows data availability and raw facts only; no scoring is performed.\n")

    # ---- reference population
    ref: HazardReferencePopulation | None = None
    try:
        ref = repo.get_hazard_reference()
        freshness_seen[f"fema_nri:{ref.provenance.freshness}"] += 1
        excluded = Counter(r.state_abbrev for r in ref.excluded_records)
        w("## NRI national reference population\n")
        w(f"- NRI version: **{ref.nri_version}**; freshness `{ref.provenance.freshness}`")
        w(
            f"- Records returned (validated count, unique FIPS, single version): **{ref.total_count}**"
        )
        w(f"- Reference population (50 states + DC): **{len(ref.reference_records)}**")
        w(
            f"- Excluded territories: **{len(ref.excluded_records)}** {dict(sorted(excluded.items()))}\n"
        )
        w("| Hazard | observed | observed_zero | not_applicable | insufficient_data | unknown |")
        w("|---|---|---|---|---|---|")
        for h in HazardCode:
            c = ref.status_counts(h)
            w(f"| {h.name} ({h.value}) | {c['observed']} | {c['observed_zero']} | "
              f"{c['not_applicable']} | {c['insufficient_data']} | {c['unknown']} |")  # fmt: skip
        w("")
    except DataLayerError as exc:
        failures.append(f"NRI reference: {exc}")
        w(f"## NRI national reference population\n\n**UNAVAILABLE:** {exc}\n")

    # ---- all hubs
    elements_noaa = [ClimateElement.SNOWFALL, ClimateElement.PRECIPITATION, ClimateElement.TMIN,
                     ClimateElement.TMAX, ClimateElement.WIND_AVG, ClimateElement.WIND_GUST_MAX]  # fmt: skip
    noaa: dict[str, ClimateDataset] = {}
    om: dict[str, ClimateDataset] = {}
    counties = {}
    w("## All 12 hubs — representability\n")
    w("NOAA columns: % of days with a reported value, "
      f"{start.year}–{end.year}. Open-Meteo: % non-null snowfall.\n")  # fmt: skip
    w("| Hub | Region | Station (county) | Hazard county | SNOW | PRCP | TMIN | TMAX | AWND | WSF5 "
      "| Open-Meteo | NRI ver. | NRI statuses (obs/zero/NA/ID/unk) | Same NRI ver. as ref |")  # fmt: skip
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for hub in catalog.hubs:
        cells: list[str] = []
        try:
            ds = repo.get_station_daily(hub.noaa_station.id, start, end)
            noaa[hub.id] = ds
            freshness_seen[f"noaa:{ds.provenance.freshness}"] += 1
            cells += _coverage_cells(ds, elements_noaa)
        except DataLayerError as exc:
            failures.append(f"NOAA {hub.id}: {exc}")
            cells += ["UNAVAILABLE"] * len(elements_noaa)
        try:
            o = repo.get_open_meteo_daily(hub.latitude, hub.longitude, hub.timezone, start, end)
            om[hub.id] = o
            freshness_seen[f"open_meteo:{o.provenance.freshness}"] += 1
            cells.append(_coverage_cells(o, [ClimateElement.SNOWFALL])[0])
        except DataLayerError as exc:
            failures.append(f"Open-Meteo {hub.id}: {exc}")
            cells.append("UNAVAILABLE")
        try:
            rec = repo.get_county_hazards(hub.hazard_county.fips)
            counties[hub.id] = rec
            freshness_seen[f"fema_nri:{rec.provenance.freshness}"] += 1
            st = Counter(v.status.value for v in rec.hazards.values())
            same = "yes" if ref and rec.nri_version == ref.nri_version else "NO"
            cells += [rec.nri_version,
                      f"{st['observed']}/{st['observed_zero']}/{st['not_applicable']}/"
                      f"{st['insufficient_data']}/{st['unknown']}", same]  # fmt: skip
            if ref:
                ref_rec = ref.get(hub.hazard_county.fips)
                if ref_rec is None or ref_rec.hazards != rec.hazards:
                    failures.append(f"NRI {hub.id}: county record differs from reference table")
        except DataLayerError as exc:
            failures.append(f"NRI {hub.id}: {exc}")
            cells += ["UNAVAILABLE", "", ""]
        station = f"{hub.noaa_station.id} ({hub.noaa_station.county_name})"
        county = f"{hub.hazard_county.name} ({hub.hazard_county.fips})"
        flag = " ⚠︎" if hub.station_county_differs else ""
        w(f"| {hub.id} | {hub.region} | {station}{flag} | {county} | " + " | ".join(cells) + " |")
    w("\n⚠︎ = station county differs from hazard county (documented in `config/hubs.yaml`).\n")

    # ---- scenario 1
    w("## Scenario 1 — Midwest winter exposure inputs\n")
    w(f"NOAA counts are days by snowfall status over {start.year}–{end.year} "
      "(measured = ≥ measurable amount; trace flagged separately). NRI: annualized frequency "
      "(status).\n")  # fmt: skip
    w("| Hub | measured | trace | zero | missing | TMIN reported | WNTW AFREQ | ISTM AFREQ "
      "| CWAV AFREQ |")  # fmt: skip
    w("|---|---|---|---|---|---|---|---|---|")
    for hub in catalog.in_region(Region.MIDWEST):
        ds, rec = noaa.get(hub.id), counties.get(hub.id)
        if ds:
            c = ds.status_counts(ClimateElement.SNOWFALL)
            tmin = ds.coverage(ClimateElement.TMIN)
            noaa_cells = (f"{c[ObservationStatus.MEASURED]} | {c[ObservationStatus.TRACE]} | "
                          f"{c[ObservationStatus.ZERO]} | {c[ObservationStatus.MISSING]} | "
                          f"{tmin.reported_days}/{tmin.expected_days}")  # fmt: skip
        else:
            noaa_cells = "UNAVAILABLE | | | |"
        nri_cells = " | ".join(
            f"{_fmt_freq(rec.hazards[h].annualized_frequency)} ({rec.hazards[h].status.value})"
            if rec
            else "UNAVAILABLE"
            for h in (HazardCode.WINTER_WEATHER, HazardCode.ICE_STORM, HazardCode.COLD_WAVE)
        )
        w(f"| {hub.id} | {noaa_cells} | {nri_cells} |")
    w("")

    # ---- scenario 2
    w("## Scenario 2 — Miami vs Houston: hurricane, coastal flood, inland flood (NRI)\n")
    w("| Hub | County | Hazard | AFREQ (/yr) | Events in record | Status | EAL rating |")
    w("|---|---|---|---|---|---|---|")
    for hub_id in ("miami_fl", "houston_tx"):
        rec = counties.get(hub_id)
        for h in (HazardCode.HURRICANE, HazardCode.COASTAL_FLOODING, HazardCode.INLAND_FLOODING):
            if rec is None:
                w(f"| {hub_id} | | {h.name} | UNAVAILABLE | | | |")
                continue
            v = rec.hazards[h]
            w(f"| {hub_id} | {rec.county_name} {rec.state_abbrev} ({rec.county_fips}) | "
              f"{h.name} | {_fmt_freq(v.annualized_frequency)} | {_fmt_freq(v.events)} | "
              f"{v.status.value} | {v.eal_rating} |")  # fmt: skip
    versions = {counties[h].nri_version for h in ("miami_fl", "houston_tx") if h in counties}
    w(f"\nNRI version(s): {sorted(versions)} — comparable resolution: county.\n")

    # ---- scenario 3
    w(f"## Scenario 3 — Denver daily snowfall, calendar year {CLIMATOLOGY_END_YEAR}\n")
    y0, y1 = date(CLIMATOLOGY_END_YEAR, 1, 1), date(CLIMATOLOGY_END_YEAR, 12, 31)
    for label, src in (("NOAA GHCN-Daily (primary, observed)", noaa),
                       ("Open-Meteo ERA5 (alternative, modeled)", om)):  # fmt: skip
        ds = src.get("denver_co")
        if not ds:
            w(f"- {label}: UNAVAILABLE")
            continue
        d = ds.slice(y0, y1)
        c = d.status_counts(ClimateElement.SNOWFALL)
        cov = d.coverage(ClimateElement.SNOWFALL)
        w(f"- **{label}** — location `{d.provenance.location_id}`, freshness "
          f"`{d.provenance.freshness}`: days={len(d.records)}; measured={c[ObservationStatus.MEASURED]}, "
          f"trace={c[ObservationStatus.TRACE]}, zero={c[ObservationStatus.ZERO]}, "
          f"missing={c[ObservationStatus.MISSING]} (missing dates: "
          f"{[x.isoformat() for x in cov.missing_dates_sample]})")  # fmt: skip
    w("\nThe percentage itself is computed by the Phase 2 analytics layer (definition: measurable "
      "snow days / days with a reported value; trace reported separately).\n")  # fmt: skip

    # ---- scenario 4
    w("## Scenario 4 — Dallas weather hazard records (NRI, Dallas County)\n")
    rec = counties.get("dallas_tx")
    if rec is None:
        w("UNAVAILABLE\n")
    else:
        w(f"NRI version {rec.nri_version}.\n")
        w(
            "| Hazard | AFREQ (/yr) | Events in record | Status | EAL rating | Risk rating (context) |"
        )
        w("|---|---|---|---|---|---|")
        for h, v in rec.hazards.items():
            w(f"| {h.name} | {_fmt_freq(v.annualized_frequency)} | {_fmt_freq(v.events)} | "
              f"{v.status.value} | {v.eal_rating} | {v.risk_rating} |")  # fmt: skip
        dfw = noaa.get("dallas_tx")
        if dfw:
            w(f"\nDFW station {start.year}–{end.year}: TMAX reported "
              f"{dfw.coverage(ClimateElement.TMAX).reported_days}/{dfw.coverage(ClimateElement.TMAX).expected_days} days "
              f"(heat indicators), WSF5 reported {dfw.coverage(ClimateElement.WIND_GUST_MAX).reported_days} days.")  # fmt: skip
    w("")

    # ---- summary
    w("## Summary\n")
    w(f"- Data freshness observed: {dict(sorted(freshness_seen.items()))}")
    w(f"- Failures: {len(failures)}")
    for f in failures:
        w(f"  - {f}")
    w(f"- Duration: {(datetime.now(UTC) - started).total_seconds():.1f} s")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="weather-risk")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hubs")
    sub.add_parser("build-snapshot")
    sub.add_parser("verify-snapshot")
    sc = sub.add_parser("scenarios", help="Phase 2: run the 4 assignment scenarios (no LLM)")
    sc.add_argument("--offline", action="store_true", help="cache/snapshot only; no network")
    sc.add_argument("--out", type=Path, default=None, help="write markdown report to this path")
    v = sub.add_parser("validate-data")
    v.add_argument("--offline", action="store_true", help="cache/snapshot only; no network")
    v.add_argument("--out", type=Path, default=None, help="write markdown report to this path")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(
        settings.log_level if args.cmd not in ("validate-data", "scenarios") else "WARNING"
    )
    catalog = load_catalog(settings.hubs_path)

    if args.cmd == "hubs":
        print("ILLUSTRATIVE hub catalog (not actual company facilities)")
        for h in catalog.hubs:
            print(f"{h.id:16s} {h.region:8s} {h.noaa_station.id} {h.hazard_county.fips} "
                  f"{h.display_name}")  # fmt: skip
        return 0
    if args.cmd == "build-snapshot":
        path = build_snapshot(settings, catalog)
        print(f"snapshot written: {path} ({len(SnapshotStore(settings.snapshot_dir))} entries)")
        return 0
    if args.cmd == "verify-snapshot":
        store = SnapshotStore(settings.snapshot_dir)
        problems = store.verify()
        print(f"{len(store)} entries; problems: {problems or 'none'}")
        return 1 if problems else 0
    if args.cmd == "scenarios":
        from weather_risk.analytics.config import load_scoring_config
        from weather_risk.analytics.engine import AnalyticsEngine
        from weather_risk.analytics.report import render_scenarios

        repo = build_repository(settings.model_copy(update={"offline": args.offline}))
        engine = AnalyticsEngine(
            repo, catalog, load_scoring_config(PROJECT_ROOT / "config" / "scoring.yaml")
        )
        report = render_scenarios(engine, offline=args.offline)
        if args.out:
            out = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out
            out.write_text(report)
            print(f"wrote {out}")
        else:
            print(report)
        return 0
    if args.cmd == "validate-data":
        s = settings.model_copy(update={"offline": args.offline})
        repo = build_repository(s)
        report = validate_data(repo, catalog)
        if args.out:
            out = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out
            out.write_text(report)
            print(f"wrote {out}")
        else:
            print(report)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "build_snapshot", "validate_data", "Freshness"]
