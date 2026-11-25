# Architecture

The **Weather Risk Intelligence Agent** answers analysts' questions about weather-hazard exposure of 12 illustrative US distribution hubs. Core principle: **the LLM never produces numbers.**
- A deterministic engine computes every statistic, score and ranking from public data.
- The LLM picks tools and writes narrative that references verified facts by id.

## 1. Components and how they talk
```
 WeatherLens (React + Vite)        curl / scripts/live_smoke.py
   browser → Vite dev server ──/api proxy──┐  │
                                           ▼  ▼
 ┌──────────────────────── FastAPI (weather_risk.api.app) ─────────────────────────┐
 │ GET /api/health   GET /api/hubs   GET /api/hubs/{id}/scores   GET /api/sessions │
 │ POST /api/chat ──► Agent (agent/orchestrator.py)                                 │
 └────────────────────────────────┬─────────────────────────────────────────────────┘
                                  │
        ┌─────────────────────────┼──────────────────────────────┐
        ▼                         ▼                              ▼
  LLM provider              ToolBox (agent/tools.py)       SessionStore (SQLite)
  (agent/gemini.py)         6 typed tools, Pydantic args   bounded history +
   1) tool loop             ──► AnalyticsEngine            resolved context
   2) structured JSON           (analytics/engine.py)
        │                         │  pure scoring, stats, percentiles
        ▼                         ▼
  Grounding validator       DataRepository (data/repository.py)
  (agent/grounding.py)        cache ─► live API ─► stale cache ─► snapshot ─► error
  facts, attribution,         │            │
  numbers, superlatives,      ▼            ▼
  premise                  SQLite cache   NOAA GHCN-Daily · Open-Meteo ERA5 · FEMA NRI
                           (raw bodies)   (+ committed snapshot in data/snapshot/)
```

### Web app (Phase 4)
| View | Endpoints | Notes |
|---|---|---|
| Overview | `/api/overview`, `/api/rankings?hazard=&region=`, `/api/hubs/{id}/scores` | KPIs; self-contained US map (us-atlas Albers + d3-geo; no tiles or keys); rankings with partial hubs listed separately with reasons; hub profile |
| AI Analyst | `/api/chat`, `/api/sessions/{id}` | The narrative is shown as safe Markdown. Evidence blocks are rendered from `analysis` only; numbers are never parsed from prose. Docked beside the dashboard on screens ≥ 1280 px. |
| Methodology & Data | `/api/methodology`, `/api/overview` | All parameters, versions and freshness come from the API |
| Status bar | `/api/health`, `/api/overview` | Separate indicators for analytics availability, AI availability and data freshness |

**Data integrity:** the frontend never computes scores, bands or ranks. It displays the backend's `*_display` strings (band-safe rounding, D-026). Its only local formatting is for raw values such as coverage percentages and frequencies.

**Frontend state:** React state plus one `useChat` hook; no state library.

### Provider resilience and observability (Phase 5)
**Model chain** (`gemini-3.5-flash-lite` → `gemini-3.6-flash` → `gemini-3.5-flash`, thinking level `low`):
- 503, timeout or 429: move to the next model immediately.
- Whole-chain rounds are bounded.
- Day-long quota 429s trip a per-model circuit breaker.
- If synthesis cannot get any model after the tools succeeded, the response is the labeled deterministic summary.

**Observability:** every response carries `agent.timings_ms`:
- tool-selection LLM;
- tool execution;
- synthesis LLM;
- validation;
- provider waits;
- prompt size.

It also carries `agent.llm_calls`: every HTTP attempt, with model, latency, tokens and errors.

**Evaluation:** `evals/run.py` drives the real API with `evals/cases.yaml` (see the README).

### Request flow for `POST /api/chat`
1. **Load the session.** The server reads the last 6 turns and the latest resolved context (hubs, hazards, metric, period) from SQLite. A new session gets an unguessable id.
2. **Tool phase,** at most 6 iterations and 12 tool calls. Gemini receives the system rules, the history and the six tool declarations. For each function call:
   - the server checks that the hubs it names were mentioned by the user or appear in the session context (*no silent guessing*);
   - it validates the arguments with Pydantic and runs the deterministic engine;
   - it registers every number in a per-turn **FactRegistry** (`fact_id → value, display, hub, topic, period, sources`);
   - it returns a compact payload whose numbers are fact references only.
3. **Synthesis.** A second Gemini call, with no tools, returns `LLMAnswer` JSON. The provider enforces the schema natively (`response_json_schema`). This is a separate call because on the live API, combining tools and a schema made the model skip tool calls.
4. **Validation.** `LLMAnswer` is checked in two stages:
   - Pydantic validation of the schema;
   - grounding validation:
     - every fact exists;
     - cited hub = the fact's hub;
     - no fact sits in a sentence about a different hub;
     - no numbers outside placeholders;
     - superlatives match the rank-1 hub or the comparison leader *for that hazard*;
     - unsupported premises are corrected.
   - On failure: one retry with targeted feedback.
   - If it still fails: a **clearly labeled deterministic summary** built from the tool results, or an error if there are none. Never a fabricated answer.
5. **Rendering.** `{{fact:id}}` placeholders are replaced with deterministic displays, with band-safe score rounding. The response carries the narrative *separately* from the authoritative payloads: rankings, comparisons, statistics, explanations, facts, sources, freshness, methodology version, assumptions, limitations and validation report.

### Agent tools
| Tool | Engine call | Returns |
|---|---|---|
| `list_hubs` | catalog | Hubs (illustrative) |
| `get_hub_profile` | `get_hub_profile` | Overall + five hazard scores, indicators, eligibility |
| `rank_hubs` | `rank_hubs` | Ranked hubs + excluded hubs with reasons |
| `compare_hubs` | `compare_hubs` | Per-hazard scores, leader, difference, FEMA frequencies |
| `get_weather_stat` | `get_weather_stat` | % of valid days, counts, coverage, missing dates |
| `explain_hub_score` | `explain_hub_score` | Hazard-level drivers, indicator contributions, rank, premise check |

## 2. Repository structure
```
config/hubs.yaml, scoring.yaml       illustrative catalog; methodology 1.1.0 parameters
src/weather_risk/
  data/        adapters (NOAA, Open-Meteo, FEMA NRI), http, cache, snapshot, repository, models
  analytics/   periods, stats, percentiles, scoring, engine, formatting, report (no LLM)
  agent/       llm (interface), gemini, fake (tests), tools, facts, grounding, schema,
               session, orchestrator
  api/app.py   FastAPI app factory + endpoints
  cli.py       weather-risk CLI (hubs, snapshot, validate-data, scenarios)
data/snapshot/ committed raw API responses + manifest (offline fallback)
tests/unit/    offline tests (fixtures, snapshot-backed engine, FakeProvider)
tests/integration/  opt-in live data-source tests (-m live)
scripts/       record_fixtures.py, sensitivity.py, live_smoke.py, benchmark.py (REAL Gemini)
evals/         cases.yaml (versioned dataset), run.py (runner), results/ (actual runs)
web/           WeatherLens frontend (src/api, src/components, src/hooks, e2e/)
docs/          plan, decisions, methodology, phase reports, screenshots, AI session export
```

## 3. Data storage choice
| Store | Technology | Why |
|---|---|---|
| HTTP response cache | SQLite (stdlib `sqlite3`), `data/cache/cache.db` | Zero-ops, single file, transactional, queryable. Raw bodies plus integrity hash, so parsers can change without refetching. |
| Offline fallback | Committed gzip snapshot + `manifest.json` | The live demo survives API outages; reproducible; public-domain / CC BY data |
| Conversations | SQLite, `data/cache/sessions.db` | Same rationale. Sessions are isolated by a random id, with bounded history |
| Configuration | YAML (`config/`) + `.env` (secrets, gitignored) | Reviewable parameters. Secrets never in git; loaded as `SecretStr` |

There is no ORM, vector database or external database server, because the data volume is tiny and the access patterns are key lookups.

## 4. Security notes (local prototype)
- **Secrets:** the Gemini key stays on the server, in `.env` (gitignored), and is never logged.
- **Input limits:** chat input is limited to 2,000 characters; session ids are validated. Tool arguments are strict Pydantic models (`extra=forbid`, enums, length limits), and tool payloads are capped at 24 KB.
- **Narrow tool surface:** the LLM has no code execution, HTTP or database access, only six read-only tools.
- **Prompt injection:**
  - user text is wrapped as untrusted, and the rules are restated;
  - the grounding validator rejects numbers that don't come from facts, whatever the model was told.
- **CORS:** restricted to the local Vite origins. Only GET/POST and `Content-Type` are allowed.
- **Not production-ready:**
  - no authentication or rate limiting on the API;
  - single process, with a lock serializing engine access;
  - no TLS;
  - session data is not encrypted at rest;
  - the session id is the only access control.
