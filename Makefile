.PHONY: install test test-live lint format hubs snapshot verify-snapshot validate-data validate-data-offline scenarios scenarios-live api api-offline smoke-live smoke-live-no-weather-network

install:            ## reproducible install from uv.lock
	uv sync --frozen

test:               ## offline test suite (no network, no LLM key)
	uv run pytest

test-live:          ## opt-in live tests against the real public APIs
	uv run pytest -m live

lint:
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts

format:
	uv run ruff format src tests scripts
	uv run ruff check --fix src tests scripts

hubs:
	uv run weather-risk hubs

snapshot:           ## re-fetch and rewrite data/snapshot/ (network; ~6-8 min)
	uv run weather-risk build-snapshot

verify-snapshot:
	uv run weather-risk verify-snapshot

validate-data:      ## live validation report -> docs/PHASE_1_VALIDATION.md
	uv run weather-risk validate-data --out docs/PHASE_1_VALIDATION.md

validate-data-offline:  ## same report from cache/snapshot only (no network)
	uv run weather-risk validate-data --offline

scenarios:          ## Phase 2: 4 assignment scenarios + 12-hub table from the snapshot (no network, no LLM)
	uv run weather-risk scenarios --offline --out docs/PHASE_2_VALIDATION.md

scenarios-live:     ## same, resolving data live (cache -> network -> snapshot)
	uv run weather-risk scenarios

api:                ## start the FastAPI server on http://127.0.0.1:8000 (docs at /docs)
	uv run uvicorn weather_risk.api.app:app --port 8000

api-offline:        ## same, weather data from cache/snapshot only (Gemini still needs network)
	WEATHER_RISK_OFFLINE=true uv run uvicorn weather_risk.api.app:app --port 8000

smoke-live:         ## REAL Gemini: 4 scenarios + 2 conversations + isolation via HTTP (needs key)
	uv run python scripts/live_smoke.py

smoke-live-no-weather-network:  ## REAL Gemini with weather APIs blocked (snapshot only)
	uv run python scripts/live_smoke.py --no-weather-network --only scenarios --out docs/PHASE_3_LIVE_SMOKE_NO_WEATHER_NETWORK.md
