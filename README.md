# WeatherLens — Logistics Weather Risk Intelligence

![WeatherLens overview](docs/screenshots/desktop-1440-overview.png)

An AI agent that helps logistics analysts see which US distribution hubs are most exposed to weather hazards. It uses public data and deterministic analytics; the LLM never computes numbers or rankings.

> **Status: Phase 5 (evaluation and QA) partially complete.** The 90% target is not met and the latest fixes are not yet verified live (Gemini free-tier quota). See [docs/PHASE_5_REPORT.md](docs/PHASE_5_REPORT.md).

**Scope and framing:** the product computes a **Weather Hazard Exposure Index**. It does not measure operational disruption risk, because we have no shipment, downtime or loss data. The 12 hubs in [config/hubs.yaml](config/hubs.yaml) are **illustrative examples**, not real company facilities.

## Data sources
| Data | Source | Auth | License |
|---|---|---|---|
| Daily station observations: snow, precipitation, min/max temperature, wind (primary) | NOAA NCEI GHCN-Daily (Access Data Service) | none | Public domain |
| Daily ERA5 reanalysis (alternative, labeled as modeled) | [Open-Meteo](https://open-meteo.com/) archive API | none | CC BY 4.0; "Weather data by Open-Meteo.com" |
| County annualized hazard frequencies | FEMA National Risk Index, Dec 2025 (ArcGIS FeatureServer) | none | Public domain |

## Setup
Requirements: [uv](https://docs.astral.sh/uv/). uv provides Python 3.12 automatically.

```bash
uv sync --frozen        # reproducible install from uv.lock
cp .env.example .env    # optional for Phase 1; nothing secret is needed yet
```

### LLM key (needed from Phase 3; not now)
Put the key **only** in your local `.env`, which is gitignored:
```
GEMINI_API_KEY=your-key-here
```
Alternatively, set it as an environment variable: `export GEMINI_API_KEY=...`.
- Never paste the key into chat, code, issues or commits.
- The app loads it as a `SecretStr`, so it is redacted in logs.

## Validating the data layer (Phase 1)
```bash
make test               # offline unit tests: no network, no LLM key
make test-live          # opt-in live tests against NOAA, Open-Meteo and FEMA
make hubs               # list the illustrative catalog
make validate-data      # live report for all 12 hubs + the 4 scenarios -> docs/PHASE_1_VALIDATION.md
make validate-data-offline   # same report from cache/snapshot only (no network)
make verify-snapshot    # check committed snapshot hashes
make snapshot           # re-fetch everything into data/snapshot/ (~6-8 min, network)
```

### How data is resolved
1. Fresh SQLite cache entry (`data/cache/cache.db`).
2. Live fetch, validated before it is cached.
3. On failure: the stale cache entry, labeled `stale_cache`.
4. Then the committed snapshot (`data/snapshot/`), labeled `snapshot`.
5. Otherwise a typed `DataUnavailableError`. Data is never fabricated or filled in.

Set `WEATHER_RISK_OFFLINE=true` to skip the network entirely.

## Quick start (full stack)
Requirements: [uv](https://docs.astral.sh/uv/) and Node.js ≥ 20. uv provides Python 3.12 automatically.
```bash
uv sync --frozen && make web-install     # backend + frontend dependencies (lockfiles)
cp .env.example .env                     # then set GEMINI_API_KEY=... (only needed for the AI Analyst)
make dev                                 # API on :8000 + WeatherLens on http://localhost:5173
```
- **Different frontend port:** use `make dev WEB_PORT=5181` if 5173 is taken. `API_URL=http://127.0.0.1:8010` points the frontend proxy at a backend on another port.
- **No network for weather data:** `WEATHER_RISK_OFFLINE=true make dev` serves weather data from the committed snapshot. The AI Analyst still needs internet.
- **How the frontend reaches the API:** the browser only calls the Vite server, which proxies `/api` to FastAPI, so the Gemini key never reaches the browser.
- **Without a key:** the Overview and Methodology views work fully, and the AI Analyst shows that it is unavailable.

### Web app commands
```bash
make web-test         # Vitest (9 integration tests on recorded real API responses)
make web-lint         # oxlint + TypeScript type check
make web-build        # production build -> web/dist
make web-inspect      # real Chromium: overflow/console checks + screenshots at 1440/1024/390 (app running)
make web-real-gemini  # the 4 assignment questions through the UI with REAL Gemini (app running, uses quota)
```
Playwright's browser is needed for the last two commands: `cd web && npx playwright install chromium`.

## Evaluation (real Gemini)
```bash
make eval            # 22 cases / 29 turns in evals/cases.yaml -> evals/results/latest.{md,json}
make eval-smoke      # quick demo subset (assignment questions, isolation, injection)
uv run python evals/run.py --case A3-denver-snow-2025 --category multi_turn   # filters
make benchmark LABEL=mytest   # latency breakdown of the 4 assignment questions -> docs/benchmarks/
```
**How the evaluation runs:**
- It starts its own server, with weather data from the committed snapshot (weather APIs blocked, empty cache), so results are comparable across runs.
- It paces requests for free-tier quotas.
- It records the model, fallbacks, thinking level, methodology and dataset version.

**What it reports:**
- per case: pass, pass with deterministic fallback, fail, or provider error;
- the assertion pass rate;
- critical (numerical grounding) failures;
- retries, deterministic fallbacks and use of fallback models.

**Quota:** it needs a Gemini key. On the free tier, `gemini-3.5-flash` and `3.6-flash` allow only 20 requests per day each, so most calls go to `gemini-3.5-flash-lite`.

## Running the API and agent (Phase 3)
1. Put your Gemini key in `.env` (gitignored): `GEMINI_API_KEY=...`. See `.env.example` for the model and timeout settings.
2. Start the server:
   ```bash
   make api            # http://127.0.0.1:8000 ; interactive OpenAPI docs at /docs
   make api-offline    # weather data from cache/snapshot only (Gemini still needs internet)
   ```
3. Example requests:
   ```bash
   curl -s localhost:8000/api/health
   curl -s localhost:8000/api/hubs
   curl -s localhost:8000/api/hubs/dallas_tx/scores          # deterministic, no LLM needed
   curl -s -X POST localhost:8000/api/chat -H 'Content-Type: application/json' \
        -d '{"message": "Which hubs in the Midwest are most exposed to winter disruption?"}'
   # follow-up in the same conversation: pass the returned session_id
   curl -s -X POST localhost:8000/api/chat -H 'Content-Type: application/json' \
        -d '{"message": "What about Denver?", "session_id": "<session_id from the previous response>"}'
   ```

The `/api/chat` response separates the LLM's narrative (`answer`, rendered from verified fact ids) from the authoritative engine output (`analysis`, `facts`, `sources`, `data_freshness`). It also includes the `validation` report and `agent` metadata: model, tool calls, tokens and latency.

**Without a Gemini key,** `/api/chat` returns `503 llm_unavailable`; the deterministic endpoints keep working.

**Real-LLM smoke tests:** these use your key and quota and take a few minutes.
```bash
make smoke-live                       # 4 scenarios + 2 multi-turn conversations + isolation
make smoke-live-no-weather-network    # scenarios with weather APIs blocked (snapshot only)
```

## Running the risk engine (Phase 2, no LLM)
```bash
make scenarios          # 4 assignment scenarios + 12-hub score table from the snapshot -> docs/PHASE_2_VALIDATION.md
make scenarios-live     # same, resolving data live (cache -> network -> snapshot)
```
Scores are a heuristic **Weather Hazard Exposure Index** (0–100) over five hazards: winter, hurricane, flood, severe convective storms and extreme heat. The parameters are in [config/scoring.yaml](config/scoring.yaml) and the method is documented in [docs/SCORING_METHODOLOGY.md](docs/SCORING_METHODOLOGY.md).

## Repository layout (so far)
```
config/hubs.yaml                 illustrative hub catalog (verified stations/counties)
src/weather_risk/
  catalog.py                     catalog loading, validation, strict name resolution
  config.py                      settings (.env), SecretStr for keys
  cli.py                         weather-risk CLI (hubs, build-snapshot, validate-data, ...)
  agent/                         Gemini provider, typed tools, fact registry, grounding, sessions
  api/app.py                     FastAPI endpoints
web/                             WeatherLens (React + TypeScript + Vite)
  src/api/                       typed client + response types
  src/components/                Overview, UsMap, HubProfilePanel, ChatPanel, AnswerCard, Methodology
  src/hooks/useChat.ts           conversation state, retry, session persistence
  e2e/                           Playwright scripts (inspection, real-Gemini UI run)
  data/
    models.py                    typed contracts (provenance, statuses, datasets, NRI records)
    adapters/{noaa_ghcn,open_meteo,fema_nri}.py   source-specific request/parse only
    http.py  cache.py  snapshot.py  repository.py  periods.py  errors.py
  analytics/
    config.py  periods.py  stats.py  percentiles.py  scoring.py   pure deterministic logic
    engine.py                    get_weather_stat / get_hub_profile / rank_hubs / compare_hubs / explain_hub_score
    models.py  report.py         typed result contracts with fact ids; scenario report
config/scoring.yaml              methodology 1.0.0: anchors, weights, thresholds, coverage policy
data/snapshot/                   committed raw-response snapshot + manifest.json
tests/unit/                      offline tests (real recorded fixtures in tests/fixtures/)
tests/integration/               opt-in live tests (-m live)
scripts/record_fixtures.py       re-records the small real fixtures
docs/                            plan, decisions, phase reports, AI session
```

## Attribution
Weather data by [Open-Meteo.com](https://open-meteo.com/) (ERA5, Copernicus/ECMWF). NOAA NCEI GHCN-Daily. FEMA National Risk Index.
