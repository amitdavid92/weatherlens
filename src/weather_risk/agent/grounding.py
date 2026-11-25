"""Grounding validation of LLM answers + deterministic rendering.

Primary control: the LLM writes numbers only as {{fact:<id>}} placeholders, which the server
renders from the per-turn FactRegistry. Validation then checks:
  1. every placeholder / cited fact exists in THIS turn's registry;
  2. attribution: a cited fact's hub matches the cited hub, and a placeholder never sits in a
     sentence that names other hubs but not the fact's owner (e.g. Houston's score in a
     sentence about Miami);
  3. no stray numbers: digits outside placeholders are rejected unless they are small counts
     (1–12), years of the resolved period/question, or literal constants from tool definitions;
  4. superlatives ("highest", "most exposed", ...) about a single hub must match a rank-1 entry
     or a comparison leader from the engine;
  5. a premise the engine marked unsupported must be corrected (premise_correction);
  6. resolved hubs must be catalog ids; analytical intents must cite at least one fact.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from weather_risk.agent.facts import FactRegistry
from weather_risk.agent.schema import LLMAnswer
from weather_risk.agent.tools import ToolExecution
from weather_risk.catalog import HubCatalog

PLACEHOLDER = re.compile(r"\{\{\s*fact:\s*([A-Za-z0-9_.\-]+)\s*\}\}")
NUMBER = re.compile(r"(?<![A-Za-z_])\d+(?:[.,]\d+)?\s*%?")
SUPERLATIVE = re.compile(
    r"\b(highest|most exposed|greatest|largest exposure|top[- ]ranked|ranks? first|"
    r"ranked first|number one|#1|leads?)\b",
    re.IGNORECASE,
)
# Narrative sentences: only explicit negation exempts a superlative from the winner check.
NEGATION = re.compile(r"\bnot\b|n't\b", re.IGNORECASE)
# premise_correction sentences restate the user's claim in order to reject it ("the premise that
# X is the most exposed is incorrect"), so correction vocabulary also counts there — and only there.
CORRECTION = re.compile(
    r"\b(not|no|never|incorrect|false|untrue|unsupported|contrary|premise|claim)\b|n't\b",
    re.IGNORECASE,
)
ANALYTICAL_INTENTS = {"rank", "compare", "weather_stat", "explain", "profile"}


def render(narrative: str, registry: FactRegistry) -> tuple[str, list[str]]:
    """Replace placeholders with deterministic displays; return (text, used fact ids)."""
    used: list[str] = []

    def sub(m: re.Match) -> str:
        fid = m.group(1)
        fact = registry.get(fid)
        if fact is None:
            return "[unverified]"
        if fid not in used:
            used.append(fid)
        return fact.display

    return PLACEHOLDER.sub(sub, narrative), used


def _hub_patterns(catalog: HubCatalog) -> dict[str, re.Pattern]:
    pats = {}
    for h in catalog.hubs:
        names = {h.city, h.display_name, h.id, h.id.replace("_", " ")}
        alts = "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True))
        pats[h.id] = re.compile(rf"(?<![A-Za-z]){alts}(?![A-Za-z])", re.IGNORECASE)
    return pats


def _strings(obj: Any) -> Iterable[str]:
    """All free-text strings in tool payloads, EXCLUDING fact references (no copyable values)."""
    if isinstance(obj, dict):
        if "fact" in obj and "value" in obj:
            return
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, str):
        yield obj


def _allowed_numbers(execs: list[ToolExecution], registry: FactRegistry, user: str) -> set[str]:
    allowed: set[str] = set()
    for text in [user, *(s for e in execs for s in _strings(e.payload))]:
        allowed |= {n.strip().rstrip("%").strip() for n in NUMBER.findall(text)}
    for f in registry.all():
        for text in (f.period or "", f.label):
            allowed |= set(re.findall(r"\b(?:19|20)\d{2}\b", text))
    return allowed


def _sentences(text: str) -> list[str]:
    # protect placeholders (they contain dots) before splitting
    tokens: list[str] = []

    def protect(m: re.Match) -> str:
        tokens.append(m.group(0))
        return f"\u0000{len(tokens) - 1}\u0000"

    protected = PLACEHOLDER.sub(protect, text)
    parts = re.split(r"(?<=[.!?])\s+|\n+", protected)
    out = []
    for p in parts:
        out.append(re.sub(r"\u0000(\d+)\u0000", lambda m: tokens[int(m.group(1))], p))
    return [s for s in out if s.strip()]


HAZARD_WORDS = {
    "winter": r"winter|snow|ice|freez|cold",
    "hurricane": r"hurrican",
    "flood": r"flood",
    "severe_convective": r"severe|convective|tornado|hail|thunderstorm|wind",
    "extreme_heat": r"heat|hot",
}


def _winners_by_topic(execs: list[ToolExecution]) -> dict[str, set[str]]:
    """Hubs that are rank #1 / comparison leader, per topic (hazard or 'overall')."""
    winners: dict[str, set[str]] = {}
    for e in execs:
        if not e.ok:
            continue
        if e.name == "rank_hubs":
            for item in e.payload.get("ranked", []):
                if item.get("rank", {}).get("value") == "#1":
                    winners.setdefault(e.payload.get("hazard", "overall"), set()).add(
                        item["hub"]["hub_id"]
                    )
        elif e.name == "compare_hubs":
            for row in e.payload.get("rows", []):
                if row.get("leader"):
                    winners.setdefault(row["hazard"], set()).add(row["leader"])
        elif (
            e.name == "explain_hub_score" and e.payload.get("rank_overall", {}).get("value") == "#1"
        ):
            winners.setdefault("overall", set()).add(e.payload["hub"]["hub_id"])
    return winners


def validate(
    answer: LLMAnswer,
    *,
    registry: FactRegistry,
    catalog: HubCatalog,
    executions: list[ToolExecution],
    user_message: str,
) -> list[str]:
    issues: list[str] = []
    ids = set(catalog.ids)
    # Claims = narrative + premise correction + clarification question: fully validated.
    # Follow-up suggestions are questions (they may legitimately mention other years), so only
    # their placeholders are checked for existence.
    claims_text = "\n".join(
        [answer.narrative, answer.premise_correction or "", answer.clarification_question or ""]
    )
    full_text = "\n".join([claims_text, *answer.follow_up_suggestions])

    # 1. existence
    placeholders = PLACEHOLDER.findall(full_text)
    for fid in placeholders:
        if fid not in registry:
            issues.append(f"unknown fact id in narrative: {fid}")
    for c in answer.cited_facts:
        f = registry.get(c.fact_id)
        if f is None:
            issues.append(f"cited fact does not exist: {c.fact_id}")
        elif f.hub_id is not None and c.hub_id is not None and c.hub_id != f.hub_id:
            issues.append(f"fact {c.fact_id} describes {f.hub_id} but was cited for {c.hub_id}")

    # 2. sentence-level attribution
    pats = _hub_patterns(catalog)
    for sentence in _sentences(claims_text):
        mentioned = {hid for hid, p in pats.items() if p.search(PLACEHOLDER.sub(" ", sentence))}
        if not mentioned:
            continue
        for fid in PLACEHOLDER.findall(sentence):
            f = registry.get(fid)
            if f is not None and f.hub_id is not None and f.hub_id not in mentioned:
                issues.append(
                    f"attribution: fact {fid} belongs to {f.hub_id} but the sentence mentions "
                    f"{sorted(mentioned)}"
                )

    # 3. stray numbers
    stripped = PLACEHOLDER.sub(" ", claims_text)
    stripped = re.sub(r"^\s*(?:\d+[.)]|[-*])\s+", " ", stripped, flags=re.MULTILINE)  # list markers
    allowed = _allowed_numbers(executions, registry, user_message)
    for raw in NUMBER.findall(stripped):
        n = raw.strip()
        bare = n.rstrip("%").strip()
        if "%" not in n and bare.isdigit() and 0 <= int(bare) <= 12:
            continue
        if bare in allowed and "%" not in n:
            continue
        # Targeted correction: name the fact(s) that hold this exact value, if any.
        matches = [f.fact_id for f in registry.all() if f.display.rstrip("%").strip() == bare][:2]
        hint = (" — write it as " + " or ".join(f"{{{{fact:{m}}}}}" for m in matches)
                if matches else "")  # fmt: skip
        issues.append(f"unsupported numeric claim '{n}' (numbers must use fact placeholders){hint}")

    # 4. superlatives
    winners_by_topic = _winners_by_topic(executions)
    has_ordering = any(e.ok and e.name in ("rank_hubs", "compare_hubs") for e in executions)
    if has_ordering:
        narrative_text = "\n".join([answer.narrative, answer.clarification_question or ""])
        checked = [(s, NEGATION) for s in _sentences(narrative_text)]
        checked += [(s, CORRECTION) for s in _sentences(answer.premise_correction or "")]
        for sentence, exempt in checked:
            clean = PLACEHOLDER.sub(" ", sentence)
            if not SUPERLATIVE.search(clean) or exempt.search(clean):
                continue
            mentioned = [hid for hid, p in pats.items() if p.search(clean)]
            if len(mentioned) != 1:
                continue
            topics = [t for t, rx in HAZARD_WORDS.items() if re.search(rx, clean, re.IGNORECASE)]
            pool = (set().union(*(winners_by_topic.get(t, set()) for t in topics)) if topics
                    else set().union(*winners_by_topic.values()) if winners_by_topic else set())  # fmt: skip
            if mentioned[0] not in pool:
                issues.append(
                    f"superlative claim about {mentioned[0]} is not supported by the ranking or "
                    f"comparison leader for {', '.join(topics) or 'any topic'}"
                )

    # 5. premise
    for e in executions:
        pc = e.payload.get("premise_check") if e.ok else None
        if pc and pc.get("supported") is False and not (answer.premise_correction or "").strip():
            issues.append("the user's premise is not supported by the engine; premise_correction "
                          "is required")  # fmt: skip

    # 6. resolution + citations
    bad = [h for h in answer.resolved_hubs if h not in ids]
    if bad:
        issues.append(f"resolved_hubs must be catalog hub ids; got {bad}")
    if (answer.status == "answered" and answer.intent in ANALYTICAL_INTENTS
            and not PLACEHOLDER.findall(answer.narrative)):  # fmt: skip
        issues.append("an analytical answer must reference facts via {{fact:...}} placeholders")
    if answer.status == "answered" and not any(e.ok for e in executions):
        issues.append("status 'answered' requires at least one successful tool result")
    if answer.status == "needs_clarification" and not (answer.clarification_question or ""):
        issues.append("needs_clarification requires clarification_question")
    return sorted(set(issues), key=issues.index)


# --------------------------------------------------------------------------- fallback


def deterministic_summary(executions: list[ToolExecution]) -> str:
    """Narrative with placeholders built ONLY from tool payloads (used when the LLM fails)."""
    lines: list[str] = []
    for e in executions:
        if not e.ok:
            lines.append(f"- `{e.name}` could not be completed: {e.error}")
            continue
        p = e.payload
        if e.name == "rank_hubs":
            scope = p["hazard"] + (f" in the {p['region']}" if p.get("region") else "")
            lines.append(f"**Ranking by {scope}:**")
            for item in p["ranked"]:
                lines.append(f"- {{{{fact:{item['rank']['fact']}}}}} {item['hub']['name']}: "
                             f"{{{{fact:{item['score']['fact']}}}}} ({item['band']})")  # fmt: skip
            for item in p["not_ranked"]:
                if "available_weight" in item:
                    lines.append(
                        f"- not ranked: {item['hub']['name']} — its "
                        f"{item['incomplete_hazard'].replace('_', ' ')} data is incomplete "
                        f"({{{{fact:{item['available_weight']['fact']}}}}} of the indicator weight "
                        "available), so its score is shown but not ranked."
                    )  # fmt: skip
                else:
                    lines.append(f"- not ranked: {item['hub']['name']} (incomplete data)")
        elif e.name == "compare_hubs":
            for row in p["rows"]:
                parts = [f"{hid}: {{{{fact:{ref['fact']}}}}}" for hid, ref in row["scores"].items()]
                lead = f"; higher: {row['leader']}" if row.get("leader") else ""
                lines.append(f"- **{row['hazard']}** — " + ", ".join(parts) + lead)
        elif e.name == "get_weather_stat":
            if p["status"] != "ok":
                lines.append(f"- {p['hub']['name']}: {p['definition']} — insufficient "
                             f"observation coverage ({{{{fact:{p['coverage']['fact']}}}}}); "
                             "no value is reported.")  # fmt: skip
            else:
                miss = (f"; missing: {{{{fact:{p['missing_dates']['fact']}}}}}"
                        if "missing_dates" in p else "")  # fmt: skip
                lines.append(
                    f"- {p['hub']['name']}, {{{{fact:{p['period']['fact']}}}}}: {p['definition']} "
                    f"on {{{{fact:{p['percent_of_valid_days']['fact']}}}}} of valid days "
                    f"({{{{fact:{p['event_days']['fact']}}}}} of {{{{fact:{p['valid_days']['fact']}}}}}"
                    f"; {{{{fact:{p['missing_days']['fact']}}}}} without a value{miss})."
                )  # fmt: skip
        elif e.name == "explain_hub_score":
            drivers = ", ".join(f"{h['hazard']} {{{{fact:{h['score']['fact']}}}}}"
                                for h in p["hazards_by_contribution"][:3])  # fmt: skip
            rank = (f", rank {{{{fact:{p['rank_overall']['fact']}}}}}"
                    if "rank_overall" in p else "")  # fmt: skip
            lines.append(f"- {p['hub']['name']}: overall {{{{fact:{p['overall']['fact']}}}}} "
                         f"({p['overall_band']}){rank}; largest hazard contributions: {drivers}.")  # fmt: skip
            pc = p.get("premise_check")
            if pc and pc.get("supported") is False:
                lines.append(f"- The claim “{pc['claim']}” is not supported by the index.")
        elif e.name == "get_hub_profile":
            hz = ", ".join(
                f"{k} {{{{fact:{v['score']['fact']}}}}}" for k, v in p["hazards"].items()
            )
            lines.append(f"- {p['hub']['name']}: overall {{{{fact:{p['overall']['fact']}}}}} "
                         f"({p['overall_band']}); {hz}.")  # fmt: skip
        elif e.name == "list_hubs":
            lines.append(
                "- Supported illustrative hubs: " + ", ".join(h["name"] for h in p["hubs"])
            )
    return "\n".join(lines)
