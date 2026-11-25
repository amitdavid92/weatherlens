# Phase 0 — Planning & Research: Weather Risk Intelligence Agent

> **Status:** Phase 0 approved 2026-11-25 with refinements; see the **Phase 0 Addendum** near the end. The Phase 1 execution plan, as approved, is included at the end.
>
> Earlier statements superseded by the Addendum are marked ~~struck~~ or annotated. Where §5–§6 conflict with the Addendum (confidence labels, offline demo, grounding), the Addendum wins.

## Context
Moveo take-home (ASSIGNMENT.pdf, 1 page, read in full). We are building an AI agent that helps logistics analysts see which US distribution hubs are most exposed to weather and should get resilience investment. It must use public APIs, deterministic ranking logic, a chat UI over an API, LLM↔code JSON schema, an eval set, and clear assumptions. Deliverables are due within 24h. Target: 10–14 h of work.

Research date: **2026-11-25**, so "last year" means **calendar 2025**. Every validation result below came from a real request made in this session. Nothing is assumed from documentation alone.

---

## 1. Requirements analysis

### 1.1 Classification
| ID | Requirement (from PDF) | Class |
|---|---|---|
| F1 | Answer the 4 example questions (Midwest winter ranking; Miami vs Houston hurricane+flood; Denver % snow days last year; why Dallas risk high) and generalize | Mandatory functional |
| F2 | Use public APIs to gather weather **and hazard** data | Mandatory functional |
| F3 | Rank or compare hubs using our defined logic/KPI | Mandatory functional |
| F4 | Explain reasoning clearly | Mandatory functional |
| F5 | Support conversational follow-ups | Mandatory functional |
| T1 | Deterministic scoring/ranking logic, not only LLM output | Mandatory technical |
| T2 | Chat interface | Mandatory technical |
| T3 | Agent exposed via an API that the chat UI uses | Mandatory technical |
| T4 | Structured output (JSON schema) enforced between LLM and code | Mandatory technical |
| T5 | Small evaluation set plus a way to run it | Mandatory technical |
| T6 | Communicate assumptions, uncertainty, scoping | Mandatory technical |
| D1 | Source code plus run instructions; runnable live in the interview | Mandatory deliverable |
| D2 | Design doc: architecture (components and how they talk), repo structure, **data storage choice** | Mandatory deliverable |
| D3 | Full AI session: plan and all relevant conversation | Mandatory deliverable |
| D4 | Submit within 24h | Mandatory deliverable |
| P1 | Deploy to a URL | Preferred |
| P2 | Python | Preferred |
| B1 | Voice | Bonus |
| B2 | Scheduled/webhook alert when a hub's risk score changes | Bonus |
| (user) | ≤1-page English overview; GitHub repo; no secrets | Mandatory per user brief |

### 1.2 Traceability matrix
| Req | Phase | Measurable acceptance criterion |
|---|---|---|
| F1 | 3, 5 | The 4 scenarios pass in the LLM eval suite (correct hubs, tool calls, grounded numbers). No hardcoded answers (grep shows no scenario strings in `src/`). |
| F2 | 1 | Adapters for Open-Meteo, NOAA GHCN-Daily and FEMA NRI. Integration tests run live behind a `-m live` marker. Every metric carries `source`, `retrieved_at` and `period`. |
| F3 | 2 | `rank_hubs(hazard, region)` is deterministic: same inputs give a byte-identical JSON output (property test). Ranking order is asserted against hand-computed fixtures. |
| F4 | 2, 3 | Every response includes `drivers[]` (top contributors with values) and `sources[]`. A grounding validator passes (every number in the answer appears in tool outputs). |
| F5 | 3 | Multi-turn eval: "What about Dallas?" after a Miami/Houston comparison resolves to the same hazards for Dallas. |
| T1 | 2 | The scoring engine has zero LLM imports and 100% branch coverage on scoring functions. |
| T2 | 4 | React chat renders answers, a score table and sources. Manual smoke test plus 1 Playwright/Vitest render test (optional). |
| T3 | 3, 4 | `POST /api/chat` is used by the UI. OpenAPI docs at `/docs`. API tests cover it with a mocked LLM. |
| T4 | 3 | The LLM final output is validated against Pydantic `AgentAnswer` (its JSON schema is sent to the LLM). On invalid output: retry once, then a deterministic fallback. Tested with a fake LLM that emits bad JSON. |
| T5 | 5 | `make eval` (or `uv run python -m evals.run`) prints a pass/fail table and writes `evals/report.json`. |
| T6 | 2, 3, 6 | Each answer has `assumptions[]`, `limitations[]` and `data_coverage`. README has a "Scope & Assumptions" section. |
| D1 | 6 | A fresh clone works with `uv sync && npm ci && make dev` (verified in a clean dir). The demo works offline from the snapshot. |
| D2 | 6 | `docs/ARCHITECTURE.md` covers all 3 required topics. |
| D3 | every phase | `docs/ai-session/` holds exports per phase plus the final raw transcript. |
| D4 | 6 | Pushed before the deadline. |

### 1.3 Ambiguities and assumptions
1. **Hub locations aren't given.** We assume a 12-hub example catalog (§3), clearly labeled as illustrative.
2. **"Midwest"** uses the US Census Bureau Midwest region (IL, IN, IA, KS, MI, MN, MO, NE, ND, OH, SD, WI).
3. **"Last year"** is the most recently *completed* calendar year relative to server date (2025 today). "Past 12 months" is handled as a separate, explicit period.
4. **"Snowfall day"** must be defined. The validated data shows the definition changes the answer by 2× (§2.2). Proposed default: NOAA measurable snowfall (≥0.1 in / 2.5 mm, i.e. a reported value >0), with trace days reported separately.
5. **Exposure vs. disruption risk.** We have no shipment, downtime, asset-vulnerability or financial data. So the system computes a **Weather Hazard Exposure Index**, not operational disruption risk. When a user asks "why is Dallas's *disruption risk* high", the agent answers in terms of hazard exposure and says so explicitly. If the premise isn't supported (Dallas isn't high under our method), it says that instead of agreeing.
6. **Hub vs. county.** Hazard-frequency data (NRI) is county-level. Climate data is a station or grid point near the hub. A hub is represented by its metro's county and nearest major-airport station.
7. **Rainfall ≠ flood, wind ≠ hurricane.** Flood exposure comes from NRI coastal and inland flood frequency. Hurricane exposure comes from NRI hurricane frequency. Heavy-precipitation days may be shown as context only, labeled "precipitation intensity, not flood exposure".

---

## 2. Data source research (actual validation results)

### 2.1 Summary
| Source | Verified? | Auth | Granularity | Coverage used | Limits / reliability | License |
|---|---|---|---|---|---|---|
| **Open-Meteo Historical (archive-api)** | ✅ HTTP 200 | None | ~0.25° ERA5 grid (point lat/lon) | snowfall_sum, precip, tmin/tmax, wind/gust daily, 1940→~5 days ago | Weighted rate limit: 600/min (headers). 1 hub-year of 6 vars cost 15.6. **10 hub-years of 5 vars cost 130.5** (0.7 s). 0 nulls in 2025 Denver and 2016–25 Chicago. | CC BY 4.0, free for non-commercial use, attribution required |
| **NOAA NCEI Access Data Service (GHCN-Daily)** | ✅ HTTP 200 | **None** (unlike CDO v2, which needs a token) | Station (airport) | SNOW, PRCP, TMIN, TMAX, AWND, WSF5 | 10 years for ORD returned in 1.3 s with 0 missing. Undocumented rate limits; historically occasionally slow. | US Gov public domain |
| **FEMA National Risk Index — ArcGIS FeatureServer** (`services.arcgis.com/XG15cJAlne2vxtgt/.../National_Risk_Index_Counties/FeatureServer/0`) | ✅ HTTP 200, **NRI_VER = "December 2025"**, 3,232 counties, 467 fields, maxRecordCount 2000 | None | County | Per-hazard `*_EVNTS`, `*_AFREQ` (annualized frequency), `*_EALS`, `*_RISKS`, `*_RISKR` for HRCN, CFLD, IFLD, WNTW, ISTM, CWAV, TRND, HAIL, SWND, HWAV, ... | Stable Esri hosting | FEMA public domain |
| FEMA NRI site `hazards.fema.gov` | ❌ Connection reset (from this network) | — | — | — | Not usable. The ArcGIS service above replaces it. | — |
| NOAA Storm Events (bulk CSV) | ✅ 2025 file streamed: 73,505 rows | None | County (C) **or NWS forecast zone (Z) — 43% of rows** | Event-level records | Zone names don't map cleanly to counties (e.g. "Dallas Divide" CO matched a "Dallas" search). Needs a zone↔county crosswalk. | Public domain |
| NHC HURDAT2 | ✅ index reachable, files to 2025 | None | Storm track points | Hurricane tracks | Needs geospatial buffering. Duplicates what NRI HRCN already models. | Public domain |
| NWS api.weather.gov alerts | ✅ HTTP 200 | None (UA header) | Point/zone | Live alerts only | Not historical. Useful only for bonus alerts. | Public domain |
| Open-Meteo Geocoding | ✅ | None | City | lat/lon | — | CC BY 4.0 |

### 2.2 Denver — % of days with snowfall, 2025 (scenario 3)
| Source / definition | Snow days | Denominator | % |
|---|---|---|---|
| NOAA GHCN DEN airport (USW00003017), **measurable (SNOW > 0)** | 26 | 364 valid (2025-05-21 missing) | **7.1%** |
| NOAA, measurable + trace ("T" flag, stored as 0.0; 19 days) | 45 | 364 | 12.4% |
| Open-Meteo ERA5 grid, snowfall_sum > 0 cm | 43 | 365 | 11.8% |
| Open-Meteo, ≥ 1 cm | 17 | 365 | 4.7% |
| Annual total | NOAA 75.5 cm vs Open-Meteo 57.5 cm | | |

**Findings:** feasible from both sources. Results are highly definition-sensitive. Reanalysis smooths and underestimates snowfall compared with station observations. **Missing-data rule:** exclude missing days from the denominator, report `valid_days / expected_days` coverage, and flag the result as low-confidence if coverage is below 90%. Never fill gaps with the other source silently. Cross-source fallback is allowed only for a whole period and is labeled.

### 2.3 Miami vs Houston — hurricane and flood (scenario 2)
NRI December 2025 (verified values):

| County | HRCN_EVNTS | HRCN_AFREQ (/yr) | HRCN_RISKS | CFLD_AFREQ | CFLD_RISKS | IFLD_AFREQ | IFLD_RISKS |
|---|---|---|---|---|---|---|---|
| Miami-Dade, FL | 124 | **0.30** | 99.96 | 2.25 | 99.60 | 4.00 | 99.71 |
| Harris, TX | 75 | **0.18** | 100 | **3.76** | 83.20 | **5.14** | 99.97 |

Feasible at the same (county) resolution. **Key methodological finding:** NRI `*_RISKS` / `RISK_SCORE` are national *percentiles of community risk*. They combine expected annual loss on *all* exposed buildings, population and agriculture with social vulnerability and community resilience. Every large metro scores 95–100 (Cook 99.97, Maricopa 99.87, Denver 95.23), so they barely separate our hubs and they measure population-scale loss, not hub exposure. **`*_AFREQ` (annualized event frequency) is hazard-intrinsic and separates the hubs well**, so we use it as the primary exposure indicator. RISKS may be shown as context only.

### 2.4 Midwest winter (scenario 1) and Dallas (scenario 4)
- NRI winter fields (verified): WNTW_AFREQ Hennepin 16.58, Cook 14.60, Douglas NE 13.68, Franklin 11.32, Jackson MO 11.21, Wayne 10.21, Marion 10.05. ISTM_AFREQ Wayne 1.88, Dallas 1.23, Jackson 0.92.
- Open-Meteo for Chicago 2016–2025: 18.1 snow days ≥1 cm per year, 109.8 freezing days per year.
- Dallas county (verified): ISTM_AFREQ 1.23 (one of the highest in the set), IFLD_AFREQ 4.61, WNTW 4.05. In 2025 Storm Events: 44 flash-flood, 16 hail, 16 thunderstorm-wind and 1 tornado event. TRND/HAIL/SWND/HWAV **AFREQ** weren't pulled yet (only RISKS); the same endpoint supports them. *Whether Dallas actually ranks "high" is unverified until the engine runs.* The agent must not assume it.

### 2.5 Not verified yet
- GHCN station IDs for 10 of the 12 hubs (only DEN and ORD verified). Candidates are listed in §3.
- Paged download of all 3,232 counties for national percentiles (count and maxRecordCount verified; paging not exercised).
- LLM provider: **no GEMINI/GOOGLE/ANTHROPIC/OPENAI key is set in the environment.** Structured output and tool calling are unverified until a key is supplied.
- Exact NRI semantics of `None` AFREQ (e.g. Denver HRCN = None) need a doc check. ~~Treat as frequency 0~~ **Superseded:** we preserve the state and never coerce it (see Addendum A1).

---

## 3. Proposed hub catalog (illustrative, not real company sites)
| Hub | Region | NRI county (FIPS) | Candidate GHCN station |
|---|---|---|---|
| Chicago, IL | Midwest | Cook (17031) | USW00094846 ORD ✅ |
| Indianapolis, IN | Midwest | Marion (18097) | USW00093819 IND |
| Columbus, OH | Midwest | Franklin (39049) | USW00014821 CMH |
| Detroit, MI | Midwest | Wayne (26163) | USW00094847 DTW |
| Minneapolis, MN | Midwest | Hennepin (27053) | USW00014922 MSP |
| Kansas City, MO | Midwest | Jackson (29095) | USW00003947 MCI |
| Denver, CO | West | Denver (08031) | USW00003017 DEN ✅ |
| Dallas, TX | South | Dallas (48113) | USW00003927 DFW* |
| Houston, TX | South | Harris (48201) | USW00012960 IAH |
| Miami, FL | South | Miami-Dade (12086) | USW00012839 MIA |
| Atlanta, GA | South | Fulton (13121) | USW00013874 ATL |
| Memphis, TN | South | Shelby (47157) | USW00013893 MEM |

*DFW airport sits in Tarrant/Dallas county; the station is used for climate, Dallas County for NRI. Catalog is stored in `config/hubs.yaml`. Unsupported hubs are refused, with the supported list suggested.

## 4. Risk dimensions (5, all data-backed)
| Dimension | Indicators (raw = calculated statistic) | Source |
|---|---|---|
| Winter | mean annual snow days (measurable), heavy-snow days (≥ 10 cm), freezing days (Tmin ≤ 0 °C), WNTW_AFREQ, ISTM_AFREQ, CWAV_AFREQ | GHCN (fallback Open-Meteo) + NRI |
| Hurricane | HRCN_AFREQ | NRI |
| Flood | CFLD_AFREQ, IFLD_AFREQ | NRI |
| Severe convective storms | TRND_AFREQ, HAIL_AFREQ, SWND_AFREQ | NRI |
| Extreme heat | days Tmax ≥ 35 °C, HWAV_AFREQ | GHCN + NRI |

Excluded: earthquake, wildfire and volcano (not weather), and wildfire smoke (no reliable data in scope). Climatology window: 2016–2025, 10 complete years.

## 5. Deterministic scoring methodology (design only)
1. **Raw statistics (facts):** calculated directly from data (counts, means, % of days, NRI frequencies), each with source, period and coverage. These are presented as facts.
2. **Indicator score 0–100 (heuristic):**
   - NRI AFREQ indicators use the **national percentile rank among all 3,232 counties**. That makes them comparable across geography and stable when hubs are added.
   - Station climate indicators use **fixed anchors** from `config/scoring.yaml` (e.g. snow days: 0→0, 40→100, linear, clipped). They are not min-max across the catalog, so adding a hub doesn't change other hubs' scores.
3. **Hazard score** is the weighted mean of available indicator scores (weights in YAML). If an indicator is missing, its weight is redistributed and `partial=true`. If all are missing, the score is `null`, never 0.
4. **Overall Weather Hazard Exposure Index** is the weighted mean of hazard scores, with equal default weights. The agent can request alternative weights (e.g. "winter only"), and those are also computed deterministically.
5. **Bands:** Low < 40 ≤ Moderate < 70 ≤ High. Labeled as heuristic thresholds.
6. **Explanations:** `drivers[]` = indicators sorted by weight × score contribution, with raw value, percentile and source. This is the only material the LLM may cite for "why".
7. **Confidence:** High when coverage is ≥ 95% and all indicators are present. Medium when coverage is ≥ 80% or the result is partial. Otherwise Low.
8. **Determinism:** pure functions, a fixed data snapshot hash, versioned methodology (`methodology_version`). The same snapshot gives identical output regardless of LLM.

**Limitations (stated in UI and docs):** exposure ≠ disruption or loss. Scores are relative heuristics, not probabilities. County frequency ≠ site-level exposure. Station ≠ hub site. Weights are judgment calls. The 10-year window is short for rare events, so hurricane and flood rely on NRI's longer records.

## 6. Architecture

```
React+TS (Vite) chat UI
      │  POST /api/chat {session_id, message}
      ▼
FastAPI ── /api/chat, /api/hubs, /api/hubs/{id}/scores, /api/health, (/api/alerts/check bonus)
      │
      ▼
Agent orchestrator (single agent, tool-calling loop ≤ 6 steps)
  ├─ LLM client (thin interface; Gemini impl; FakeLLM for tests)
  ├─ Tools (Pydantic I/O): list_hubs, get_hub_profile, rank_hubs,
  │   compare_hubs, get_weather_stat(hub, metric, period), explain_hub_score
  ├─ Output: AgentAnswer JSON schema → validate → grounding check
  │   → retry once → deterministic fallback
  └─ Session store (conversation + resolved context: hubs/hazards/period)
      │
      ▼
Analytics & scoring engine (pure Python, no LLM)
      │
      ▼
Data layer: adapters (open_meteo, noaa_ghcn, fema_nri) → normalize/validate (Pydantic)
  → SQLite cache (raw responses + normalized metrics, keyed by request hash)
  → committed snapshot seed (data/snapshot/*.json) for offline demo
```

- **Storage:** stdlib `sqlite3` file (`data/cache.db`, gitignored) as the HTTP/metric cache and session store. A small committed JSON snapshot is used as a fallback so the live demo survives API outages. No ORM.
- **Failure handling:** httpx with timeouts plus 2 retries with backoff. On failure: cache, then snapshot, then explicit "data unavailable" (never fabricated). Responses carry `data_freshness`.
- **Structured output:** the Pydantic `AgentAnswer` fields are `answer`, `intent`, `hubs[]`, `hazards[]`, `period`, `facts_used[] (fact_id, value)`, `assumptions[]`, `limitations[]`, `confidence`, `follow_ups[]`. The schema is passed as the provider's response schema and also validated server-side.
- **Grounding validator:** every number in `answer` must match a tool-output value (with tolerance and unit formatting) and every `fact_id` must exist, or the answer is rejected.
- **Logging:** structlog/JSON logs with request id, tool calls, latency and validation failures. Secrets come from `.env` (gitignored) with a committed `.env.example`.
- **Deployment (optional):** a single Docker image in which FastAPI serves the built React assets, on Render/Fly/Railway.

### Repository structure
```
moveo-weather-risk/
  README.md  OVERVIEW.md (≤1 page)  Makefile  pyproject.toml  .env.example
  config/ hubs.yaml  scoring.yaml
  src/weather_risk/
    data/ adapters/{open_meteo,noaa_ghcn,fema_nri}.py  cache.py  models.py  snapshot.py
    analytics/ stats.py  scoring.py  periods.py
    agent/ llm.py  tools.py  schemas.py  orchestrator.py  grounding.py  prompts.py  session.py
    api/ main.py  routes.py
  web/ (Vite React TS)
  tests/ unit/  integration/  fixtures/ (recorded API responses)
  evals/ cases.yaml  run.py  report.json
  data/snapshot/
  docs/ PHASE_0_PLAN.md  ARCHITECTURE.md  DECISIONS.md  ai-session/
```

## 7. Evaluation strategy
**Deterministic (pytest, offline, from recorded fixtures):** stats (snow-day %, trace and missing handling, coverage), period resolution ("last year" on 2026-11-25 → 2025; leap years), percentile and anchor normalization, weight redistribution, null ≠ 0, ranking order and tie-breaks, determinism (repeated runs give identical hashes), adapter parsing and error paths (timeouts, 429, malformed JSON gives a typed error), API contract with FakeLLM, invalid LLM JSON leads to retry then fallback, grounding validator rejecting invented numbers.

**LLM behavioral evals (`evals/cases.yaml`, real LLM, ~20 cases):** each case lists expected tool(s) and args, the expected hub set, and checks. Checks are: schema-valid, numbers grounded, ranking equals engine output, and required caveats present.
- 4 assignment scenarios.
- Follow-ups: "What about Dallas?", "and in 2024?", "rank them by flood instead".
- Period interpretation: "last year", "2023", "past 12 months".
- Unsupported: hub not in catalog (Boston), unsupported hazard (earthquake), future year.
- Unavailable data: adapter forced down, so the answer states unavailability.
- Fabrication attempts: "just estimate Seattle's numbers", "assume Dallas had 50 tornadoes".
- False premise: "why is Phoenix's hurricane risk high?"

Pass criteria are objective (booleans per check). The runner prints a table and pass rate, and the target is ≥ 90%.

## 8. Roadmap
| Phase | Est. | Depends on | Exit criteria |
|---|---|---|---|
| 0 Planning (this) | 1.5 h | — | This doc approved |
| 1 Foundation and data layer | 2 h | 0 | 3 adapters, cache, snapshot, station IDs verified, fixture tests green |
| 2 Risk engine | 2 h | 1 | Scores for 12 hubs, determinism tests, methodology doc section |
| 3 Agent and API | 3 h | 2 + LLM key | /api/chat, tools, schema enforcement, grounding, FakeLLM tests |
| 4 Web app | 1.5 h | 3 | Chat UI with score table, sources, caveats |
| 5 Evals and QA | 1.5 h | 3 (4 parallel) | `make eval` ≥ 90%, bugs fixed |
| 6 Docs and delivery | 1 h | all | README, ARCHITECTURE, OVERVIEW, session export, clean-clone test |
| 7 Optional | 1–2 h | 6 | Deploy, then alert webhook, then voice (in that order) |
| **Core total** | **~12.5 h** | | |

**Critical path:** data layer → engine → agent (LLM key) → evals → docs.
**Top risks and fallbacks:**
1. No LLM key or quota issues: get a key in Phase 1. The provider interface allows swapping to Claude/OpenAI.
2. NOAA ADS slowness: Open-Meteo fallback plus snapshot.
3. NRI service change: committed snapshot of hub counties plus national percentile tables.
4. Gemini schema quirks with tool calling: separate the tool loop from the final structured call.
5. Time overrun.

**Scope cuts, in order:** drop heat dimension, drop severe-convective → drop NOAA (Open-Meteo only), simplify UI to plain chat, reduce evals to 12.
**MVP:** the 4 scenarios work end-to-end through UI→API→agent→engine with schema-validated output and a runnable eval. **Submission-ready:** MVP plus ≥ 90% eval pass, docs, session export, clean-clone verified, offline snapshot.

## 9. Risks, assumptions, limitations
These are covered in §1.3, §2.5, §5 and §8. Additional points:
- The Open-Meteo free tier is non-commercial. Fine for a take-home; note it in the docs.
- Python 3.14 is installed. Pin **3.12** via uv for wheel compatibility.
- The NRI December 2025 release could change. Store `NRI_VER` with each fact.

## 10. AI session export strategy
- Claude Code writes the raw transcript to `~/.claude/projects/-Users-amitdavid-IdeaProjects-Tasks-Moveo-moveo-weather-risk/<session-id>.jsonl`. It exists for this session (`5281f355-....jsonl`).
- At each phase end: run `/export` to save a readable transcript as `docs/ai-session/phase-N.md`. At delivery, also copy the raw JSONL(s).
- Keep one long session where possible. If sessions split (context resets, new sessions), export each and index them in `docs/ai-session/README.md`.
- Before committing: scan exports for secrets and personal data (API keys, email) and redact only those, noting each redaction. Do not otherwise edit history.
- Maintain `docs/DECISIONS.md` (ADR-lite log) and a phase-completion log.

## 11. Decisions needing approval
1. **Climate source:** NOAA GHCN station observations as primary and Open-Meteo as fallback (recommended), or Open-Meteo only (simpler, but the snow undercount is visible).
2. **Snow-day definition:** measurable (> 0 reported; 7.1% for Denver 2025) as the headline, with trace-inclusive (12.4%) shown as secondary.
3. **Index framing:** "Weather Hazard Exposure Index", explicitly not disruption risk.
4. **Normalization:** NRI national percentiles plus fixed climate anchors (not catalog min-max).
5. **Hub catalog:** the 12 hubs in §3.
6. **LLM provider:** Gemini (please provide `GEMINI_API_KEY`) or another provider.
7. **Storage:** SQLite cache plus committed JSON snapshot.
8. **Frontend:** React+TS (Vite), served by FastAPI in production.
9. **Deployment target** (Render/Fly/Railway) or local-only.

---

## Phase 0 Addendum: post-review refinements (approved decisions and safeguards)

**Approved:**
- Python 3.12 with uv; FastAPI and Pydantic; pytest.
- NOAA GHCN-Daily as primary climate source; Open-Meteo as a clearly labeled alternative.
- NRI ArcGIS FeatureServer for hazard data.
- The 12-hub illustrative catalog.
- Measurable snow as the default definition, with trace reported separately.
- "Weather Hazard Exposure Index" framing.
- National percentiles for NRI and fixed anchors for climate indicators.
- Stdlib SQLite; committed JSON snapshots.
- Gemini, later; React+TS+Vite, later.

Deployment, voice and alerts are deferred.

### A1. Missing data and NRI states (new evidence, gathered 2026-11-25)
Cross-tab of `*_AFREQ` against the `*_RISKR` rating label over all 3,232 records:

| AFREQ | RISKR | Example |
|---|---|---|
| NULL | always "Not Applicable" (HRCN 747, CFLD 2,644, WNTW 2) | Denver HRCN |
| 0 | "No Rating" or "Insufficient Data" | HRCN 126 "No Rating" |
| > 0 | a rating, or "Insufficient Data" / "No Rating" | |

- "Insufficient Data" is the same 88 records for every hazard. **All are US territories:** PR 78, AS 3, MP 3, VI 3, GU 1.
- **Official definitions were not yet confirmed.** The FEMA tech-doc PDF is over 10 MB (fetch tool limit), hazards.fema.gov resets connections from this network, and no local PDF tool is installed. Phase 1 action: download the PDF into the scratchpad and extract the text with a uv-run tool, then cite the definitions in `docs/DECISIONS.md`.
- **Data model rule:** each NRI hazard value carries
  - `status ∈ {observed, observed_zero, not_applicable, no_rating, insufficient_data, unknown}`
  - the raw `afreq`, `events` and `rating_label`.
  - Nothing is coerced. Status is derived from AFREQ together with the rating label. Any combination outside the verified table becomes `unknown`.
- **NOAA daily state:** `measured` (value > 0), `zero` (reported 0, no trace flag), `trace` (measurement flag T), `missing` (row absent or value empty), plus raw M/Q/S flags. A non-empty quality flag means `quality_flagged=True`; the value is kept, and the policy for excluding it is decided in Phase 2.
  - **Evidence:** MIA SNOW is only 20.5% reported for 2016–2025 (99.6–100% elsewhere). Unreported days stay `missing` and are never treated as zero.

### A2. Percentile normalization (implemented in Phase 2, defined now)
- **Reference population:** the 3,144 county-equivalents in the 50 states plus DC. The 88 territory records (PR, GU, AS, MP, VI) are excluded and documented.
- **Per-hazard eligibility:** `not_applicable` / `no_rating` / `insufficient_data` / `unknown` counties are excluded from that hazard's percentile denominator. The reference set size is reported per hazard.
- **Zero handling:** an `observed_zero` county gets an exposure score of **0** for that indicator. It is not given a percentile rank, so a mass of zeros can't inflate it.
- **Positive values:** positive AFREQ values use a mid-rank percentile among the eligible counties, counting zeros as below them. Ties share the mid-rank (average of the tied ranks).
- **Not-applicable hub hazards:** if a hub's county is `not_applicable` for a hazard (e.g. Denver hurricane), that indicator is reported as "not applicable", not as a 0 score. Phase 2 decides how an N/A hazard enters the overall index and documents it.

### A3. Source comparability
- No metric, period or ranking mixes NOAA and Open-Meteo values.
- Each dataset carries `source_id`, and every derived statistic declares exactly one source.
- Cross-hub rankings use the common primary source (NOAA). If a hub's NOAA coverage for a metric falls below threshold, that hub is shown as "insufficient coverage" in the ranking. It is **not** backfilled from Open-Meteo. An Open-Meteo-based ranking can be produced as a separate, labeled view across *all* hubs.

### A4. Coverage vs. confidence
- Replace the single "confidence" label with two fields:
  - `data_completeness`: numeric coverage per source and metric.
  - `methodology_caveats`: fixed statements, e.g. "heuristic exposure index; not validated against operational disruption".
- No "High confidence" wording. The UI shows completeness as a fact and the caveat always.

### A5. Offline demonstration
- The committed snapshot makes the **data layer** work offline and survive API outages.
- **LLM conversations still need internet and a Gemini key.** The deterministic API endpoints (`/api/hubs`, scores) work offline. The chat needs the LLM.
- Phase 3 may add a clearly labeled "LLM unavailable" response; it won't be presented as conversation.

### A6. Grounding strategy (implemented in Phase 3, decided now)
- The LLM output schema references facts by `fact_id` (produced by tools) rather than writing critical numbers freely.
- Critical numbers (percentages, scores, ranks, counts, dates, periods) are rendered deterministically by server templates from the fact registry, with explicit formatting and units.
- The LLM writes narrative around placeholders such as `{{fact:denver.snow_days_pct.2025}}`.
- Validation:
  1. `fact_id`s must exist.
  2. Hub IDs and periods must match tool arguments.
  3. A secondary check flags stray numerals in the narrative that aren't facts.
- Regex validation is not the primary control.

---

## Phase 1 plan: Foundation and data layer (approved for execution)

**Repo:** `/Users/amitdavid/IdeaProjects/Tasks/Moveo/moveo-weather-risk` (contains only `ASSIGNMENT.pdf`, no git). The assignment PDF is never modified.

### P1.1 Foundation
- `git init`. Commit 1 on `main`: scaffold plus `docs/PHASE_0_PLAN.md` and `docs/DECISIONS.md`. Then branch `phase-1-data-layer` for implementation commits (scaffold, catalog, http+cache, each adapter, repository/snapshot, tests, validation doc).
- Commit messages end with the required Co-Authored-By line.
- `uv init --package` style layout: `pyproject.toml` (name `weather-risk`, `requires-python = ">=3.12,<3.13"`), `.python-version` = 3.12, `uv.lock`.
- **Runtime deps (only):** `httpx`, `pydantic`, `pydantic-settings`, `pyyaml`.
- **Dev deps:** `pytest`, `respx`, `ruff`. FastAPI is deferred to Phase 3.
- `.gitignore`: .env, .venv, `data/cache/`, `__pycache__`, node_modules, `*.jsonl`.
- `.env.example`: `GEMINI_API_KEY=` (empty), `WEATHER_RISK_CACHE_PATH`, TTLs, `LOG_LEVEL`.
- `Makefile`: `install`, `test`, `test-live`, `lint`, `snapshot`, `validate-data`.
- `README.md`: setup plus Phase 1 data validation instructions, with Gemini key guidance. Put the key only in a local `.env` (gitignored) or a shell env var; never paste it into chat, code or commits. Settings will expose it as `SecretStr` so it's redacted in logs and repr. I won't read `.env`.
- `docs/DECISIONS.md`: ADR-lite log D-001 to D-0xx, covering the approved decisions plus A1–A6.
- `docs/ai-session/README.md`: export procedure. The raw JSONL stays outside the repo at `~/.claude/projects/-Users-amitdavid-IdeaProjects-Tasks-Moveo-moveo-weather-risk/5281f355-….jsonl` until it has been reviewed and redacted. You run `/export` (a user-only slash command) at each phase end. There's also a redaction log template.

### P1.2 Hub catalog: `config/hubs.yaml` + `src/weather_risk/catalog.py`
- Header comment: **illustrative example hubs, not actual company facilities.**
- **Fields per hub:**
  - `id` (e.g. `chicago_il`), `display_name`, `city`, `state`, `region` (Census), `latitude`, `longitude` (city reference point, verified via Open-Meteo geocoding)
  - `hazard_county {name, fips: "17031"}` (strings)
  - `noaa_station {id, name, latitude, longitude, county_name, county_fips}`
  - `aliases[]`, `assumptions[]`
- **Verified station → county (FCC Census API, 2026-11-25):**
  - Match: IND→Marion, CMH→Franklin, DTW→Wayne, MSP→Hennepin, DEN→Denver, DFW→Dallas, IAH→Harris, MIA→Miami-Dade, MEM→Shelby.
  - Differs from the hazard county: **ORD→DuPage (hazard: Cook)**, **MCI→Platte (hazard: Jackson)**, **ATL→Clayton (hazard: Fulton)**. Each of these is recorded as an assumption.
- All 12 station IDs were verified in `ghcnd-stations.txt` and have SNOW/PRCP/TMAX records into 2026. 2016–2025 completeness was checked; MIA SNOW coverage is 20.5% (assumption noted).
- **`HubResolver.resolve(text)`:**
  - Normalizes (casefold, strip punctuation and "hub").
  - Exact match on id, display name, city, "city, ST" or alias.
  - Raises `UnsupportedHubError` (with difflib suggestions plus the supported list) or `AmbiguousHubError` (e.g. "Texas" → Dallas/Houston).
  - No fuzzy auto-resolution.
- Catalog validation at load: unique ids and aliases, 5-digit FIPS strings, station id pattern, lat/lon bounds, valid region.

### P1.3 Data contracts: `src/weather_risk/data/models.py`, `errors.py`
- `SourceId` enum (noaa_ghcn_daily, open_meteo_archive, fema_nri).
- `Provenance`:
  - `source_id`, `dataset_name`, `dataset_version`
  - `request_url`, `query_params`, `retrieved_at`
  - `geographic_resolution` (station / grid_cell / county) and the location identifier
  - `license`, `attribution`
  - `freshness` (`live` / `cache` / `stale_cache` / `snapshot`)
- `ObservationStatus`, `DailyValue {value_normalized, unit, original_value, original_unit, status, flags}`.
- `DailyObservation`, `ClimateDataset {provenance, element units, period, days, coverage: dict[element, CoverageReport]}`.
- `CoverageReport {expected_days, reported_days, missing_days, missing_dates (truncated list)}`.
- `HazardCode` enum (10 hazards), `HazardStatus`, `HazardValue`, `CountyHazardRecord`, `HazardReferencePopulation {records, total_count, excluded_territories, nri_version}`.
- `SnapshotManifest`, `CacheEntryMeta`.
- **Errors:** `ExternalDataError` → `SourceTimeoutError`, `RateLimitedError`, `InvalidResponseError`, `DataUnavailableError`. Validation errors cover invalid stations and date ranges.
- **No scoring.** Simple coverage counts are allowed because they're factual.

### P1.4 HTTP + cache: `data/http.py`, `data/cache.py`
- **httpx client:** 20 s timeout. Up to 3 attempts with exponential backoff (0.5 s, then 1 s, then 2 s) on timeouts, 5xx and 429. Honors `Retry-After` (capped). Descriptive User-Agent with no personal data.
- **SQLite `http_cache` table:**
  - Columns: `key` (sha256 of source + method + canonical url + sorted params), `source_id`, `url`, `params_json`, `fetched_at`, `expires_at`, `status_code`, `body`, `body_sha256`, `dataset_version`.
  - **TTL policy (configurable):** completed historical periods 30 days; periods touching the last 30 days 1 day; NRI 7 days.
  - **Corrupt or invalid entries:** if the body hash or JSON parse fails, the entry is deleted, a warning is logged and the data is refetched.
  - Logs cache hit, miss, stale and evict.

### P1.5 Adapters (source-specific parsing isolated): `data/adapters/`
- **`noaa_ghcn.py`** (NCEI ADS `daily-summaries`):
  - Elements: SNOW, PRCP, TMIN, TMAX, AWND, WSF5 (missing elements are allowed).
  - `units=metric`, `includeAttributes=true`.
  - Parses the M/Q/S/time attribute flags.
  - Reindexes to the full requested date range, so absent rows become `missing`.
  - Units: snow and precip in mm, temperature in °C, wind in m/s. **Verify the metric conversion live** against `units=standard` for a sample (Phase 1 live test).
  - Validates the station-id regex and that start ≤ end ≤ today.
- **`open_meteo.py`** (archive API):
  - Explicit `temperature_unit=celsius`, `precipitation_unit=mm`, `wind_speed_unit=kmh`. Snowfall arrives in cm and is normalized to mm with the original kept.
  - Records the grid lat/lon, elevation, timezone and the `models` used. Verify that an explicit `models=era5` (or documented best_match) works live.
  - Labeled `modeled_reanalysis`.
- **`fema_nri.py`** (ArcGIS FeatureServer):
  - Fields: STCOFIPS, COUNTY, STATEABBRV, NRI_VER, plus `{H}_EVNTS`, `{H}_AFREQ`, `{H}_RISKR`, `{H}_RISKS` (context only) for H in HRCN, CFLD, IFLD, WNTW, ISTM, CWAV, TRND, HAIL, SWND, HWAV.
  - Single-county fetch by FIPS.
  - National fetch: `returnCountOnly` first, then pages via `resultOffset`/`resultRecordCount=2000` and `orderByFields=OBJECTID`. Validates total == count, unique STCOFIPS, 5-digit FIPS, and a single NRI_VER.
  - Status derivation follows the A1 table.

### P1.6 Repository and snapshot: `data/repository.py`, `data/snapshot.py`
- **`DataRepository.get_station_daily(...)`, `get_open_meteo_daily(...)`, `get_county_hazards(fips)`, `get_hazard_reference()`.**
- **Fallback order:**
  1. Valid cache.
  2. Live fetch (then cache).
  3. On failure: stale cache, labeled `stale_cache`.
  4. Then snapshot, labeled `snapshot`.
  5. Then `DataUnavailableError`.
  - Never fabricates or fills values.
- **Snapshot (`make snapshot`):**
  - Contents: NOAA 2016-01-01..2025-12-31 for the 12 stations; Open-Meteo for the same period for the 12 hubs (throttled under the 600/min weighted limit); NRI hub counties; the compact national reference set (STCOFIPS plus AFREQ and status for the 10 hazards, column-oriented JSON).
  - Location: `data/snapshot/`, alongside a `manifest.json` that records the query params/URLs, generation time, periods, dataset versions, sha256 per file and license/attribution (NOAA and FEMA public domain; Open-Meteo CC BY 4.0, redistributable with attribution).
  - Raw national NRI geometry and unused fields are not committed. Target total size is under ~10 MB; this is checked before commit.

### P1.7 Logging and config
- `config.py`: `Settings` via pydantic-settings. `gemini_api_key: SecretStr | None` is declared and unused.
- `logging_setup.py`: stdlib JSON formatter with `event`, `source`, `cache` and `duration_ms`.

### P1.8 Tests (offline by default; `-m live` opt-in, deselected by default in pytest config)
- **Fixtures:** small real responses trimmed from live calls (Denver Jan 2025 with T-flag days and 2025-05-21 missing; MIA unreported snow; Open-Meteo short range; NRI Miami-Dade/Harris/Denver/Dallas records plus records with null/zero/territory states; 2-page national paging).
- **Coverage:**
  - Catalog: aliases, unsupported, ambiguous, FIPS as strings, station/county mismatch recorded.
  - NOAA: parsing, unit handling, trace vs measurable vs zero vs missing, quality flags, absent dates.
  - Open-Meteo: units cm→mm with original kept.
  - NRI: null vs 0 vs N/A, territory exclusion, pagination, duplicate FIPS rejected, count mismatch rejected.
  - Invalid JSON and HTML error pages produce typed errors.
  - Timeouts and 429 trigger bounded retries.
  - Cache: hit, miss, expiry and corrupt eviction.
  - Repository fallback: stale cache, then snapshot, then unavailable.
  - Snapshot: manifest hashes verified.
  - Provenance present on every result.
  - Date ranges, leap year (2024 = 366) and invalid ranges.
- **Live tests:** one per source plus the NOAA metric-vs-standard unit check.

### P1.9 Live validation: `uv run python -m weather_risk.cli validate-data`
- Writes `docs/PHASE_1_VALIDATION.md` (timestamped, generated from live calls, nothing hardcoded) covering:
  1. The 6 Midwest hubs: NOAA 2016–2025 coverage per element, plus NRI WNTW/ISTM/CWAV values and status.
  2. Miami vs Houston: HRCN/CFLD/IFLD AFREQ, events, status and NRI version.
  3. Denver 2025: daily SNOW counts by status (measured / trace / zero / missing), with dates of missing days.
  4. Dallas: all 10 hazards (TRND/HAIL/SWND/IFLD/WNTW/ISTM/CWAV/HWAV...).
  5. All 12 hubs: a representability table.
- Discrepancies with Phase 0 numbers are reconciled in that doc.

### Phase 1 completion criteria (visible portion; the user's message was truncated at "The national N…")
- Installs reproducibly (`uv sync` from the lockfile).
- 12-hub catalog defined and validated.
- 3 adapters implemented, with real access verified live.
- Models distinguish missing, not-applicable and observed zero.
- National NRI reference population retrieved with validated pagination (assumed continuation of the cut-off item).
- Offline test suite green. Live tests green or failures documented.
- Snapshot plus manifest committed. Validation doc generated. Decisions and session docs updated.
- **Then stop for review.**

**Estimated time:** about 2.5 h.

### Final user requirements (approval message, 2026-11-25)
- NOAA status rules are per-element. Negative temperatures are valid measurements. Trace and zero semantics apply only to SNOW (and PRCP trace flag T where present). Other elements have only measured/missing.
- County hazard records and the national reference population must share the same NRI_VER when used together. Enforce this in code and raise an error on mismatch.
- If FEMA definitions remain unverified, document the limitation and handle conservatively.
- Completion requires:
  - lockfile install
  - 12 hubs validated
  - 3 adapters tested
  - national reference validated
  - cache and snapshot fallback tested
  - 4 scenarios' data available
  - offline tests passing
  - live results documented
  - no secrets
  - scoped commits
  - Phase 0 doc and DECISIONS saved
- Produce `docs/PHASE_1_REPORT.md` with the full list of required sections, including git hashes and independent validation instructions.

## Verification of this phase
- All numbers in §2 come from live requests in this session (Open-Meteo archive, NCEI ADS, NRI ArcGIS, Storm Events CSV, HURDAT2 index, NWS, geocoding). Commands are reproducible from the transcript.
- On approval: write `docs/PHASE_0_PLAN.md` with this content and stop for review before Phase 1.
