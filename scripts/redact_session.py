"""Redact credentials and private contact data from an AI-session export before committing it.

    uv run python scripts/redact_session.py <input> <output> [--email you@example.com]

Replaces Google API keys (`AIza…`, `AQ.…`), OpenAI/Anthropic-style `sk-…` keys, GitHub tokens,
private-key blocks and non-placeholder `GEMINI_API_KEY=` values with `[REDACTED: <reason>]`, and the
given private email address(es) with `[REDACTED: email]`. Nothing else is changed: the
conversation is not edited, reordered or reconstructed. Prints per-pattern COUNTS only, never values,
so the output can be pasted into docs/ai-session/README.md's redaction log.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("Google API key", re.compile(r"\bAQ\.[0-9A-Za-z_-]{20,}")),
    ("API key", re.compile(r"\bsk-(?:ant-)?[0-9A-Za-z_-]{20,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}")),
    (
        "private key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
        ),
    ),  # fmt: skip
]
# `GEMINI_API_KEY=<value>` where the value is not an obvious placeholder or a regex/code fragment.
ASSIGNMENT = re.compile(r"(GEMINI_API_KEY=)([0-9A-Za-z_.-]{24,})")


def redact(text: str, emails: list[str]) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}

    def sub(reason: str):
        def f(m: re.Match[str]) -> str:
            counts[reason] = counts.get(reason, 0) + 1
            return f"[REDACTED: {reason}]"

        return f

    for reason, pat in PATTERNS:
        text = pat.sub(sub(reason), text)

    def assign(m: re.Match[str]) -> str:
        counts["GEMINI_API_KEY value"] = counts.get("GEMINI_API_KEY value", 0) + 1
        return m.group(1) + "[REDACTED: API key]"

    text = ASSIGNMENT.sub(assign, text)
    for e in emails:
        text = re.compile(re.escape(e), re.IGNORECASE).sub(sub("email"), text)
    return text, counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--email", action="append", default=[], help="private address to redact")
    a = ap.parse_args()
    if a.input.resolve() == a.output.resolve():
        print("refusing to overwrite the input; write to a new file", file=sys.stderr)
        return 2
    out, counts = redact(a.input.read_text(encoding="utf-8"), a.email)
    a.output.write_text(out, encoding="utf-8")
    for reason, n in sorted(counts.items()):
        print(f"{n:5d}  {reason}")
    print(f"total {sum(counts.values())} redaction(s) -> {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
