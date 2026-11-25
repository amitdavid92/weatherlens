"""Per-turn registry of verified facts produced by tools.

Every number the agent may state is registered here with its owner (hub), topic (hazard/metric),
period and sources. The LLM references facts by id (`{{fact:<id>}}`); the server renders values
deterministically and checks attribution.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from weather_risk.analytics.formatting import format_value


class VerifiedFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    fact_id: str
    label: str
    value: float | int | str | bool | None
    display: str
    unit: str | None = None
    kind: str
    hub_id: str | None  # owner hub; None for multi-hub facts (e.g. differences)
    topic: str | None = None  # hazard / metric / "overall"
    period: str | None = None
    source_ids: list[str] = []
    status: str = "ok"
    tool: str


class FactRegistry:
    def __init__(self) -> None:
        self._facts: dict[str, VerifiedFact] = {}

    def add(
        self,
        fact_id: str,
        *,
        label: str,
        value: float | int | str | bool | None,
        kind: str,
        tool: str,
        unit: str | None = None,
        hub_id: str | None = None,
        topic: str | None = None,
        period: str | None = None,
        source_ids: list[str] | None = None,
        status: str = "ok",
        display: str | None = None,
    ) -> dict:
        """Register a fact and return the compact reference shown to the LLM."""
        if display is None:
            display = format_value(value if not isinstance(value, bool) else str(value).lower(),
                                   unit, kind)  # fmt: skip
        fact = VerifiedFact(
            fact_id=fact_id, label=label, value=value, display=display, unit=unit, kind=kind,
            hub_id=hub_id, topic=topic, period=period, source_ids=source_ids or [],
            status=status, tool=tool,
        )  # fmt: skip
        existing = self._facts.get(fact_id)
        if existing is not None and existing.display != display:
            raise ValueError(f"conflicting values registered for fact {fact_id}")
        self._facts[fact_id] = fact
        ref: dict = {"fact": fact_id, "value": display}
        if unit and unit not in ("%", "index 0–100"):
            ref["unit"] = unit
        return ref

    def get(self, fact_id: str) -> VerifiedFact | None:
        return self._facts.get(fact_id)

    def __contains__(self, fact_id: str) -> bool:
        return fact_id in self._facts

    def __len__(self) -> int:
        return len(self._facts)

    def all(self) -> list[VerifiedFact]:
        return list(self._facts.values())
