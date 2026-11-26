"""Gemini provider (official `google-genai` SDK).

- Automatic function calling is disabled: the server executes tools itself.
- Bounded timeout per request and bounded retries (with backoff) on timeouts / 429 / 5xx.
- Optional fallback model when the primary is overloaded (HTTP 503).
- The API key is read from settings (SecretStr) and never logged.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from weather_risk.agent.llm import (
    ChatMessage,
    LLMAuthError,
    LLMError,
    LLMNotConfiguredError,
    LLMQuotaError,
    LLMTimeoutError,
    LLMUnavailableError,
    StepResult,
    ToolCall,
    Usage,
)

log = logging.getLogger("weather_risk.llm")
MAX_RATE_LIMIT_WAIT_SECONDS = 20.0
MIN_CALL_SECONDS = 1.0  # never start a Gemini call with less time than this left
# A 429 whose retry hint exceeds this is a daily (not per-minute) quota: skip that model.
DAILY_QUOTA_HINT_SECONDS = 120.0


def _usage(resp: Any) -> Usage:
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        return Usage()
    return Usage(
        input_tokens=u.prompt_token_count or 0,
        output_tokens=u.candidates_token_count or 0,
        thinking_tokens=getattr(u, "thoughts_token_count", None) or 0,
    )


def _retry_delay_seconds(exc: Exception) -> float | None:
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", str(exc))
    return float(m.group(1)) if m else None


def _classify(exc: Exception) -> LLMError:
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        msg = f"Gemini API error {code}: {str(exc)[:200]}"
        if code in (401, 403):
            return LLMAuthError(f"Gemini rejected the API key or permissions (HTTP {code})")
        if code == 429:
            err = LLMQuotaError("Gemini quota or rate limit exceeded (HTTP 429)")
            err.retry_after = _retry_delay_seconds(exc)  # type: ignore[attr-defined]
            return err
        if code in (500, 502, 503, 504):
            return LLMUnavailableError(msg)
        if code == 400 and "API key" in str(exc):
            return LLMAuthError("Gemini rejected the API key (HTTP 400)")
        return LLMError(msg)
    name = type(exc).__name__.lower()
    if "timeout" in name or "timed out" in str(exc).lower():
        return LLMTimeoutError(f"Gemini request timed out: {type(exc).__name__}")
    if "connect" in name or "network" in name:
        return LLMUnavailableError(f"cannot reach Gemini: {type(exc).__name__}")
    return LLMError(f"unexpected Gemini error: {type(exc).__name__}")


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        fallback_model: str | None = None,
        timeout_seconds: float = 45.0,
        max_attempts: int = 2,
        temperature: float = 0.0,
        thinking_level: str | None = "low",
        sleep=time.sleep,
    ) -> None:
        if not api_key:
            raise LLMNotConfiguredError("GEMINI_API_KEY is not configured")
        self.model = model
        self.fallback_model = fallback_model
        # Fallback chain: primary first, then comma-separated fallbacks (deduplicated).
        chain = [model] + [m.strip() for m in (fallback_model or "").split(",") if m.strip()]
        self.models = list(dict.fromkeys(chain))
        self._thinking = (
            types.ThinkingConfig(thinking_level=thinking_level.upper()) if thinking_level else None
        )
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000))
        )
        self._max_attempts = max_attempts
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._sleep = sleep
        self.last_model_used: str | None = None
        # model -> monotonic time until which it is skipped (daily quota exhausted)
        self._exhausted_until: dict[str, float] = {}
        # Per-turn call log (reset by the orchestrator): one entry per HTTP attempt.
        self.call_log: list[dict[str, Any]] = []
        # Absolute time.monotonic() deadline for the current turn (set by the orchestrator).
        self.deadline: float | None = None

    # ----------------------------------------------------------------- call with retries
    def _call(
        self, contents: Any, config: types.GenerateContentConfig, phase: str = "llm"
    ) -> tuple[Any, float]:
        """Bounded fail-fast chain (Phase 5, D-037).

        Each round tries every model in the chain ONCE. Overload (503), timeouts and per-minute
        quota (429) move straight to the next model instead of retrying an overloaded one.
        After a failed round the whole chain is retried, up to `max_attempts` rounds, after a
        short backoff (honoring a capped server retry hint). Auth and non-retryable errors raise
        immediately. Worst case: len(chain) × max_attempts calls.
        """
        if self._thinking is not None and config.thinking_config is None:
            config = config.model_copy(update={"thinking_config": self._thinking})
        last: LLMError | None = None
        for round_no in range(1, self._max_attempts + 1):
            now = time.monotonic()
            available = [m for m in self.models if self._exhausted_until.get(m, 0) <= now]
            if not available:
                break
            last_hint: float | None = None
            for model in available:
                call_config = self._within_deadline(config, phase)
                t0 = time.perf_counter()
                try:
                    resp = self._client.models.generate_content(
                        model=model, contents=contents, config=call_config
                    )
                except Exception as exc:  # noqa: BLE001 - classified below
                    err = _classify(exc)
                    last = err
                    self.call_log.append({"phase": phase, "model": model, "attempt": round_no,
                                          "ok": False, "error": err.kind,
                                          "latency_ms": round((time.perf_counter() - t0) * 1000, 1)})  # fmt: skip
                    log.warning("llm_error", extra={"model": model, "kind": err.kind,
                                                    "round": round_no})  # fmt: skip
                    if isinstance(err, LLMAuthError | LLMNotConfiguredError):
                        raise err from None
                    if not (err.retryable or isinstance(err, LLMQuotaError)):
                        raise err from None
                    hint = getattr(err, "retry_after", None)
                    if isinstance(err, LLMQuotaError) and hint and hint > DAILY_QUOTA_HINT_SECONDS:
                        # daily quota: circuit-break this model, never wait for it
                        self._exhausted_until[model] = time.monotonic() + hint
                        self.call_log[-1]["error"] = "daily_quota_exhausted"
                    elif hint is not None:
                        last_hint = hint if last_hint is None else min(last_hint, hint)
                    continue
                latency = (time.perf_counter() - t0) * 1000
                self.last_model_used = model
                u = _usage(resp)
                self.call_log.append({"phase": phase, "model": model, "attempt": round_no,
                                      "ok": True, "latency_ms": round(latency, 1),
                                      "input_tokens": u.input_tokens,
                                      "output_tokens": u.output_tokens,
                                      "thinking_tokens": u.thinking_tokens,
                                      "model_version": getattr(resp, "model_version", None)})  # fmt: skip
                log.info("llm_call", extra={"model": model, "latency_ms": round(latency),
                                            "input_tokens": u.input_tokens,
                                            "output_tokens": u.output_tokens,
                                            "thinking_tokens": u.thinking_tokens,
                                            "round": round_no, "phase": phase})  # fmt: skip
                return resp, latency
            still_available = [
                m for m in self.models if self._exhausted_until.get(m, 0) <= time.monotonic()
            ]
            if round_no < self._max_attempts and still_available:
                delay = min(2 ** (round_no - 1), 8)
                if last_hint is not None:  # per-minute quota: honor the server hint (capped)
                    delay = min(max(delay, last_hint), MAX_RATE_LIMIT_WAIT_SECONDS)
                if self.deadline is not None and (
                    time.monotonic() + delay + MIN_CALL_SECONDS >= self.deadline
                ):
                    break  # no time left for another call after the wait
                self.call_log.append({"phase": phase, "wait_ms": round(delay * 1000),
                                      "reason": last.kind if last else "retry"})  # fmt: skip
                self._sleep(delay)
        if last is None:  # every model already circuit-broken: nothing was attempted
            raise LLMQuotaError("Gemini daily quota exhausted for all configured models")
        raise last

    def _within_deadline(self, config: types.GenerateContentConfig, phase: str):
        """Refuse to start a call after the turn deadline; cap the call timeout to what is left."""
        if self.deadline is None:
            return config
        remaining = self.deadline - time.monotonic()
        if remaining < MIN_CALL_SECONDS:
            self.call_log.append(
                {"phase": phase, "model": None, "ok": False, "error": "deadline_exceeded"}
            )
            raise LLMTimeoutError("request deadline reached before the AI call could start")
        if remaining < self._timeout_seconds:
            return config.model_copy(
                update={"http_options": types.HttpOptions(timeout=int(remaining * 1000))}
            )
        return config

    # ----------------------------------------------------------------- interface
    def tool_step(
        self, *, system: str, messages: list[ChatMessage], tools: list[dict[str, Any]]
    ) -> StepResult:
        contents: list[types.Content] = []
        for m in messages:
            if m.raw is not None:
                contents.append(m.raw)
            if m.tool_results:
                contents.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(name=call.name, response={"result": res})
                    for call, res in m.tool_results]))  # fmt: skip
            elif m.raw is None and m.text is not None:
                contents.append(
                    types.Content(role=m.role, parts=[types.Part.from_text(text=m.text)])
                )
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self._temperature,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t["name"],
                            description=t["description"],
                            parameters_json_schema=t["parameters"],
                        )
                        for t in tools
                    ]
                )
            ],  # fmt: skip
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")
            ),
        )
        resp, latency = self._call(contents, config, phase="tool_selection")
        calls = [ToolCall(name=fc.name, args=dict(fc.args or {}), id=getattr(fc, "id", None))
                 for fc in (resp.function_calls or [])]  # fmt: skip
        raw = resp.candidates[0].content if resp.candidates else None
        text = None
        if not calls:
            try:
                text = resp.text
            except (ValueError, AttributeError):
                text = None
        return StepResult(text=text, tool_calls=calls, usage=_usage(resp), latency_ms=latency,
                          model_version=getattr(resp, "model_version", None), raw=raw)  # fmt: skip

    def structured(
        self, *, system: str, prompt: str, schema: dict[str, Any]
    ) -> tuple[str, Usage, float, str | None]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self._temperature,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        resp, latency = self._call(prompt, config, phase="synthesis")
        try:
            text = resp.text or ""
        except (ValueError, AttributeError):
            text = ""
        return text, _usage(resp), latency, getattr(resp, "model_version", None)
