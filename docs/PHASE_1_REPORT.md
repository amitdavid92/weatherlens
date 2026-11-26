# Phase 1 Report: Foundation and Data Layer

**Date:** 2026-11-25 · **Branch:** `phase-1-data-layer` · **Status:** complete, awaiting review. Phase 2 has not started.

## 1. Implementation summary
Phase 1 delivers a tested, reproducible data layer that retrieves every input needed for the four assignment scenarios, for all 12 illustrative hubs.

- **Three independent adapters:**
  - NOAA GHCN-Daily (primary, observed);
  - Open-Meteo ERA5 (alternative, labeled as modeled);
  - FEMA NRI (county hazard frequencies plus the national reference table).

  Source-specific parsing is isolated in each adapter.
- **Typed contracts** keep missing data, observed zero, trace, not applicable, insufficient data and unknown as separate states throughout. Nothing is coerced.
- **SQLite raw-response cache** with a committed, hash-verified **snapshot** fallback. The fallback order is fresh cache, live fetch, stale cache, snapshot, then a typed `DataUnavailableError`.
- **CLI** for catalog listing, snapshot build and verification, and live/offline validation.
- **Offline test suite** (136 tests on real recorded fixtures) and an opt-in **live suite** (6 tests).
- **Not built yet:** scoring engine, LLM agent, API, frontend and bonus features.

## 2. Files and components created
| Path | Purpose |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | Python 3.12, reproducible install. Runtime deps: httpx, pydantic, pydantic-settings, pyyaml. Dev deps: pytest, respx, ruff. |
| `config/hubs.yaml` | Illustrative 12-hub catalog with verified stations and counties, aliases and assumptions |
| `src/weather_risk/catalog.py` | Catalog validation; strict resolver (exact match only; `UnsupportedHubError` with suggestions; `AmbiguousHubError` for states and regions) |
| `src/weather_risk/config.py` | Settings from env/`.env`; `GEMINI_API_KEY` as `SecretStr` (declared, unused) |
| `src/weather_risk/logging_setup.py` | JSON-lines structured logging |
| `src/weather_risk/data/models.py` | Provenance, ObservationStatus, ClimateDataset, CoverageReport, HazardStatus, HazardValue, CountyHazardRecord, HazardReferencePopulation, snapshot/cache metadata |
| `src/weather_risk/data/errors.py` | Typed errors: timeout, rate-limited, HTTP, invalid response, version mismatch, data unavailable, unsupported or ambiguous hub |
| `src/weather_risk/data/http.py` | `SourceRequest` (deterministic key); httpx fetcher with timeouts, bounded exponential backoff and capped Retry-After |
| `src/weather_risk/data/cache.py` | SQLite raw-body cache with integrity hash, TTL and eviction of corrupt entries |
| `src/weather_risk/data/adapters/noaa_ghcn.py` | NCEI ADS `daily-summaries`, metric units, M/Q/S flags, per-element status rules |
| `src/weather_risk/data/adapters/open_meteo.py` | Archive API with `models=era5` pinned, explicit units validated, cm→mm conversion |
| `src/weather_risk/data/adapters/fema_nri.py` | Count, paged national table, county query; status derivation; single-version enforcement |
| `src/weather_risk/data/repository.py` | Fallback chain; calendar-year chunking; `get_county_with_reference` version guard |
| `src/weather_risk/data/snapshot.py` | Deterministic gzip snapshot writer and reader, manifest, verification |
| `src/weather_risk/data/periods.py` | Date ranges, leap years, canonical year chunks, last completed year |
| `src/weather_risk/cli.py` | `weather-risk hubs | build-snapshot | verify-snapshot | validate-data [--offline]` |
| `data/snapshot/` | 255 raw responses (2.9 MB) plus `manifest.json` |
| `tests/unit/*`, `tests/fixtures/*` | Offline tests; fixtures are **real** recorded responses (`scripts/record_fixtures.py`) |
| `tests/integration/test_live_sources.py` | Opt-in live tests (`-m live`) |
| `Makefile`, `README.md`, `.env.example`, `.gitignore` | Developer commands, setup, no credentials |
| `docs/PHASE_0_PLAN.md`, `docs/DECISIONS.md`, `docs/ai-session/README.md` | Approved plan, decision log (D-001…D-013), session export procedure |
| `docs/PHASE_1_VALIDATION.md` | Generated live validation report (§4–§6 below summarise it) |

## 3. Technical decisions and deviations
All decisions are logged in [DECISIONS.md](DECISIONS.md). The notable ones:

- **NRI status uses the EAL rating (`*_EALR`), not `*_RISKR`** (D-006).
  - This refines the Phase 0 Addendum, which used `RISKR`.
  - The FEMA technical documentation (Dec 2025 v1.20, §3.2 Table 2) shows that the Risk Index rating also depends on social-vulnerability and resilience data.
  - `EALR` maps one-to-one onto the frequency states across all 3,232 records and 10 hazards. Zero combinations become `unknown`.
- **Official FEMA definitions were obtained.** The PDF (15 MB) was downloaded to the scratchpad and its text extracted with a throwaway `pypdf` that was not added to the project.
  - Remaining inference: the documentation defines the labels but doesn't explicitly tie a null AFREQ to them. That link is empirical and held for 100% of records; it is documented as a limitation.
- **Open-Meteo `models=era5` pinned** (D-003).
  - **Reconciles with Phase 0:** Denver 2025 has 43 days with snowfall > 0 under the default `best_match` (Phase 0) and 34 under `era5` (now).
- **Climate requests are split into calendar-year chunks**, so cache and snapshot entries serve any sub-range. Assembled datasets keep the provenance of each chunk in `components`.
- **The cache and snapshot store raw response bodies**, not parsed objects. Fallback data runs through the same parsers and validation as live data.
- **NRI page size is read at call time.** A test caught a bug where the default argument was frozen at import time, so the configured page size was ignored.
- **Per-hazard exclusion matters inside the 50-state reference set.** 30 Alaska counties are `insufficient_data` for heat wave and 143 counties are `not_applicable` for ice storm. Phase 2 excludes them from those hazards' denominators (D-007).
- **Deviation:** the plan listed `structlog`. The stdlib JSON formatter is used instead, to avoid an extra dependency.
- **Deviation:** FastAPI is not installed yet; it comes in Phase 3, as planned.
- **Git author** is repo-local: `Amit David <72254985+amitdavid92@users.noreply.github.com>`, as you chose.
- **`ASSIGNMENT.pdf` is deliberately not committed.** It's Moveo's document; tell me if you want it in the repo.

## 4. Live data validation: all 12 hubs
Source: `docs/PHASE_1_VALIDATION.md`, generated by `make validate-data` at 2026-11-25T10:47Z.
- **Failures:** 0.
- **Freshness:** 36 datasets live, plus 1 snapshot fallback (see §7).

The NOAA columns show the share of days with a reported value, 2016–2025.

| Hub | Station (station county) | Hazard county | SNOW | TMIN/TMAX | PRCP | Open-Meteo | NRI ver. = reference |
|---|---|---|---|---|---|---|---|
| chicago_il | USW00094846 (DuPage ⚠︎) | Cook 17031 | 100% | 100% | 100% | 100% | yes |
| indianapolis_in | USW00093819 | Marion 18097 | 100% | 100% | 100% | 100% | yes |
| columbus_oh | USW00014821 | Franklin 39049 | 100% | 100% | 100% | 100% | yes |
| detroit_mi | USW00094847 | Wayne 26163 | 100% | 100% | 100% | 100% | yes |
| minneapolis_mn | USW00014922 | Hennepin 27053 | 100% | 100% | 100% | 100% | yes |
| kansas_city_mo | USW00003947 (Platte ⚠︎) | Jackson 29095 | 99.9% | 100% | 100% | 100% | yes |
| denver_co | USW00003017 | Denver 08031 | 100% | 100% | 100% | 100% | yes |
| dallas_tx | USW00003927 | Dallas 48113 | 100% | 100% | 99.9% | 100% | yes |
| houston_tx | USW00012960 | Harris 48201 | 100% | 100% | 100% | 100% | yes |
| **miami_fl** | USW00012839 | Miami-Dade 12086 | **20.5%** | 100% | 100% | 100% | yes |
| atlanta_ga | USW00013874 (Clayton ⚠︎) | Fulton 13121 | 99.6% | 100% | 100% | 100% | yes |
| memphis_tn | USW00013893 | Shelby 47157 | 100% | 100% | 100% | 100% | yes |

Every hub county has 10 NRI hazard records with no `unknown` statuses. ⚠︎ marks a station county that differs from the hazard county; each one is documented as a hub assumption.

**Verification methods:**
- **Stations:** `ghcnd-stations.txt` and `ghcnd-inventory.txt`.
- **Station counties:** FCC Census Area API (2020).
- **City reference points:** Open-Meteo geocoding. Each point falls inside its hazard county (checked with the FCC API).

## 5. Data availability for the four assignment scenarios
1. **Midwest winter:** available for all 6 Midwest hubs.
   - NOAA 2016–2025 snowfall split into measured, trace, zero and missing. Missing days: 0 everywhere except Kansas City (2).
   - TMIN reported on 3653/3653 days.
   - NRI frequencies for winter weather, ice storm and cold wave are all `observed`.
2. **Miami vs Houston:** available at the same county resolution, both in NRI December 2025.
   - Hurricane: Miami 0.305/yr (124 events), Houston 0.1836/yr (75 events).
   - Coastal flooding: Miami 2.25/yr, Houston 3.761/yr.
   - Inland flooding: Miami 4.0/yr, Houston 5.143/yr.
   - All six values are `observed`.
3. **Denver 2025 daily snowfall:** available.
   - NOAA: 365 days; measured 26, trace 19, zero 319, missing 1 (2025‑05‑21).
   - Open-Meteo ERA5 (kept separate): measured 34, zero 331, missing 0.
   - The percentage itself is a Phase 2 calculation.
4. **Dallas:** all 10 hazard records are available.
   - Coastal flooding is `not_applicable`; the other 9 are `observed`.
   - Examples: hail 8.922/yr, heat wave 19.11/yr, inland flooding 4.607/yr, ice storm 1.226/yr, tornado 0.9278/yr.
   - The DFW station has TMAX for 3653/3653 days.

These figures are retrieved, not hardcoded; tests assert behaviors and states, not these values. Compared with the Phase 0 research, the NOAA Denver figures match exactly (26 measured, 19 trace, 1 missing), and the NRI values match Phase 0 to its 2-decimal rounding.

## 6. NRI reference population
- **3,232** records returned. The count is validated against `returnCountOnly`, every FIPS is unique and 5 digits, and all records carry one version (**December 2025**). Two pages of 2,000, ordered by `STCOFIPS`.
- **Reference population: 3,144** (50 states + DC).
- **Excluded: 88 territories** (PR 78, AS 3, MP 3, VI 3, GU 1).
- **Statuses within the reference population:**
  - Hurricane: 747 `not_applicable`, 126 `observed_zero`.
  - Coastal flooding: 2,644 `not_applicable`.
  - Ice storm: 143 `not_applicable`.
  - Heat wave: 30 `insufficient_data` (Alaska).
  - `unknown`: 0 for every hazard.

## 7. Cache and snapshot behavior
- **Cache:** `data/cache/cache.db` (gitignored).
  - TTLs: 30 days for completed periods, 1 day for the last 30 days, 7 days for NRI.
  - A response is validated before it is cached, so invalid live responses are never cached.
  - Corrupt entries (hash mismatch) are evicted and refetched.
  - Measured: the second request for Denver 2025 came from cache, with no HTTP call.
- **Snapshot:** 255 gzip files (2.9 MB).
  - NOAA: 12 stations × 2016–2025.
  - Open-Meteo: 12 hubs × 2016–2025.
  - NRI: 12 counties, the count and 2 national pages.
  - `manifest.json` records params, retrieval time, period, version, sha256 and licenses. `make verify-snapshot` reports 255 entries and no problems.
  - The gzip output is byte-deterministic (tested).
  - NOAA and FEMA data are public domain; Open-Meteo is CC BY 4.0 with attribution, so everything is redistributable.
- **Observed real fallback:** right after the snapshot build, Open-Meteo returned HTTP 429 and TLS timeouts during the live validation. The client retried with backoff. For Atlanta 2025 the retries ran out, and the repository served the snapshot, labeled `snapshot`.
- **Offline proof:** `validate-data --offline` from an **empty** cache served all 37 datasets from the snapshot in 2.4 s with 0 failures. Its content was identical to the live report apart from freshness labels.

## 8. Test commands and actual results
| Command | Result (2026-11-25) |
|---|---|
| `uv run pytest` (= `make test`, offline, default) | **136 passed, 6 deselected in 0.20 s** |
| `uv run pytest -m live` (= `make test-live`) | **6 passed in 17.21 s** (real NOAA, Open-Meteo, FEMA) |
| `uv run ruff check src tests scripts` / `ruff format --check` | All checks passed / 30 files formatted |
| Fresh `git clone` → `uv sync --frozen` → `uv run pytest` | **136 passed** |
| Fresh clone: `verify-snapshot`, then `validate-data --offline` | 255 entries, no problems; 0 failures |
| `make validate-data` | Report written; 0 failures (see §4) |

**What the offline tests cover:**
- Catalog: aliases, unsupported names, typo suggestions, ambiguous state/region names, duplicate aliases, numeric FIPS, region/state mismatch, the illustrative flag, station IDs.
- NOAA:
  - parsing; trace vs measurable; missing keys; absent dates;
  - negative and **0 °C** temperatures as measurements; leap day;
  - Miami unreported snow; quality flags;
  - 8 kinds of invalid response; station and range validation.
- Open-Meteo: units cm→mm with the original kept; null vs zero; unit mismatch; 6 kinds of invalid payload; model and unit parameters pinned.
- NRI:
  - real observed-zero, not-applicable and insufficient-data records (Guam, Alaska, an Arizona county);
  - 12-case status table;
  - pagination; count mismatch; duplicate FIPS; mixed versions; county-vs-reference version check;
  - territory exclusion; invalid records; ArcGIS error and HTML responses; FIPS mismatch.
- HTTP: 5xx retry with backoff; timeouts bounded; 429 with capped Retry-After; 4xx not retried; transport errors; key determinism.
- Cache: hit, miss, expiry, corruption, replacement.
- Repository:
  - cache hit avoids a second call; multi-year chunks; 366-day leap year;
  - invalid responses not cached; stale fallback; refresh of expired entries;
  - snapshot fallback; offline mode; unavailable; corrupt snapshot rejected;
  - NRI pagination and version reconciliation through the repository.
- Snapshot: manifest, hashes, deterministic gzip.

## 9. Known limitations and unresolved issues
1. **NRI null semantics.** The mapping from null AFREQ to the rating label is empirical, not stated in the FEMA documentation (D-006). It holds for 100% of records, and any other combination becomes `unknown`.
2. **Miami SNOW** is reported on only 20.5% of 2016–2025 days. Unreported days stay `missing`. Phase 2 must show low coverage for Miami snow metrics; plausibly zero snow, but that is never assumed.
3. **Open-Meteo rate limits.** Rebuilding the cache from empty for all 12 hubs × 10 years can trigger HTTP 429. Retries and the snapshot cover it, but Phase 2+ should rely mainly on cache and snapshot for bulk climatology. The snapshot builder throttles; `validate-data` does not.
4. **NOAA responses have no dataset version.** Retrieval timestamps are recorded instead. GHCN-Daily can be revised retroactively; the 30-day TTL and the snapshot pin what we used.
5. **Station ≠ hub site.** Airport stations stand in for the hubs, and 3 hubs have a station outside the hazard county. Both are documented per hub.
6. **The policy for excluding quality-flagged values** is deferred to Phase 2. The flags are preserved and counted.
7. **NRI `*_EVNTS` can be fractional** (e.g. Dallas hail 338.9) because NRI apportions events spatially. Values are stored raw and must not be presented as whole-event counts.
8. **The snapshot covers 2016–2025.** Other periods need live access or the cache.
9. **The `validate-data` and `build-snapshot` CLI paths** are verified by real runs, not unit tests.
10. **AI session export is pending.** *(Superseded: the final privacy decision, D-046, is that full transcripts are delivered privately and never committed. See `docs/ai-session/README.md`.)* You need to run `/export` (only the user can) and save it under `docs/ai-session/`. The raw JSONL stays outside the repo until it has been reviewed. Some docs mention a local path containing the macOS username `amitdavid`; this is low-sensitivity and flagged for your review.

## 10. Git commits (branch `phase-1-data-layer`, based on `main`)
| Hash | Message |
|---|---|
| `5a63a84` | chore: project scaffold, Phase 0 plan and decision log (on `main`) |
| `45b522c` | feat(catalog): illustrative 12-hub catalog with verified stations and counties |
| `601912b` | feat(data): NOAA GHCN-Daily, Open-Meteo and FEMA NRI adapters with cache and snapshot fallback |
| `3b77607` | test: offline suite with real recorded fixtures; opt-in live integration tests |
| `6bed789` | feat(cli): hubs, build-snapshot, verify-snapshot and validate-data commands |
| `3d0075a` | data: reproducible snapshot of raw source responses (2016-2025, NRI Dec 2025) |
| (this commit) | docs: Phase 1 report and generated validation |

There are no remotes and nothing has been pushed. The branch is not merged into `main`; that's waiting on your review.

## 11. How to validate the data layer independently
```bash
git clone <repo> && cd moveo-weather-risk && git checkout phase-1-data-layer
uv sync --frozen
make test                    # offline: expect 136 passed
make verify-snapshot         # expect 255 entries; problems: none
make validate-data-offline   # all 12 hubs + 4 scenarios from the snapshot, no network
make test-live               # optional, network: 6 live tests
make validate-data           # optional, network: regenerates docs/PHASE_1_VALIDATION.md
```
To spot-check one source by hand, e.g. Denver 2025 NOAA snow (no token needed):
`https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries&stations=USW00003017&startDate=2025-01-01&endDate=2025-12-31&dataTypes=SNOW&units=metric&format=json&includeAttributes=true`

## 12. Readiness for Phase 2
Phase 1 is **ready.** Every input for all four scenarios is available live and offline, with explicit states and provenance.

Phase 2 (deterministic risk engine) can build on:
- `ClimateDataset.status_counts` and `coverage`;
- `HazardValue.usable_frequency`;
- `HazardReferencePopulation.reference_records` and `status_counts`;
- `get_county_with_reference` (version-safe).

Decisions Phase 2 must make and document:
- the quality-flag exclusion policy;
- the minimum coverage threshold, e.g. for Miami snow;
- how `not_applicable` hazards enter the overall index;
- climate anchor values;
- hazard and indicator weights.
