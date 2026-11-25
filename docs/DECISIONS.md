# Decision Log

Short ADR-style records. Status: **Accepted** unless noted. Dates are 2026-11-25 (Phase 0 and Phase 1).

---

### D-001: Product framing is a "Weather Hazard Exposure Index", not disruption risk
We have no shipment, downtime, asset vulnerability or financial-loss data. The system measures
**weather hazard exposure** at hub locations. It does not measure operational disruption risk.
When a user asks about "disruption risk", the agent reframes the question and says so. If the
premise is not supported by the data, it says so rather than agreeing.

### D-002: Stack
- Python 3.12 managed with uv; `uv.lock` is committed.
- FastAPI and Pydantic (FastAPI arrives in Phase 3).
- pytest for tests.
- Stdlib `sqlite3` for the cache.
- Gemini as the LLM (Phase 3).
- React, TypeScript and Vite for the UI (Phase 4).

Deployment, voice and alerts are deferred until all mandatory requirements are met.

Phase 1 runtime dependencies are only `httpx`, `pydantic`, `pydantic-settings` and `pyyaml`.

### D-003: Data sources
| Role | Source | Why |
|---|---|---|
| Primary climate (observed) | NOAA NCEI Access Data Service, GHCN-Daily `daily-summaries` | Station observations. No token needed (the CDO v2 API does need one). Public domain. |
| Alternative climate (modeled) | Open-Meteo archive, **`models=era5`** pinned | Gap-free reanalysis grid. Labeled `modeled_reanalysis`. Pinned because the `best_match` default blends models and changes daily values; Denver 2025 has 43 vs 34 snowfall > 0 days depending on model. |
| Hazard frequency | FEMA NRI county table via the FEMA-hosted ArcGIS FeatureServer | `hazards.fema.gov` resets connections from our network; the FeatureServer is stable and serves the same release (`NRI_VER` = "December 2025", tech doc v1.20). |
| Not used (yet) | NOAA Storm Events, HURDAT2, NWS alerts | Storm Events logs 43% of rows by forecast zone, so it needs a zone↔county crosswalk. HURDAT2 duplicates what NRI already models. NWS alerts are live-only. |

### D-004: Illustrative 12-hub catalog
The hubs are assumed examples, not company facilities.
- The catalog has 6 Midwest hubs (US Census Bureau region) plus Denver, Dallas, Houston, Miami, Atlanta and Memphis.
- Each hub is represented by:
  - a city reference point (Open-Meteo geocoding);
  - the county containing that point, used for hazard data (verified with the FCC Census Area API);
  - the nearest major-airport GHCN station, used for climate data (verified in `ghcnd-stations.txt`).
- At Chicago (DuPage vs Cook), Kansas City (Platte vs Jackson) and Atlanta (Clayton vs Fulton), the station's county differs from the hazard county. This is recorded as an assumption on each hub.
- Name resolution is exact-match on id, name, city or alias only. Typos are suggested, never auto-resolved. A state or region name raises `AmbiguousHubError`.

### D-005: Observation states. Missing is never zero.
NOAA, assigned **per element**:
- SNOW and PRCP (accumulations):
  - `measured` when the value is > 0;
  - `trace` when the value is 0 and the measurement flag is "T";
  - `zero` when the value is 0 with no trace flag;
  - `missing` when the key is absent or empty.
- TMIN, TMAX, AWND and WSF5: `measured` (any value, **including negatives and 0 °C**) or `missing`. Trace and zero semantics never apply to them.
- Dates absent from a response become `missing` for every element.
- Quality flags are preserved and marked `quality_flagged`; the value is kept. The exclusion policy is set in Phase 2.
- Example: Miami SNOW is reported on only about 20% of 2016–2025 days. The other days stay `missing`.

Open-Meteo: null → `missing`; 0 → `zero`; > 0 → `measured`. There is no trace concept.

### D-006: NRI hazard states
**Official definitions** (NRI Technical Documentation, December 2025 v1.20, §3.2 Table 2, pp. 3‑5 to 3‑6; extracted from the PDF on 2026-11-25):
- "Not Applicable": *community is not considered at risk for hazard type*. These are a-priori applicability definitions.
- "Insufficient Data": *hazard source data are not available*.
- "No EAL": *hazard type exposure or annualized frequency is zero*.
- "No Rating" (Risk Index only): *Expected Annual Loss is zero*.

**Empirical check:** we cross-tabulated `*_AFREQ` against `*_EALR` over all 3,232 records and 10 hazards. Every record fits this table:

| AFREQ | EALR | Our status |
|---|---|---|
| null | Not Applicable | `not_applicable` |
| null | Insufficient Data | `insufficient_data` |
| 0 | No Expected Annual Losses | `observed_zero` |
| > 0 | any rating (incl. "No Expected Annual Losses", meaning zero exposure) | `observed` |
| anything else | — | `unknown` (conservative) |

- Status is taken from the **EAL rating** (`*_EALR`), not the Risk Index rating (`*_RISKR`). The Risk Index rating also reflects whether social-vulnerability and resilience data exist, so it is not a pure hazard-data state.
- Raw AFREQ, EVNTS, EALR, RISKR and RISKS are all kept. `RISKS` and `RISKR` are context only: they are community-risk percentiles in which nearly every large metro scores 95–100.
- **Remaining limitation:** the documentation defines the rating labels, but it does not explicitly say that a null AFREQ *means* the same as the label. That link is our empirical inference, and it held for 100% of records. Any combination outside the table becomes `unknown`.

### D-007: National reference population (used in Phase 2)
- Of 3,232 NRI county records, 88 are territories (PR 78, AS 3, MP 3, VI 3, GU 1). These are excluded from the reference population, leaving the **3,144** county-equivalents of the 50 states plus DC.
- Per hazard, `not_applicable`, `insufficient_data` and `unknown` counties are excluded from that hazard's denominator. Example: 30 Alaska counties are `insufficient_data` for heat wave.
- `observed_zero` counties will get an indicator score of 0. They are not percentile-ranked, so a mass of zeros cannot inflate anyone's score.
- Positive values will use mid-rank percentiles, with zeros counted below them and ties sharing the mid-rank.
- When a county record and the reference table are used together they **must share one `NRI_VER`**. `DataRepository.get_county_with_reference` enforces this: on a mismatch it takes the county row from the reference table and raises if it is still inconsistent.

### D-008: Source comparability
- A metric, period or ranking never mixes NOAA and Open-Meteo values.
- Each `ClimateDataset` has exactly one source.
- Cross-hub rankings use NOAA. A hub with insufficient NOAA coverage is shown as such, not backfilled.
- Open-Meteo rankings, if offered, are a separate labeled view across all hubs.

### D-009: Cache and snapshot
- **Cache:** stdlib SQLite (`data/cache/cache.db`, gitignored). It stores **raw response bodies**, keyed by sha256 of the source, URL and sorted params, with an integrity hash per entry.
- **Validation before caching:** a response is parsed and validated before it is cached, so an invalid response is never stored.
- **Corrupt entries** are evicted and refetched.
- **TTLs:** 30 days for completed historical periods; 1 day for periods touching the last 30 days; 7 days for NRI.
- **Resolution order:**
  1. Fresh cache.
  2. Live fetch.
  3. On failure: stale cache, labeled `stale_cache`.
  4. Then the snapshot, labeled `snapshot`.
  5. Otherwise a typed `DataUnavailableError`.
- **Climate requests** are canonicalized to calendar-year chunks, so cached and snapshot entries serve any sub-range.
- **Snapshot:** gzip files with deterministic mtime under `data/snapshot/`. They hold raw bodies, so fallback data goes through the same parsers as live data. `manifest.json` records params, retrieval time, period, version, sha256 and licenses for each file. NOAA and FEMA data are public domain; Open-Meteo is CC BY 4.0 (redistributable with attribution).
- **Offline mode** (`WEATHER_RISK_OFFLINE=true`) never calls the network.

### D-010: Completeness vs. confidence
- Data completeness is reported as numbers (reported/expected days, status counts).
- Scientific confidence is **not** claimed. Every answer carries a fixed caveat: "heuristic exposure index; not validated against operational disruption". The product does not use "High confidence" labels.

### D-011: Offline demo scope
The snapshot makes the **data layer** work offline. A real LLM conversation still needs internet and a Gemini key. Deterministic endpoints will work offline; the chat will not.

### D-012: Grounding strategy (implemented in Phase 3)
- The LLM output schema references facts by `fact_id` (produced by tools). Critical numbers (percentages, scores, ranks, counts, dates, periods) are rendered deterministically by server templates with explicit units and rounding.
- Validation:
  1. `fact_id`s must exist.
  2. Hub IDs and periods must match tool arguments.
  3. A secondary scan flags stray numerals in the narrative.
- Regex checking of free prose is not the primary control.

### D-013: Secrets
- `GEMINI_API_KEY` lives only in a local `.env` (gitignored) or the shell environment.
- It is typed as `SecretStr`, so it is redacted in repr and logs.
- `.env.example` has empty values only.
- Claude Code never reads `.env`.

---

## Phase 2 (2026-11-25)

### D-014: Scoring parameters live in versioned, validated config
`config/scoring.yaml` holds the following, all with `methodology_version: 1.0.0`:
- climate source and period (NOAA, 2016–2025);
- minimum coverage (0.90);
- quality-flag exclusion;
- thresholds (4 in heavy snow, TMIN ≤ 0 °C, TMAX ≥ 35 °C);
- climate anchors;
- indicator and hazard weights (equal 0.2);
- partial-hazard threshold (0.60);
- bands.

Load-time validation rejects weights that don't sum to 1, non-positive hazard weights, missing hazards, inverted anchors, inconsistent indicator kinds and non-increasing bands. The parameters were fixed before any scores were computed.

### D-015: Not-applicable FEMA counties belong to the reference population as a no-exposure tier
**Refines Phase 0 Addendum A2**, which excluded them.
- FEMA defines "Not Applicable" as *community not considered at risk*, which is known absence of exposure, not missing data.
- `not_applicable` and `observed_zero` counties stay in the per-hazard denominator, ranked below all positives, and score 0 themselves.
- Only territories, `insufficient_data` and `unknown` are excluded.

Excluding not-applicable counties would rank, say, Dallas's hurricane frequency only against coastal-adjacent counties. Its percentile would fall from 50.8 to 35.5, but for the wrong reason: absent-exposure counties would be dropped instead of counted below it.

### D-016: Not-applicable hazards in hub scores: score 0, keep the weight
A not-applicable indicator contributes 0 and stays in the hazard and overall denominators, so removing it cannot inflate a score (Dallas flood = 48.9, not 97.8). Unknown or insufficient data is never 0. It makes the hazard `partial` (renormalized, if ≥ 60% of weight is available) or `unavailable`, and an unavailable hazard makes the overall index unavailable.

### D-017: Partial results are reported but not ranked
`rank_partial_results: false`. A hub with any partial hazard appears in rankings under `not_ranked` with its score and status. Example: Miami's winter score lacks the snow indicators (20.5% coverage).

### D-018: Annual averages use observed-rate scaling
`annual = (event_days / valid_days) · (expected_days / n_years)`. This assumes missing days resemble observed ones and never treats them as zero. It applies only when coverage is ≥ 90%.

### D-019: Engine contracts carry stable fact ids
Every result (`WeatherStatResult`, `HubProfile`, `RankingResult`, `ComparisonResult`, `Explanation`) carries `Fact`s with ids such as `denver_co.stat.snow_days_measurable.2025-01-01_2025-12-31.noaa_ghcn_daily.percent`, `dallas_tx.overall.score` and `dallas_tx.extreme_heat.nri_heat_wave.score`. Each fact also carries units, sources, period and status. Phase 3 renders critical numbers from these ids (D-012).

### D-020: Premise checks are deterministic
`explain_hub_score(hub, claimed_band)` compares the claim with the configured bands and reports `supported: true/false/None` with reasoning. For Dallas, the claim "High" is **not supported** (59.7, Moderate; rank 2 of 11 ranked hubs). Thresholds were not adjusted.

### D-021 (resolved by D-022): percentile compression near zero
The approved mid-rank percentile gives tiny but positive modeled frequencies mid-range scores. Examples: hurricane, Dallas ≈ 1/87 yr → 50.8; coastal flood, any coastal county ≥ ~85.

Options for a v1.1:
- (a) keep it, and disclose it (current behavior);
- (b) blend the percentile with an absolute log-scale anchor on AFREQ;
- (c) apply a minimum material frequency, e.g. treat < 0.02/yr as the no-exposure tier.

Not changed in Phase 2.

## Phase 2 refinement (2026-11-25, methodology 1.1.0)

### D-022: Hybrid FEMA normalization (methodology 1.1.0)
`s = 0.5·national mid-rank percentile + 0.5·absolute log-frequency`. The absolute half uses one return-period rule for every hazard: 0.01/yr (the 1%-annual-chance "100-year" planning standard) → 0, and 1/yr → 100, on a log10 scale.

- **Chosen over** percentile-only (v1.0.0) and conditional (positive-only) percentiles after a sensitivity analysis (`docs/PHASE_2_SENSITIVITY.md`). The conditional version fixes hurricane but drops Miami's coastal-flood score to 44.0, because coastal counties are then compared only with each other.
- **The hybrid is monotone in frequency,** so every within-hazard ranking is unchanged; magnitudes for rare hazards fall (Dallas hurricane 50.8 → 27.0).
- **No minimum-frequency cutoff:** every positive frequency still scores above 0.
- **Known effect:** for hazards that occur at least yearly almost everywhere, the absolute half saturates at 100, so overall *levels* rose (e.g. Houston 68.3 → 73.6, now in the High band). Overall rank order changed only for two adjacent pairs (Atlanta/Kansas City, Minneapolis/Indianapolis).
- **Not chosen per hub or per hazard.** Hazard-specific severity anchors were out of scope for the timebox.

### D-023: Contribution levels are reported explicitly
**Problem:** the Phase 2 report and summary said Dallas's hurricane indicator was "the single largest contributor to the overall score".
- At **indicator level** that was true: hurricane is the only indicator of its hazard, so it gets the full hazard weight (10.2 points).
- At **hazard level** it was third (severe convective 17.9, heat 16.2, hurricane 10.2).
- The arithmetic was consistent; the wording conflated the two levels.

**Fix:**
- `Explanation` now has `primary_driver` (hazard level), `hazards_by_contribution` (`W_h·H_h`; sums to the overall score), `top_indicators` with both `contribution_to_hazard` and `contribution_to_overall`, and an explanatory note.
- Regression tests check that the primary driver is the argmax of independently recomputed hazard contributions, and that both levels sum to the overall score.

### D-024: Ranking eligibility is per scope, with explicit reasons
- Every `HubProfile` exposes `ranking_eligibility[overall | <hazard>]` with `eligible`, `status` and `reason`.
- `RankingEntry` carries `eligible` and `exclusion_reason`.
- Partial overall scores stay visible but are excluded from the default overall ranking.
- A hazard ranking includes every hub whose *hazard* is complete. Miami is ranked #1 for hurricane and #2 for flood; it is excluded only from the overall and winter rankings, because its snowfall coverage is 20.5% (missing is never treated as 0).

### D-025: AI session export placement and review
The user's `/export` (Phases 0–1) was moved unmodified to `docs/ai-session/session-phase-0-1.txt` after a pattern review: no credentials; personal data limited to the chosen GitHub noreply address and local paths. A real-looking Gemini key was later typed into the tracked `.env.example` and echoed into this session. That file was never staged. The key must be rotated and redacted from the next export.
