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
        max_attempts: int = 3,
        temperature: float = 0.0,
        sleep=time.sleep,
    ) -> None:
        if not api_key:
            raise LLMNotConfiguredError("GEMINI_API_KEY is not configured")
        self.model = model
        self.fallback_model = fallback_model
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000))
        )
        self._max_attempts = max_attempts
        self._temperature = temperature
        self._sleep = sleep
        self.last_model_used: str | None = None

    # ----------------------------------------------------------------- call with retries
    def _call(self, contents: Any, config: types.GenerateContentConfig) -> tuple[Any, float]:
        models = [self.model] + ([self.fallback_model] if self.fallback_model else [])
        last: LLMError | None = None
        for model in models:
            for attempt in range(1, self._max_attempts + 1):
                t0 = time.perf_counter()
                try:
                    resp = self._client.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                    latency = (time.perf_counter() - t0) * 1000
                    self.last_model_used = model
                    u = _usage(resp)
                    log.info("llm_call", extra={"model": model, "latency_ms": round(latency),
                                                "input_tokens": u.input_tokens,
                                                "output_tokens": u.output_tokens,
                                                "thinking_tokens": u.thinking_tokens,
                                                "attempt": attempt})  # fmt: skip
                    return resp, latency
                except Exception as exc:  # noqa: BLE001 - classified below
                    err = _classify(exc)
                    last = err
                    log.warning("llm_error", extra={"model": model, "kind": err.kind,
                                                    "attempt": attempt})  # fmt: skip
                    if isinstance(err, LLMAuthError | LLMNotConfiguredError):
                        raise err from None
                    if not (err.retryable or isinstance(err, LLMQuotaError)):
                        raise err from None
                    if attempt < self._max_attempts:
                        delay = min(2 ** (attempt - 1), 8)
                        hint = getattr(err, "retry_after", None)
                        if hint is not None:  # per-minute quota: honor the server hint (capped)
                            delay = min(max(delay, hint), MAX_RATE_LIMIT_WAIT_SECONDS)
                        self._sleep(delay)
            # retries exhausted on this model -> try fallback only for overload/timeouts
            if not isinstance(last, LLMUnavailableError | LLMTimeoutError):
                break
        assert last is not None
        raise last

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
        resp, latency = self._call(contents, config)
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
        resp, latency = self._call(prompt, config)
        try:
            text = resp.text or ""
        except (ValueError, AttributeError):
            text = ""
        return text, _usage(resp), latency, getattr(resp, "model_version", None)
