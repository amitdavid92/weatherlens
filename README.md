# Weather Risk Intelligence Agent

An AI agent that helps logistics analysts see which US distribution hubs are most exposed to weather hazards. It uses public data and deterministic analytics; the LLM never computes numbers or rankings.

> **Status: Phase 2 (deterministic risk engine) complete.** Next: agent and API (Phase 3), then the chat UI (Phase 4). See [docs/PHASE_2_REPORT.md](docs/PHASE_2_REPORT.md) and [docs/SCORING_METHODOLOGY.md](docs/SCORING_METHODOLOGY.md).

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
