"""Small LLM provider interface + typed errors.

Two calls are needed by the agent:
  - `tool_step`: conversation + tool declarations -> either tool calls or plain text
  - `structured`: prompt + JSON schema -> JSON text (provider-native structured output)
Kept separate on purpose: on the real Gemini API, combining tools and a response schema in one
call made the model skip tool calls (verified 2026-11-25), so synthesis is a second call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    kind = "provider_error"
    retryable = False


class LLMAuthError(LLMError):
    kind = "auth_error"


class LLMQuotaError(LLMError):
    kind = "quota_exceeded"


class LLMTimeoutError(LLMError):
    kind = "timeout"
    retryable = True


class LLMUnavailableError(LLMError):
    kind = "unavailable"
    retryable = True


class LLMNotConfiguredError(LLMError):
    kind = "not_configured"


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.thinking_tokens += other.thinking_tokens


@dataclass
class StepResult:
    text: str | None
    tool_calls: list[ToolCall]
    usage: Usage
    latency_ms: float
    model_version: str | None = None
    raw: Any = None  # provider-native content, echoed back into the conversation


@dataclass
class ChatMessage:
    role: str  # "user" | "model"
    text: str | None = None
    raw: Any = None  # provider-native content (preferred when present)
    tool_results: list[tuple[ToolCall, dict]] = field(default_factory=list)


class LLMProvider(Protocol):
    name: str
    model: str

    def tool_step(
        self, *, system: str, messages: list[ChatMessage], tools: list[dict[str, Any]]
    ) -> StepResult: ...

    def structured(
        self, *, system: str, prompt: str, schema: dict[str, Any]
    ) -> tuple[str, Usage, float, str | None]: ...
