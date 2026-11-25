"""GeminiProvider error handling and retries, offline (the SDK call is stubbed)."""

from __future__ import annotations

import httpx
import pytest
from google.genai import errors as genai_errors

from weather_risk.agent.gemini import GeminiProvider, _classify
from weather_risk.agent.llm import (
    LLMAuthError,
    LLMNotConfiguredError,
    LLMQuotaError,
    LLMTimeoutError,
    LLMUnavailableError,
)


def api_error(code: int, message: str = "x", extra: str = ""):
    cls = genai_errors.ClientError if code < 500 else genai_errors.ServerError
    return cls(code, {"error": {"code": code, "message": message + extra, "status": "S"}})


def test_missing_key_is_not_configured():
    with pytest.raises(LLMNotConfiguredError):
        GeminiProvider(api_key=None, model="m")


@pytest.mark.parametrize(
    "exc,kind",
    [(api_error(401), LLMAuthError), (api_error(403), LLMAuthError),
     (api_error(400, "API key not valid"), LLMAuthError), (api_error(429), LLMQuotaError),
     (api_error(503), LLMUnavailableError), (api_error(500), LLMUnavailableError),
     (httpx.ReadTimeout("slow"), LLMTimeoutError), (httpx.ConnectError("no"), LLMUnavailableError)],
)  # fmt: skip
def test_error_classification(exc, kind):
    assert isinstance(_classify(exc), kind)


def test_quota_retry_delay_is_parsed():
    err = _classify(api_error(429, "quota", ' "retryDelay": "17s"'))
    assert err.retry_after == 17.0


class StubModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.models_called: list[str] = []

    def generate_content(self, *, model, contents, config):
        self.models_called.append(model)
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


def provider(outcomes, **kw):
    sleeps: list[float] = []
    p = GeminiProvider(api_key="test-key-not-real", model="primary", sleep=sleeps.append, **kw)
    stub = StubModels(outcomes)
    p._client = type("C", (), {"models": stub})()
    return p, stub, sleeps


class Resp:
    text = '{"ok": true}'
    usage_metadata = None
    model_version = "primary-001"
    candidates = []
    function_calls = None


def test_bounded_retries_then_success():
    p, stub, sleeps = provider([api_error(503), api_error(503), Resp()], max_attempts=3)
    text, *_ = p.structured(system="s", prompt="p", schema={})
    assert text == '{"ok": true}' and len(stub.models_called) == 3 and sleeps == [1, 2]


def test_fallback_model_on_overload():
    p, stub, _ = provider([api_error(503), api_error(503), Resp()], max_attempts=2,
                          fallback_model="fallback")  # fmt: skip
    p.structured(system="s", prompt="p", schema={})
    assert stub.models_called == ["primary", "primary", "fallback"]


def test_auth_error_not_retried():
    p, stub, _ = provider([api_error(401)], max_attempts=3, fallback_model="fallback")
    with pytest.raises(LLMAuthError):
        p.structured(system="s", prompt="p", schema={})
    assert stub.models_called == ["primary"]


def test_quota_retries_with_capped_server_hint_then_raises():
    hint = ' "retryDelay": "45s"'
    p, stub, sleeps = provider([api_error(429, "q", hint)] * 2, max_attempts=2,
                               fallback_model="fallback")  # fmt: skip
    with pytest.raises(LLMQuotaError):
        p.structured(system="s", prompt="p", schema={})
    assert sleeps == [20.0] and stub.models_called == ["primary", "primary"]  # no fallback on 429
