"""Deterministic, scripted LLM provider for OFFLINE TESTS ONLY.

It is never selected implicitly: responses produced with it are labeled provider="fake".
A script is a list of steps consumed in order:
  ("tools", [ToolCall, ...])   -> tool_step returns these calls
  ("text", "...")              -> tool_step returns plain text (ends the tool phase)
  ("json", "..." | dict)        -> structured returns this JSON text
  ("raise", LLMError(...))     -> the next call raises
"""

from __future__ import annotations

import json
from typing import Any

from weather_risk.agent.llm import ChatMessage, LLMError, StepResult, ToolCall, Usage


class FakeProvider:
    name = "fake"

    def __init__(self, script: list[tuple[str, Any]], model: str = "fake-scripted") -> None:
        self.model = model
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def _next(self, expected: tuple[str, ...]) -> tuple[str, Any]:
        if not self.script:
            raise AssertionError("fake script exhausted")
        kind, value = self.script.pop(0)
        if kind == "raise":
            assert isinstance(value, LLMError)
            raise value
        if kind not in expected:
            raise AssertionError(f"fake script expected {expected}, got {kind}")
        return kind, value

    def tool_step(self, *, system: str, messages: list[ChatMessage], tools: list[dict[str, Any]]):
        self.calls.append({"type": "tool_step", "system": system, "messages": messages,
                           "tools": [t["name"] for t in tools]})  # fmt: skip
        kind, value = self._next(("tools", "text"))
        if kind == "tools":
            calls = [
                c if isinstance(c, ToolCall) else ToolCall(name=c[0], args=c[1]) for c in value
            ]
            return StepResult(text=None, tool_calls=calls, usage=Usage(10, 5, 0), latency_ms=1.0,
                              model_version=self.model)  # fmt: skip
        return StepResult(text=value, tool_calls=[], usage=Usage(10, 5, 0), latency_ms=1.0,
                          model_version=self.model)  # fmt: skip

    def structured(self, *, system: str, prompt: str, schema: dict[str, Any]):
        self.calls.append({"type": "structured", "system": system, "prompt": prompt})
        _, value = self._next(("json",))
        text = value if isinstance(value, str) else json.dumps(value)
        return text, Usage(20, 30, 0), 1.0, self.model
