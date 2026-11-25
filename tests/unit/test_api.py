"""API contract tests (offline: snapshot-backed engine; FakeProvider or no provider)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.unit.test_agent import DENVER_CALL, GOOD_DENVER
from tests.unit.test_analytics_engine import make_engine
from weather_risk.agent.fake import FakeProvider
from weather_risk.agent.llm import LLMAuthError, LLMQuotaError, LLMTimeoutError, LLMUnavailableError
from weather_risk.agent.session import SessionStore
from weather_risk.api.app import AppState, create_app
from weather_risk.config import Settings


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    return make_engine(tmp_path_factory.mktemp("api"))


def client(engine, tmp_path, provider=None, error="GEMINI_API_KEY is not configured"):
    settings = Settings(_env_file=None, WEATHER_RISK_OFFLINE=True)
    state = AppState(settings, engine, provider, None if provider else error,
                     SessionStore(tmp_path / "s.db"))  # fmt: skip
    return TestClient(create_app(state))


def test_deterministic_endpoints_work_without_llm(engine, tmp_path):
    c = client(engine, tmp_path)
    h = c.get("/api/health").json()
    assert h["status"] == "ok" and h["llm"]["available"] is False and h["snapshot_entries"] > 0
    hubs = c.get("/api/hubs").json()
    assert hubs["illustrative"] is True and len(hubs["hubs"]) == 12
    p = c.get("/api/hubs/dallas_tx/scores")
    assert p.status_code == 200
    assert p.json()["overall_score"] == pytest.approx(
        engine.get_hub_profile("dallas_tx").overall_score
    )
    assert p.json()["ranking_eligibility"]["overall"]["eligible"] is True


def test_chat_without_llm_is_503_not_fake(engine, tmp_path):
    r = client(engine, tmp_path).post("/api/chat", json={"message": "Rank the Midwest"})
    assert r.status_code == 503
    assert (
        r.json()["error"] == "llm_unavailable" and "Deterministic endpoints" in r.json()["detail"]
    )


@pytest.mark.parametrize(
    "path,status,error",
    [("/api/hubs/boston_ma/scores", 404, "unknown_hub"),
     ("/api/hubs/DROP%20TABLE/scores", 422, "invalid_request"),
     ("/api/sessions/does-not-exist-1", 404, "unknown_session"),
     ("/api/sessions/x", 422, "invalid_request")],
)  # fmt: skip
def test_error_responses_are_structured(engine, tmp_path, path, status, error):
    r = client(engine, tmp_path).get(path)
    assert r.status_code == status and r.json()["error"] == error and r.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [{}, {"message": ""}, {"message": "x" * 2001}, {"message": "hi", "extra": 1},
     {"message": "hi", "session_id": "bad id!"}],
)  # fmt: skip
def test_chat_input_validation(engine, tmp_path, body):
    r = client(engine, tmp_path, FakeProvider([])).post("/api/chat", json=body)
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"


def test_chat_contract_session_history_and_unknown_session(engine, tmp_path):
    c = client(engine, tmp_path, FakeProvider([("tools", [DENVER_CALL]), ("text", "ok"),
                                               ("json", GOOD_DENVER)]))  # fmt: skip
    r = c.post(
        "/api/chat", json={"message": "What percentage of days in Denver last year had snowfall?"}
    )
    assert r.status_code == 200
    body = r.json()
    for key in ("session_id", "status", "intent", "answer", "resolved", "facts", "analysis",
                "sources", "data_freshness", "methodology_version", "assumptions",
                "limitations", "follow_up_suggestions", "validation", "agent"):  # fmt: skip
        assert key in body
    assert body["agent"]["provider"] == "fake" and body["narrative_source"] == "llm"
    hist = c.get(f"/api/sessions/{body['session_id']}").json()
    assert hist["turns"][0]["user_message"].startswith("What percentage")
    r2 = c.post("/api/chat", json={"message": "and 2024?", "session_id": "unknownsession1"})
    assert r2.status_code == 404 and r2.json()["error"] == "unknown_session"


@pytest.mark.parametrize(
    "exc,status,error",
    [(LLMQuotaError("429"), 429, "llm_quota_exceeded"), (LLMTimeoutError("t"), 504, "llm_timeout"),
     (LLMAuthError("bad key"), 503, "llm_auth_error"),
     (LLMUnavailableError("503"), 503, "llm_unavailable")],
)  # fmt: skip
def test_provider_errors_map_to_status_codes(engine, tmp_path, exc, status, error):
    c = client(engine, tmp_path, FakeProvider([("raise", exc)]))
    r = c.post("/api/chat", json={"message": "Rank the Midwest for winter"})
    assert r.status_code == status and r.json()["error"] == error


def test_cors_is_narrow(engine, tmp_path):
    c = client(engine, tmp_path)
    ok = c.options("/api/hubs", headers={"Origin": "http://localhost:5173",
                                         "Access-Control-Request-Method": "GET"})  # fmt: skip
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = c.options("/api/hubs", headers={"Origin": "https://evil.example",
                                          "Access-Control-Request-Method": "GET"})  # fmt: skip
    assert "access-control-allow-origin" not in bad.headers


def test_openapi_documents_endpoints(engine, tmp_path):
    spec = client(engine, tmp_path).get("/openapi.json").json()
    for path in ("/api/health", "/api/hubs", "/api/hubs/{hub_id}/scores", "/api/chat",
                 "/api/sessions/{session_id}"):  # fmt: skip
        assert path in spec["paths"]
    assert "ChatResponse" in spec["components"]["schemas"]
