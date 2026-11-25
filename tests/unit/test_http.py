from __future__ import annotations

import httpx
import pytest
import respx

from weather_risk.data.errors import RateLimitedError, SourceHTTPError, SourceTimeoutError
from weather_risk.data.http import HttpFetcher, SourceRequest

URL = "https://example.test/api"
REQ = SourceRequest(source_id="test", url=URL, params={"a": "1"})


def fetcher(sleeps: list[float], attempts: int = 3) -> HttpFetcher:
    return HttpFetcher(max_attempts=attempts, backoff_base_seconds=0.5, sleep=sleeps.append)


@respx.mock
def test_success_first_try():
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"[1]"))
    sleeps: list[float] = []
    resp = fetcher(sleeps).get(REQ)
    assert resp.body == b"[1]" and sleeps == []


@respx.mock
def test_retries_5xx_then_succeeds_with_exponential_backoff():
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200, content=b"ok")]
    )
    sleeps: list[float] = []
    assert fetcher(sleeps).get(REQ).body == b"ok"
    assert route.call_count == 3
    assert sleeps == [0.5, 1.0]


@respx.mock
def test_timeouts_are_bounded_and_typed():
    route = respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    sleeps: list[float] = []
    with pytest.raises(SourceTimeoutError):
        fetcher(sleeps).get(REQ)
    assert route.call_count == 3
    assert len(sleeps) == 2  # no sleep after the final attempt


@respx.mock
def test_rate_limit_honours_retry_after_capped():
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(429, headers={"Retry-After": "999"}),
            httpx.Response(429),
        ]
    )
    sleeps: list[float] = []
    with pytest.raises(RateLimitedError):
        fetcher(sleeps).get(REQ)
    assert sleeps == [2.0, 30.0]


@respx.mock
def test_client_errors_are_not_retried():
    route = respx.get(URL).mock(return_value=httpx.Response(400, text="bad params"))
    with pytest.raises(SourceHTTPError) as exc:
        fetcher([]).get(REQ)
    assert exc.value.status_code == 400
    assert route.call_count == 1


@respx.mock
def test_transport_errors_are_retried_then_typed():
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("reset"))
    with pytest.raises(SourceHTTPError):
        fetcher([], attempts=2).get(REQ)
    assert route.call_count == 2


def test_request_key_is_deterministic_and_param_order_independent():
    a = SourceRequest(source_id="s", url=URL, params={"x": "1", "y": "2"})
    b = SourceRequest(source_id="s", url=URL, params={"y": "2", "x": "1"})
    c = SourceRequest(source_id="s", url=URL, params={"x": "1", "y": "3"})
    assert a.key == b.key != c.key
    assert len(a.key) == 64
