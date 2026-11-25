# Phase 2 Report: Deterministic Risk Engine

**Date:** 2026-11-25 · **Branch:** `phase-2-risk-engine` (from `main` at merge `8ade76d`) · **Status:** complete, awaiting review. Phase 3 has not started.

## 1. Implementation summary
A fully deterministic analytics and **Weather Hazard Exposure Index** engine (methodology `1.0.0`) on top of the Phase 1 data layer. It needs no LLM, API or frontend. It answers the analytical part of all four assignment scenarios, offline from the committed snapshot.

| Component | File | Role |
|---|---|---|
| Scoring config | `config/scoring.yaml`, `analytics/config.py` | Anchors, thresholds, indicator and hazard weights, coverage policy, bands, version. Validated at load. |
| Periods | `analytics/periods.py` | `last year`, `YYYY`, `YYYY-YYYY`, `last N years`, `trailing 12 months`, `climatology`. Leap-aware; future and partial years rejected. |
| Statistics | `analytics/stats.py` | Measurable and trace-inclusive snow days, heavy-snow, freezing and extreme-heat days. Expected/valid/missing/excluded counts, quality-flag exclusion with reasons, 90% coverage gate, annual averages. |
| Percentiles | `analytics/percentiles.py` | Per-hazard national mid-rank percentiles of NRI AFREQ (rules in §4) |
| Scoring | `analytics/scoring.py` | Pure indicator → hazard → overall aggregation with contributions; partial and unavailable policy |
| Engine | `analytics/engine.py` | `get_weather_stat`, `get_hub_profile`, `rank_hubs`, `compare_hubs`, `explain_hub_score`; hub, region, hazard and period resolution |
| Contracts | `analytics/models.py` | Typed results with stable `Fact` ids, units, sources, periods, coverage, contributions, assumptions, limitations, methodology version |
| Report and CLI | `analytics/report.py`, `weather-risk scenarios`, `make scenarios` | Generates `docs/PHASE_2_VALIDATION.md` from real outputs |

FEMA frequencies are always labeled *"NRI December 2025, hazard-specific period of record"*. They are never presented as specific to a user-selected year.

## 2. Actual scenario results
Generated offline from the snapshot, with methodology 1.0.0 and NRI December 2025. Full output is in [PHASE_2_VALIDATION.md](PHASE_2_VALIDATION.md).

**1. Midwest winter ranking.** Annual averages are for 2016–2025. "NRI pctl" is the national percentile score of the FEMA frequency.

| Rank | Hub | Winter score | Snow days/yr | Freezing days/yr | NRI pctl: winter weather / ice storm / cold wave |
|---|---|---|---|---|---|
| 1 | Minneapolis | **67.5** | 34.4 | 143.1 | 79.7 / 42.8 / 93.0 |
| 2 | Detroit | **64.7** | 36.1 | 113.7 | 52.0 / **98.4** / 66.4 |
| 3 | Chicago | **55.1** | 26.2 | 107.1 | 72.2 / 49.0 / 79.4 |
| 4 | Columbus | **50.2** | 20.5 | 97.8 | 58.7 / 60.6 / 74.7 |
| 5 | Kansas City | **48.6** | 11.9 | 102.6 | 57.8 / 74.8 / 60.5 |
| 6 | Indianapolis | **47.7** | 16.2 | 99.7 | 51.2 / 64.2 / 69.8 |

**2. Miami vs Houston**
- **Hurricane:** Miami **98.9** vs Houston 91.7. Frequency 0.305/yr vs 0.184/yr.
- **Flood:** Houston **98.0** vs Miami 94.1.
  - Coastal flooding: 3.76/yr vs 2.25/yr.
  - Inland flooding: 5.14/yr vs 4.00/yr.

**3. Denver, calendar year 2025** (NOAA station USW00003017):
- **Measurable snowfall: 7.14%** of days (26 of 364 valid days).
- **Including trace: 12.36%** (45 of 364).
- 365 expected days; 1 missing (2025‑05‑21); 0 quality-excluded; coverage 99.7%.
- Open-Meteo ERA5 gives 9.32% (34 of 365). It is modeled data, reported separately and never mixed with NOAA.

**Miami, insufficient coverage:** for 2016–2025 snowfall, 748 of 3,653 days are valid (20.5%), below the 90% threshold.
- The statistic is withheld (not zero).
- Miami's winter score is therefore `partial` (70% of its weight available), so its overall score is `partial`.
- Miami is listed as **not ranked** in the overall ranking.

**4. Dallas.** Overall **59.7, Moderate**; rank 2 of 11 ranked hubs.
- **Premise "Dallas's risk is High" is not supported** (High starts at 70). Weights and thresholds were not adjusted.
- Drivers, by contribution to the overall score:

| Hazard | Score | Contribution | Main indicators |
|---|---|---|---|
| Severe convective storms | 89.7 | 17.9 | Tornado 96.3, hail 96.9, strong wind 75.8 |
| Extreme heat | 80.9 | 16.2 | 65 days ≥ 95 °F per year; heat-wave percentile 96.7 |
| Hurricane | 50.8 | 10.2 | Frequency 0.0115/yr — see limitation 1 |
| Flood | 48.9 | 9.8 | Inland 97.8; coastal not applicable (scored 0) |
| Winter | 28.3 | 5.7 | Ice storm percentile 88.2 is the notable driver |

## 3. Overall and per-hazard scores (12 hubs)
| Rank | Hub | Overall | Band | Winter | Hurricane | Flood | Severe convective | Extreme heat |
|---|---|---|---|---|---|---|---|---|
| 1 | Houston | 68.3 | Moderate | 19.0 | 91.7 | 98.0 | 54.8 | 77.8 |
| 2 | Dallas | 59.7 | Moderate | 28.3 | 50.8 | 48.9 | 89.7 | 80.9 |
| 3 | Chicago | 58.5 | Moderate | 55.1 | 40.4 | 93.7 | 85.1 | 18.1 |
| 4 | Detroit | 57.2 | Moderate | 64.7 | 48.9 | 91.3 | 56.8 | 24.4 |
| 5 | Memphis | 51.7 | Moderate | 33.0 | 64.2 | 49.2 | 49.7 | 62.1 |
| 6 | Kansas City | 46.3 | Moderate | 48.6 | 0.0 | 48.7 | 83.5 | 50.4 |
| 7 | Atlanta | 45.3 | Moderate | 26.5 | 71.5 | 44.9 | 64.3 | 19.2 |
| 8 | Indianapolis | 44.2 | Moderate | 47.7 | 37.0 | 45.6 | 66.5 | 24.1 |
| 9 | Minneapolis | 43.2 | Moderate | 67.5 | 0.0 | 34.5 | 79.2 | 35.0 |
| 10 | Columbus | 39.2 | Low | 50.2 | 31.3 | 47.3 | 43.9 | 23.5 |
| 11 | Denver | 28.1 | Low | 51.1 | 0.0 | 20.9 | 49.2 | 19.4 |
| — | Miami | 55.5 (partial, not ranked) | Moderate | 6.5\* | 98.9 | 94.1 | 42.3 | 35.4 |

\* Partial: the snow indicators are unavailable because coverage is too low.

## 4. Formulas, weights and policies
These are summarized here; the full method is in [SCORING_METHODOLOGY.md](SCORING_METHODOLOGY.md).

**Formulas:**
- Climate indicator: `s = 100·clip((x−low)/(high−low), 0, 1)`.
- FEMA indicator, positive frequency: `s = 100·(Z + L + ½E)/N`.
  - N = eligible counties (50 states + DC, minus territories and insufficient/unknown records).
  - Z = no-exposure counties (observed-zero or not-applicable).
  - L = eligible positive values below; E = equal values (ties share the mid-rank).
- FEMA indicator in the no-exposure tier: 0.
- Hazard: `H = Σ w·s / Σ w` over available indicators; requires ≥ 60% of the weight.
- Overall: `O = Σ 0.2·H` over the five hazards.
- Every score is bounded to 0–100.

**Anchors:**

| Indicator | Scored 0 at | Scored 100 at |
|---|---|---|
| Snow days/yr | 0 | 60 |
| Heavy-snow days/yr (≥ 4 in) | 0 | 6 |
| Freezing days/yr | 0 | 180 |
| Days ≥ 95 °F per year | 0 | 100 |

**Weights within each hazard:**

| Hazard | Indicator weights |
|---|---|
| Winter | Snow 0.2, heavy snow 0.1, freezing 0.2, FEMA winter weather 0.2, ice storm 0.2, cold wave 0.1 |
| Hurricane | FEMA hurricane 1.0 |
| Flood | Coastal 0.5, inland 0.5 |
| Severe convective | Tornado, hail and strong wind, ⅓ each |
| Extreme heat | Hot days 0.5, FEMA heat wave 0.5 |

Bands: Low < 40 ≤ Moderate < 70 ≤ High.

**Missing data and "not applicable":**
- **Not applicable** scores 0 and keeps its weight, so dropping it can't inflate a score.
- **Insufficient data or unknown** is never treated as 0; it makes the hazard partial or unavailable.
- **An unavailable hazard** makes the overall score unavailable.
- **A partial overall score** is reported but not ranked.
- **Rankings** require one FEMA version, one climate source and one climate period. Exact ties share a rank and are listed by hub ID.

## 5. Deviations from the Phase 0 plan
1. **FEMA "not applicable" counties stay in the national reference set** as a no-exposure tier (D-015). The Phase 0 addendum had excluded them. FEMA defines "not applicable" as known absence of risk, and excluding these counties would distort percentiles. For example, it would compare Dallas's hurricane frequency only with coastal-adjacent counties.
2. **No separate "confidence" label** (per your refinement). Results carry data completeness (coverage numbers and status) plus fixed methodology caveats.
3. **Severe convective storms and flood use FEMA frequencies only.** No station-wind or rainfall proxies are used, deliberately.

## 6. Test commands and results (2026-11-25)
| Command | Result |
|---|---|
| `uv run pytest` (offline, default) | **214 passed**, 6 deselected (136 from Phase 1 + 78 new) |
| `uv run pytest -m live` | **6 passed** (Phase 1 live suite, unchanged) |
| `uv run ruff check src tests scripts` / `ruff format --check` | All checks passed / 43 files formatted |
| Fresh `git clone` → `uv sync --frozen` → `pytest` | 214 passed; scenarios reproduce identically |
| `make scenarios` with HTTP(S) routed to a dead proxy and an empty cache | Output identical to the committed report; 0 HTTP attempts logged; served from the snapshot |

**What the new tests cover:**
- **Statistics:** hand-computed denominators (missing, quality-excluded, valid); measurable vs trace; heavy snow; freezing including 0 °C and negatives; heat threshold included; coverage gate; all-missing never zero; leap-year and multi-year annual averages computed independently; Open-Meteo kept separate.
- **Periods:** 10 resolution cases, including leap-day trailing windows; 8 unsupported cases.
- **Percentiles:** hand-computed mid-rank values with ties; zeros and "not applicable" give 0; insufficient/unknown are unavailable; territory exclusion; a mass of zeros doesn't inflate; version mismatch.
- **Anchors and scoring:** clipping; a full hub score computed by hand; contributions sum to scores; not-applicable kept in the denominator; partial renormalization; unavailable hazard → overall unavailable; bounds; bands; 10 invalid-config cases.
- **Engine, against the real snapshot:**
  - Denver 2025 percentages equal counts made **directly from the raw snapshot JSON**.
  - The Minneapolis snow indicator is recomputed from raw rows.
  - Miami/Houston frequencies match the raw FEMA records, and the leader follows the raw values.
  - Miami's insufficient-coverage path; the Midwest ranking; the Dallas premise check (threshold derived from config) and contribution sum.
  - All 12 hubs bounded; deterministic ordering; repeatable across fresh engines.
  - Unsupported hubs, hazards, regions, periods and metrics rejected; version-mismatch fallback; report rendering.

## 7. Limitations and unresolved issues
1. **Percentile compression near zero (D-021, needs your decision).**
   - A tiny but positive FEMA frequency ranks above about 870 no-exposure counties and scores mid-range. Hurricane examples: Dallas (about one event per 87 years) scores 50.8; Chicago 40.4; Detroit 48.9.
   - For coastal flooding, 2,644 not-applicable counties put every coastal county at about 85 or higher.
   - For Dallas, the hurricane indicator is the single largest contributor to the overall score (10.2 points).
   - The validation report includes a diagnostic table. Options: (a) keep and disclose (current); (b) blend with an absolute log-scale anchor; (c) set a minimum material frequency.
2. **Partial hubs are excluded from overall rankings.** Miami, the strongest hurricane exposure in the catalog, is therefore absent from the overall ranking, though shown with its partial score. Setting `rank_partial_results: true` would include it, flagged.
3. **Weights and anchors are judgment calls**, and equal hazard weights strongly shape the overall ranking. The engine does not yet accept custom weights per request; Phase 3 could add that as a deterministic parameter.
4. **The climate window is 10 years**, short for rare heavy-snow events. FEMA periods of record differ by hazard.
5. **Exposure is not operational risk.** The index has no vulnerability, redundancy or cost dimension.
6. **Sources not yet used:** NOAA wind, precipitation and Storm Events data.
7. **AI session file.** An `ai-session` export (94 KB, untracked) sits at the repo root. My scan found no API keys or email addresses. It's not committed yet; it should move to `docs/ai-session/` after your review, together with the Phase 2 export.

## 8. Commits
| Hash | Message |
|---|---|
| `8ade76d` | Merge branch 'phase-1-data-layer' (on `main`, preserves all Phase 1 commits) |
| `2de7df5` | feat(analytics): scoring config, period resolution and historical day-count statistics |
| `808481d` | feat(analytics): national percentiles, hazard/overall scoring and analytics engine |
| `218bad4` | test(analytics): hand-computed unit tests and snapshot-based scenario tests |
| `92228ae` | feat(cli): scenarios command rendering the four assignment scenarios and score table |
| `88663b9` | docs: scoring methodology, Phase 2 decisions and generated scenario validation |
| (this commit) | docs: Phase 2 report |

Nothing has been pushed; there is no remote. `ASSIGNMENT.pdf` remains untracked.

## 9. Readiness for Phase 3
Phase 2 is **ready.**
- The five engine interfaces are typed, deterministic and fact-addressable. They map one-to-one onto the planned LLM tools.
- `Fact` ids support deterministic rendering of critical numbers (D-012).
- The premise check gives the agent a grounded way to push back on false premises such as "Dallas is high".

Inputs Phase 3 needs from you:
- a `GEMINI_API_KEY` in your local `.env`;
- a decision on D-021 (percentile compression), or approval to keep v1.0.0 as is;
- whether partial hubs should be rankable with a flag.
