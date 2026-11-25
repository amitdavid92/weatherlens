from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from weather_risk.config import PROJECT_ROOT, Settings
from weather_risk.data.cache import ResponseCache
from weather_risk.data.http import HttpResponse, SourceRequest

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def load_fixture(name: str) -> tuple[SourceRequest, bytes]:
    meta = json.loads((FIXTURES / f"{name}.request.json").read_text())
    req = SourceRequest(
        source_id=meta["source_id"],
        url=meta["url"],
        params=meta["params"],
        location_id=meta.get("location_id"),
    )
    return req, (FIXTURES / f"{name}.body").read_bytes()


class FakeFetcher:
    """Deterministic stand-in for HttpFetcher: maps request keys to bodies or exceptions."""

    def __init__(self) -> None:
        self.responses: dict[str, bytes | Exception] = {}
        self.calls: list[SourceRequest] = []

    def add(self, req: SourceRequest, outcome: bytes | Exception) -> None:
        self.responses[req.key] = outcome

    def get(self, req: SourceRequest) -> HttpResponse:
        self.calls.append(req)
        outcome = self.responses.get(req.key)
        if outcome is None:
            from weather_risk.data.errors import SourceHTTPError

            raise SourceHTTPError(req.source_id, 404, f"no fake response for {req.params}")
        if isinstance(outcome, Exception):
            raise outcome
        return HttpResponse(status_code=200, body=outcome, elapsed_ms=1.0, headers={})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        WEATHER_RISK_CACHE_PATH=tmp_path / "cache.db",
        WEATHER_RISK_SNAPSHOT_DIR=tmp_path / "snapshot",
        WEATHER_RISK_HUBS_PATH=PROJECT_ROOT / "config" / "hubs.yaml",
        GEMINI_API_KEY=None,
        _env_file=None,
    )


@pytest.fixture
def cache(tmp_path: Path) -> ResponseCache:
    c = ResponseCache(tmp_path / "cache.db")
    yield c
    c.close()


@pytest.fixture
def fake_fetcher() -> FakeFetcher:
    return FakeFetcher()
