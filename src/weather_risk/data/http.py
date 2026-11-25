"""HTTP access with timeouts, bounded retries/backoff and typed errors.

Every external request is described by a `SourceRequest`, whose deterministic `key` is shared by
the SQLite cache and the committed snapshot.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

from weather_risk.data.errors import (
    RateLimitedError,
    SourceHTTPError,
    SourceTimeoutError,
)

log = logging.getLogger("weather_risk.http")

USER_AGENT = "weather-risk-take-home/0.1 (+research; no contact)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_SECONDS = 30.0


@dataclass(frozen=True)
class SourceRequest:
    source_id: str
    url: str
    params: dict[str, str] = field(default_factory=dict)
    # Free-form metadata used for snapshot manifests (not part of the key).
    location_id: str | None = None
    period: tuple[str, str] | None = None

    @property
    def key(self) -> str:
        canonical = json.dumps(
            {"source": self.source_id, "url": self.url, "params": sorted(self.params.items())},
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def full_url(self) -> str:
        return str(httpx.URL(self.url, params=self.params))


@dataclass
class HttpResponse:
    status_code: int
    body: bytes
    elapsed_ms: float
    headers: dict[str, str]


class HttpFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        backoff_base_seconds: float = 0.5,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._client = client or httpx.Client(
            timeout=timeout_seconds, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._max_attempts = max_attempts
        self._backoff = backoff_base_seconds
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def get(self, req: SourceRequest) -> HttpResponse:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            t0 = time.perf_counter()
            try:
                resp = self._client.get(req.url, params=req.params)
            except httpx.TimeoutException as exc:
                last_exc = SourceTimeoutError(req.source_id, f"timeout: {exc}")
                self._log_retry(req, attempt, "timeout")
                self._backoff_sleep(attempt, None)
                continue
            except httpx.TransportError as exc:
                last_exc = SourceHTTPError(req.source_id, 0, f"transport error: {exc}")
                self._log_retry(req, attempt, f"transport:{type(exc).__name__}")
                self._backoff_sleep(attempt, None)
                continue

            elapsed = (time.perf_counter() - t0) * 1000
            if resp.status_code in RETRYABLE_STATUS:
                if resp.status_code == 429:
                    last_exc = RateLimitedError(req.source_id, "rate limited (HTTP 429)")
                else:
                    last_exc = SourceHTTPError(req.source_id, resp.status_code, resp.text[:200])
                self._log_retry(req, attempt, f"http_{resp.status_code}")
                self._backoff_sleep(attempt, resp.headers.get("Retry-After"))
                continue
            if resp.status_code >= 400:
                # Non-retryable client error (bad params etc.).
                raise SourceHTTPError(req.source_id, resp.status_code, resp.text[:300])

            log.info(
                "http_ok",
                extra={
                    "source": req.source_id,
                    "status": resp.status_code,
                    "duration_ms": round(elapsed, 1),
                    "bytes": len(resp.content),
                    "attempt": attempt,
                },
            )
            return HttpResponse(
                status_code=resp.status_code,
                body=resp.content,
                elapsed_ms=elapsed,
                headers={k.lower(): v for k, v in resp.headers.items()},
            )

        assert last_exc is not None
        log.warning("http_failed", extra={"source": req.source_id, "error": str(last_exc)})
        raise last_exc

    def _backoff_sleep(self, attempt: int, retry_after: str | None) -> None:
        if attempt >= self._max_attempts:
            return
        delay = self._backoff * (2 ** (attempt - 1))
        if retry_after:
            with contextlib.suppress(ValueError):
                delay = max(delay, min(float(retry_after), MAX_RETRY_AFTER_SECONDS))
        self._sleep(delay)

    @staticmethod
    def _log_retry(req: SourceRequest, attempt: int, reason: str) -> None:
        log.warning(
            "http_retry", extra={"source": req.source_id, "attempt": attempt, "reason": reason}
        )
