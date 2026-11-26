"""Phase 7 public-demo protections: limits, AI slot, deadline, demo password, frontend serving,
error sanitization and session isolation. Offline (snapshot engine, scripted provider)."""

from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient

from tests.unit.test_agent import DENVER_CALL, GOOD_DENVER
from tests.unit.test_analytics_engine import make_engine
from tests.unit.test_gemini_provider import Resp, api_error, provider
from weather_risk.agent.fake import FakeProvider
from weather_risk.agent.llm import LLMTimeoutError, LLMUnavailableError
from weather_risk.agent.orchestrator import Agent
from weather_risk.agent.session import SessionStore
from weather_risk.api.app import AppState, create_app
from weather_risk.api.guard import ChatSlots, DailyCounter, SlidingWindowLimiter, client_ip
from weather_risk.config import Settings

Q = "What percentage of days in Denver last year had snowfall?"


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    return make_engine(tmp_path_factory.mktemp("guards"))


def good_script(n: int = 1) -> list:
    return [("tools", [DENVER_CALL]), ("text", "ok"), ("json", GOOD_DENVER)] * n


def client(engine, tmp_path, provider=None, **env) -> TestClient:
    settings = Settings(_env_file=None, WEATHER_RISK_OFFLINE=True, **env)
    state = AppState(settings, engine, provider, None if provider else "not configured",
                     SessionStore(tmp_path / "s.db"))  # fmt: skip
    return TestClient(create_app(state))


# ------------------------------------------------------------------ guard primitives
def test_sliding_window_limits_and_recovers():
    now = [0.0]
    lim = SlidingWindowLimiter(2, 60, clock=lambda: now[0])
    assert lim.hit("a") is None and lim.hit("a") is None
    assert lim.hit("a") == pytest.approx(60.0)
    assert lim.hit("b") is None  # keys are independent
    now[0] = 61
    assert lim.hit("a") is None
    assert SlidingWindowLimiter(0, 60).hit("x") is None  # 0 disables


def test_daily_counter_resets_each_utc_day():
    from datetime import UTC, datetime

    day = [datetime(2026, 11, 26, tzinfo=UTC)]
    d = DailyCounter(2, now=lambda: day[0])
    assert d.hit() and d.hit() and not d.hit()
    day[0] = datetime(2026, 11, 27, tzinfo=UTC)
    assert d.hit()


def test_chat_slots_bound_concurrency_and_queue():
    slots = ChatSlots(1, max_waiting=0, queue_timeout=0.01)
    assert slots.acquire()
    assert not slots.acquire()  # no queue room
    slots.release()
    assert slots.acquire()
    slots.release()


def test_client_ip_ignores_spoofed_forwarded_entries():
    class R:
        def __init__(self, xff):
            self.headers = {"x-forwarded-for": xff} if xff else {}
            self.client = type("C", (), {"host": "10.0.0.5"})()

    assert client_ip(R("6.6.6.6, 203.0.113.9"), 1) == "203.0.113.9"  # proxy-appended entry
    assert client_ip(R("6.6.6.6"), 0) == "10.0.0.5"  # no proxy trusted: socket peer
    assert client_ip(R(None), 1) == "10.0.0.5"


# ------------------------------------------------------------------ chat limits through the API
def test_per_ip_rate_limit_returns_429_with_retry_after(engine, tmp_path):
    c = client(engine, tmp_path, FakeProvider(good_script(2)),
               WEATHER_RISK_CHAT_LIMIT_PER_IP_MINUTE=2)  # fmt: skip
    assert c.post("/api/chat", json={"message": Q}).status_code == 200
    assert c.post("/api/chat", json={"message": Q}).status_code == 200
    r = c.post("/api/chat", json={"message": Q})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert r.json()["retryable"] is True and int(r.headers["retry-after"]) >= 1


def test_per_session_limit(engine, tmp_path):
    c = client(engine, tmp_path, FakeProvider(good_script(2)),
               WEATHER_RISK_CHAT_LIMIT_PER_SESSION_HOUR=1)  # fmt: skip
    sid = c.post("/api/chat", json={"message": Q}).json()["session_id"]
    assert c.post("/api/chat", json={"message": Q, "session_id": sid}).status_code == 200
    r = c.post("/api/chat", json={"message": Q, "session_id": sid})
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"


def test_daily_limit(engine, tmp_path):
    c = client(engine, tmp_path, FakeProvider(good_script(1)), WEATHER_RISK_CHAT_DAILY_LIMIT=1)
    assert c.post("/api/chat", json={"message": Q}).status_code == 200
    r = c.post("/api/chat", json={"message": Q})
    assert r.status_code == 429 and r.json()["error"] == "daily_limit_reached"
    assert c.get("/api/overview").status_code == 200  # dashboard unaffected


def test_busy_when_the_ai_slot_and_queue_are_full(engine, tmp_path):
    c = client(engine, tmp_path, FakeProvider(good_script(1)), WEATHER_RISK_CHAT_MAX_WAITING=0)
    c.app.state.ctx.chat_slots.acquire()  # simulate a request in flight
    r = c.post("/api/chat", json={"message": Q})
    assert r.status_code == 503 and r.json()["error"] == "busy" and r.json()["retryable"]
    c.app.state.ctx.chat_slots.release()
    assert c.post("/api/chat", json={"message": Q}).status_code == 200


def test_provider_error_details_never_reach_the_client(engine, tmp_path):
    secret = "upstream said: project 1234 key AIza-internal-detail"
    c = client(engine, tmp_path, FakeProvider([("raise", LLMUnavailableError(secret))]))
    r = c.post("/api/chat", json={"message": "Rank the Midwest for winter"})
    assert r.status_code == 503 and r.json()["error"] == "llm_unavailable"
    assert "1234" not in r.text and "AIza" not in r.text


def test_slot_is_released_after_errors(engine, tmp_path):
    c = client(engine, tmp_path, FakeProvider([("raise", LLMTimeoutError("t")), *good_script(1)]),
               WEATHER_RISK_CHAT_MAX_WAITING=0)  # fmt: skip
    assert c.post("/api/chat", json={"message": Q}).status_code == 504
    assert c.post("/api/chat", json={"message": Q}).status_code == 200


# ------------------------------------------------------------------ deadline
class SlowToolProvider(FakeProvider):
    def tool_step(self, **kw):
        time.sleep(0.05)
        return super().tool_step(**kw)


def test_deadline_stops_the_tool_loop_and_still_answers(engine, tmp_path):
    # Without the deadline the agent would ask for another tool step and get "json" -> error.
    p = SlowToolProvider([("tools", [DENVER_CALL]), ("json", GOOD_DENVER)])
    agent = Agent(engine, p, SessionStore(tmp_path / "d.db"))
    r = agent.chat(Q, deadline_seconds=0.01)
    assert r.status == "answered" and r.validation.valid
    assert [c["type"] for c in p.calls] == ["tool_step", "structured"]


def test_provider_refuses_to_start_a_call_after_the_deadline():
    p, stub, sleeps = provider([api_error(503), Resp()], max_attempts=3)
    p.deadline = time.monotonic() + 5  # below Gemini's 10 s minimum per-call deadline
    with pytest.raises(LLMTimeoutError):
        p.structured(system="s", prompt="p", schema={})
    assert stub.models_called == [] and sleeps == []


def test_provider_does_not_sleep_past_the_deadline():
    p, stub, sleeps = provider([api_error(503), Resp()], max_attempts=3)
    p.deadline = time.monotonic() + 10.5  # enough for one call, not for 1 s backoff + another
    with pytest.raises(LLMUnavailableError):
        p.structured(system="s", prompt="p", schema={})
    assert len(stub.models_called) == 1 and sleeps == []


# ------------------------------------------------------------------ demo password
def basic(user: str, pw: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def test_demo_password_protects_everything_but_health(engine, tmp_path):
    c = client(engine, tmp_path, WEATHER_RISK_DEMO_PASSWORD="s3cret-demo")
    assert c.get("/api/health").status_code == 200  # platform health checks
    r = c.get("/api/overview")
    assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]
    assert c.get("/api/overview", headers=basic("moveo", "wrong")).status_code == 401
    assert c.get("/api/overview", headers={"Authorization": "Basic !!notb64"}).status_code == 401
    assert c.get("/api/overview", headers=basic("moveo", "s3cret-demo")).status_code == 200


def test_no_password_means_open(engine, tmp_path):
    assert client(engine, tmp_path).get("/api/overview").status_code == 200


# ------------------------------------------------------------------ frontend serving
def test_frontend_is_served_with_spa_fallback(engine, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>WeatherLens</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside")
    c = client(engine, tmp_path, WEATHER_RISK_WEB_DIST=str(dist))
    assert "WeatherLens" in c.get("/").text
    assert c.head("/").status_code == 200  # uptime monitors often use HEAD
    a = c.get("/assets/app.js")
    assert a.status_code == 200 and "immutable" in a.headers["cache-control"]
    assert "WeatherLens" in c.get("/analyst/deep/link").text  # refresh on a client route
    assert "outside" not in c.get("/../secret.txt").text
    assert c.get("/api/does-not-exist").status_code == 404  # API 404s are not masked
    assert c.get("/api/health").json()["status"] == "ok"
    assert c.get("/").headers["x-content-type-options"] == "nosniff"


# ------------------------------------------------------------------ sessions
def test_sessions_are_isolated_and_not_cached(engine, tmp_path):
    c = client(engine, tmp_path, FakeProvider(good_script(1)))
    r = c.post("/api/chat", json={"message": Q})
    sid = r.json()["session_id"]
    assert len(sid) >= 22  # 128-bit random capability token
    assert r.headers["cache-control"] == "no-store"
    h = c.get(f"/api/sessions/{sid}")
    assert h.status_code == 200 and h.headers["cache-control"] == "no-store"
    assert c.get("/api/sessions/someoneelse_000000000000").status_code == 404
    assert c.get("/api/sessions").status_code in (404, 405)  # no listing of sessions


def test_capped_call_deadline_never_goes_below_the_gemini_minimum():
    p, stub, _ = provider([Resp()])
    seen = []
    stub.generate_content = lambda **kw: (seen.append(kw["config"]), Resp())[1]
    p.deadline = time.monotonic() + 12  # less than the 45 s per-call timeout
    p.structured(system="s", prompt="p", schema={})
    timeout_ms = seen[0].http_options.timeout
    assert 10_000 <= timeout_ms <= 12_000


def test_climate_dataset_cache_is_bounded_and_results_unchanged(engine):
    from weather_risk.analytics.engine import CLIMATE_CACHE_MAX

    before = engine.rank_hubs().model_dump()
    for h in engine.catalog.hubs:  # touch every hub-decade dataset
        engine.climate_dataset(h, engine.climatology, engine.cfg.climate.source)
    assert len(engine._climate) <= CLIMATE_CACHE_MAX
    engine._profiles.clear()  # force recomputation from (re)loaded datasets
    assert engine.rank_hubs().model_dump() == before
