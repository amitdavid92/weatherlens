"""Explicit JSON schemas.

`LLMAnswer`   — the structured output the LLM MUST return (provider-native JSON schema + Pydantic
                validation). Narrative may reference numbers only via {{fact:<id>}} placeholders.
`ChatResponse` — the API contract. The LLM narrative is kept separate from the authoritative
                analytical payloads produced by the deterministic engine.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AnswerStatus = Literal["answered", "needs_clarification", "unsupported", "insufficient_data"]
Intent = Literal[
    "rank", "compare", "weather_stat", "explain", "profile", "list_hubs", "clarify", "other"
]


class CitedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_id: str = Field(..., description="Exact fact id from the tool results.")
    hub_id: str | None = Field(..., description="Hub the fact describes (null for multi-hub).")


class LLMAnswer(BaseModel):
    """Structured output contract between the LLM and the application."""

    model_config = ConfigDict(extra="forbid")

    status: AnswerStatus
    intent: Intent
    narrative: str = Field(..., max_length=4000, description=(
        "Markdown answer. EVERY number, percentage, score, rank, count, date or year from the "
        "data MUST be written as {{fact:<fact_id>}}; never type digits from tool results."))  # fmt: skip
    cited_facts: list[CitedFact] = Field(default_factory=list, max_length=60)
    resolved_hubs: list[str] = Field(default_factory=list, max_length=12)
    resolved_hazards: list[str] = Field(default_factory=list, max_length=5)
    resolved_metric: str | None = None
    resolved_period: str | None = None
    premise_correction: str | None = Field(None, max_length=600, description=(
        "Required when a tool's premise_check says the user's claim is not supported."))  # fmt: skip
    clarification_question: str | None = Field(None, max_length=300)
    follow_up_suggestions: list[str] = Field(default_factory=list, max_length=3)


# --------------------------------------------------------------------------- API models


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ToolCallRecord(BaseModel):
    name: str
    args: dict[str, Any]
    ok: bool
    error: str | None = None
    error_type: str | None = None
    latency_ms: float


class ValidationReport(BaseModel):
    valid: bool
    attempts: int
    issues: list[str] = Field(default_factory=list)  # unresolved issues of the final attempt
    retry_reasons: list[str] = Field(default_factory=list)  # issues that triggered the retry
    fallback_used: bool = False


class AgentInfo(BaseModel):
    provider: str  # "gemini" or "fake" (tests only; never presented as the real agent)
    model: str
    model_version: str | None = None
    iterations: int
    tool_calls: list[ToolCallRecord]
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    latency_ms: float


class Resolved(BaseModel):
    hubs: list[str] = Field(default_factory=list)
    hazards: list[str] = Field(default_factory=list)
    metric: str | None = None
    period: str | None = None


class Analysis(BaseModel):
    """Authoritative deterministic payloads (from the engine), keyed by result type."""

    rankings: list[dict[str, Any]] = Field(default_factory=list)
    comparisons: list[dict[str, Any]] = Field(default_factory=list)
    weather_stats: list[dict[str, Any]] = Field(default_factory=list)
    explanations: list[dict[str, Any]] = Field(default_factory=list)
    profiles: list[dict[str, Any]] = Field(default_factory=list)
    hubs: list[dict[str, Any]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: str
    turn: int
    status: Literal[
        "answered", "needs_clarification", "unsupported", "insufficient_data", "fallback", "error"
    ]
    intent: str
    answer: str  # rendered narrative (placeholders replaced deterministically)
    narrative_source: Literal["llm", "deterministic_fallback", "none"]
    premise_correction: str | None = None
    clarification_question: str | None = None
    resolved: Resolved
    facts: list[dict[str, Any]]  # verified facts cited in the answer
    analysis: Analysis
    sources: list[dict[str, Any]]
    data_freshness: dict[str, list[str]]  # source -> freshness labels seen
    methodology_version: str
    assumptions: list[str]
    limitations: list[str]
    follow_up_suggestions: list[str]
    validation: ValidationReport
    agent: AgentInfo


class ErrorResponse(BaseModel):
    error: str
    detail: str
    retryable: bool = False
