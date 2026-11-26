# Phase 2 Report: Deterministic Risk Engine

**Date:** 2026-11-25 · **Branch:** `phase-2-risk-engine` (from `main` at merge `8ade76d`) · **Status:** complete, including the review refinement (methodology **1.1.0**). Phase 3 has not started.

> **Refinement after review (methodology 1.1.0):**
> - FEMA frequencies now use a hybrid of national percentile and absolute log-frequency (D-022).
> - Explanations now separate hazard-level from indicator-level contributions (D-023). This corrects an earlier statement in this report.
> - Ranking eligibility is explicit per scope (D-024).
> - The AI session export is placed in the repo (D-025).
>
> §2–§4 show v1.1.0 results; v1.0.0 → v1.1.0 comparisons are in §2a and [SCORING_METHODOLOGY.md §6](SCORING_METHODOLOGY.md).

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

## 2. Actual scenario results (methodology 1.1.0)
Generated offline from the snapshot, NRI December 2025. Full output is in [PHASE_2_VALIDATION.md](PHASE_2_VALIDATION.md).

**1. Midwest winter ranking.** The order is unchanged from v1.0.0.

| Rank | Hub | Winter score (v1.0.0 → v1.1.0) |
|---|---|---|
| 1 | Minneapolis | 67.5 → **74.0** |
| 2 | Detroit | 64.7 → **71.4** |
| 3 | Chicago | 55.1 → **62.9** |
| 4 | Columbus | 50.2 → **58.8** |
| 5 | Kansas City | 48.6 → **57.2** |
| 6 | Indianapolis | 47.7 → **57.1** |

**2. Miami vs Houston**
- **Hurricane:** Miami **86.6** vs Houston 77.4. Frequency 0.305/yr vs 0.184/yr.
- **Flood:** Houston **99.0** vs Miami 97.0.
  - Coastal flooding: 98.8 vs 95.9.
  - Inland flooding: 99.2 vs 98.2.
- Same leaders as in v1.0.0.

**3. Denver, calendar year 2025.** Unaffected by the change.
- Measurable snow: **7.14%** of days (26 of 364 valid).
- Including trace: **12.36%** (45 of 364).
- 1 missing day (2025‑05‑21); coverage 99.7%.

**Miami, insufficient coverage:** 20.5% valid snow observations.
- The statistic is withheld; the winter hazard is partial; the overall score (61.3) is partial and **not ranked overall**.
- Miami **is ranked** #1 for hurricane and #2 for flood, with explicit reasons recorded (D-024).

**4. Dallas.** Overall **58.7, Moderate**; rank 2 of 11 ranked hubs.
- **Premise "Dallas's risk is High" is not supported.**
- **Primary driver: severe convective storms.** Hazard contributions to the overall score:

| Hazard | Score | Contribution |
|---|---|---|
| Severe convective storms | 94.6 | 18.9 |
| Extreme heat | 81.7 | 16.3 |
| Flood | 49.4 | 9.9 |
| Winter | 40.6 | 8.1 |
| Hurricane | 27.0 | 5.4 |

### 2a. v1.0.0 → v1.1.0: key indicators
| Indicator | Frequency | v1.0.0 | v1.1.0 |
|---|---|---|---|
| Dallas hurricane | 0.0115/yr (≈ 1 per 87 yr) | 50.8 | **27.0** |
| Chicago hurricane | 0.0093/yr | 40.4 | 20.2 |
| Miami hurricane | 0.305/yr | 98.9 | 86.6 |
| Houston hurricane | 0.184/yr | 91.7 | 77.4 |
| Chicago coastal flooding | 0.012/yr | 88.3 | **46.2** |
| Miami coastal flooding | 2.25/yr | 91.7 | 95.9 |
| Houston coastal flooding | 3.76/yr | 97.6 | 98.8 |

## 3. Overall and per-hazard scores (12 hubs, v1.1.0)
| Rank | Hub | Overall | Band | Winter | Hurricane | Flood | Severe convective | Extreme heat |
|---|---|---|---|---|---|---|---|---|
| 1 | Houston | 73.6 | High | 34.0 | 77.4 | 99.0 | 77.4 | 80.1 |
| 2 | Dallas | 58.7 | Moderate | 40.6 | 27.0 | 49.4 | 94.6 | 81.7 |
| 3 | Chicago | 56.7 | Moderate | 62.9 | 20.2 | 72.9 | 92.6 | 34.8 |
| 4 | Detroit | 56.2 | Moderate | 71.4 | 25.4 | 72.7 | 73.8 | 37.6 |
| 5 | Memphis | 54.0 | Moderate | 44.4 | 41.4 | 49.6 | 72.4 | 62.4 |
| 6 | Atlanta | 50.7 | Moderate | 39.7 | 50.3 | 47.5 | 78.2 | 37.8 |
| 7 | Kansas City | 49.5 | Moderate | 57.2 | 0.0 | 49.4 | 88.3 | 52.6 |
| 8 | Minneapolis | 49.3 | Moderate | 74.0 | 0.0 | 42.3 | 86.8 | 43.4 |
| 9 | Indianapolis | 47.9 | Moderate | 57.1 | 18.5 | 47.8 | 79.0 | 37.2 |
| 10 | Columbus | 45.6 | Moderate | 58.8 | 15.6 | 48.6 | 67.4 | 37.2 |
| 11 | Denver | 40.0 | Low | 56.6 | 0.0 | 34.4 | 67.9 | 40.9 |
| — | Miami | 61.3 (partial, not ranked) | Moderate | 10.4\* | 86.6 | 97.0 | 68.1 | 44.7 |

\* Partial: the snow indicators are unavailable because coverage is too low.

The v1.0.0 overall scores and ranks are in [SCORING_METHODOLOGY.md §6](SCORING_METHODOLOGY.md). Only two adjacent pairs swapped: Atlanta/Kansas City and Minneapolis/Indianapolis.

## 4. Formulas, weights and policies
These are summarized here; the full method is in [SCORING_METHODOLOGY.md](SCORING_METHODOLOGY.md).

**Formulas:**
- Climate indicator: `s = 100·clip((x−low)/(high−low), 0, 1)`.
- FEMA indicator, positive frequency (v1.1.0): `s = ½·s_rel + ½·s_abs`.
  - `s_rel = 100·(Z + L + ½E)/N`
  - `s_abs = 100·clip(log10(x/0.01)/2, 0, 1)`, so 1-in-100 years scores 0 and once a year scores 100.
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

**Ranking eligibility:** each hub and scope gets an explicit eligible flag and reason. Hazard rankings include every hub whose hazard is complete.

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
| `uv run pytest` (offline, default) | **227 passed**, 6 deselected (136 from Phase 1 + 91 Phase 2, including 13 refinement tests) |
| `uv run pytest -m live` | **6 passed** (Phase 1 live suite, unchanged) |
| `uv run ruff check src tests scripts` / `ruff format --check` | All checks passed / 44 files formatted |
| Fresh `git clone` → `uv sync --frozen` → `pytest` | 214 passed; scenarios reproduce identically |
| `make scenarios` with HTTP(S) routed to a dead proxy and an empty cache (re-run on v1.1.0) | Output identical to the committed report; 0 HTTP attempts logged; served from the snapshot |
| `uv run python scripts/sensitivity.py --out docs/PHASE_2_SENSITIVITY.md` | Methods A, B and C compared for all 12 hubs (offline) |

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
1. **FEMA scores are relative and absolute *frequency*, not event likelihood or severity** (D-022).
   - The hybrid reduces near-zero compression (Dallas hurricane 27.0) but keeps a positive score for every real exposure.
   - Its absolute half saturates for hazards that occur at least yearly, which lifted overall levels; Houston is now in the High band.
   - Anchors are a single return-period rule, not hazard-specific severity anchors.
   - **Correction:** an earlier version of this report called Dallas's hurricane indicator "the single largest contributor to the overall score". It was the largest *single indicator* (because hurricane has only one indicator), but third at hazard level. Fixed in D-023, with regression tests.
2. **Partial hubs are excluded from the default overall ranking only** (shown with their score and reason). Miami is ranked in the hurricane and flood rankings.
3. **Weights and anchors are judgment calls**, and equal hazard weights strongly shape the overall ranking. The engine does not yet accept custom weights per request; Phase 3 could add that as a deterministic parameter.
4. **The climate window is 10 years**, short for rare heavy-snow events. FEMA periods of record differ by hazard.
5. **Exposure is not operational risk.** The index has no vulnerability, redundancy or cost dimension.
6. **Sources not yet used:** NOAA wind, precipitation and Storm Events data.
7. **AI session.** The Phases 0–1 export is now `docs/ai-session/session-phase-0-1.txt` (*later removed from the public repository and delivered privately; see D-046*); it was reviewed, needed no redactions, and is unmodified. **Security:** a real-looking Gemini key was typed into the tracked `.env.example`. It was never staged or committed, but it now appears in this session's transcript. Rotate the key, move it to `.env`, restore the placeholder, and redact it from the next export (D-025).

## 8. Commits
| Hash | Message |
|---|---|
| `8ade76d` | Merge branch 'phase-1-data-layer' (on `main`, preserves all Phase 1 commits) |
| `2de7df5` | feat(analytics): scoring config, period resolution and historical day-count statistics |
| `808481d` | feat(analytics): national percentiles, hazard/overall scoring and analytics engine |
| `218bad4` | test(analytics): hand-computed unit tests and snapshot-based scenario tests |
| `92228ae` | feat(cli): scenarios command rendering the four assignment scenarios and score table |
| `88663b9` | docs: scoring methodology, Phase 2 decisions and generated scenario validation |
| `afa9d5e` | docs: Phase 2 report |
| `d50aca6` | feat(analytics): methodology 1.1.0 hybrid FEMA normalization, explicit contribution levels and ranking eligibility |
| `ad36d96` | docs: methodology 1.1.0, sensitivity analysis, updated validation and Phase 2 report; add reviewed AI session export (phases 0-1) |
| (this commit) | docs: record refinement commit hashes |

Nothing has been pushed; there is no remote. `ASSIGNMENT.pdf` remains untracked.

## 9. Readiness for Phase 3
Phase 2 is **ready.**
- The five engine interfaces are typed, deterministic and fact-addressable. They map one-to-one onto the planned LLM tools.
- `Fact` ids support deterministic rendering of critical numbers (D-012).
- The premise check gives the agent a grounded way to push back on false premises such as "Dallas is high".

Inputs Phase 3 needs from you:
- a **rotated** `GEMINI_API_KEY` in your local `.env` (not `.env.example`);
- approval of methodology 1.1.0.
