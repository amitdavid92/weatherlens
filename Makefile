.PHONY: install test test-live lint format hubs snapshot verify-snapshot validate-data validate-data-offline

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
