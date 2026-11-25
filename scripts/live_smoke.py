"""REAL-Gemini smoke scenarios through the HTTP API (not a mock; needs GEMINI_API_KEY + network).

    uv run python scripts/live_smoke.py                      # spawns uvicorn, writes report
    uv run python scripts/live_smoke.py --no-weather-network # weather APIs blocked, snapshot only
    uv run python scripts/live_smoke.py --base-url http://127.0.0.1:8000   # use a running server

Each check compares the agent's structured response with the deterministic engine (v1.1.0).
Results (answers, tool calls, validation, model, latency, tokens) are written to
docs/PHASE_3_LIVE_SMOKE.md and docs/phase3_live_smoke.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weather_risk.analytics.config import ClimateMetric, load_scoring_config  # noqa: E402
from weather_risk.analytics.engine import AnalyticsEngine  # noqa: E402
from weather_risk.catalog import load_catalog  # noqa: E402
from weather_risk.config import get_settings  # noqa: E402
from weather_risk.data.repository import build_repository  # noqa: E402


def engine() -> AnalyticsEngine:
    s = get_settings().model_copy(update={"offline": True})
    return AnalyticsEngine(build_repository(s), load_catalog(s.hubs_path),
                           load_scoring_config(ROOT / "config" / "scoring.yaml"))  # fmt: skip


def tools(r: dict) -> list[tuple[str, dict]]:
    return [(t["name"], t["args"]) for t in r["agent"]["tool_calls"]]


def check(cond: bool, label: str, out: list[str]) -> bool:
    out.append(("PASS " if cond else "FAIL ") + label)
    return cond


# ------------------------------------------------------------------ expectations (engine-based)


def checks_midwest(r, e, out):
    exp = [x.hub_id for x in e.rank_hubs(hazard="winter", region="Midwest").ranked]
    got = [x["hub_id"] for rk in r["analysis"]["rankings"] for x in rk["ranked"]]
    check(any(n == "rank_hubs" for n, _ in tools(r)), "called rank_hubs", out)
    check(got[:6] == exp, f"ranking order equals engine {exp}", out)
    check(e.hub(exp[0]).city.lower() in r["answer"].lower(), f"answer names #1 {exp[0]}", out)


def checks_compare(r, e, out, hubs=("miami_fl", "houston_tx"), hazards=("hurricane", "flood")):
    c = e.compare_hubs(list(hubs), list(hazards))
    comps = r["analysis"]["comparisons"]
    check(bool(comps), "called compare_hubs", out)
    if comps:
        got = {row["hazard"]: row["leader"] for row in comps[-1]["rows"]}
        for row in c.rows:
            if row.hazard.value in got:
                check(got[row.hazard.value] == row.leader,
                      f"{row.hazard.value} leader = {row.leader}", out)  # fmt: skip
        check(set(hubs) <= set(comps[-1]["hub_ids"]), f"compared {sorted(hubs)}", out)


def checks_denver(r, e, out, year=2025, metric="snow_days_measurable", want_trace=True):
    s = e.get_weather_stat("denver_co", ClimateMetric(metric), str(year))
    stats = r["analysis"]["weather_stats"]
    match = [x for x in stats if x["metric"] == metric and x["period"]["start"] == f"{year}-01-01"]
    check(bool(match), f"weather stat {metric} {year} retrieved", out)
    if match:
        check(match[0]["event_days"] == s.event_days, f"event_days = {s.event_days}", out)
    check(f"{s.value_percent_of_valid_days:.2f}%" in r["answer"] or str(s.event_days) in r["answer"],
          "answer states the engine's value", out)  # fmt: skip
    check(str(year) in r["answer"], f"answer states the year {year}", out)
    if want_trace:
        t = e.get_weather_stat("denver_co", ClimateMetric.SNOW_DAYS_TRACE_INCLUSIVE, str(year))
        check(f"{t.value_percent_of_valid_days:.2f}%" in r["answer"],
              "answer also gives trace-inclusive %", out)  # fmt: skip
        check("missing" in r["answer"].lower(), "answer discloses missing observation(s)", out)


def checks_dallas(r, e, out):
    ex = e.explain_hub_score("dallas_tx", claimed_band="High")
    check(any(n == "explain_hub_score" for n, _ in tools(r)), "called explain_hub_score", out)
    check(bool(r.get("premise_correction")), "premise_correction present", out)
    text = (r["answer"] + " " + (r.get("premise_correction") or "")).lower()
    check(ex.overall_band.lower() in text, f"states band {ex.overall_band}", out)
    check(f"#{ex.rank_among_catalog}" in text or "second" in text, "states its rank", out)
    check(ex.primary_driver.replace("_", " ").split()[0] in text,
          f"names primary driver {ex.primary_driver}", out)  # fmt: skip


SCENARIOS = [
    ("S1", "Which hubs in the Midwest are most exposed to winter disruption?", checks_midwest),
    ("S2", "Compare Miami and Houston in terms of hurricane and flood exposure.", checks_compare),
    ("S3", "What percentage of days in Denver last year had snowfall?", checks_denver),
    ("S4", "Why is the Dallas hub's weather disruption risk high?", checks_dallas),
]


def conv_a(e):
    return [
        ("Compare Miami and Houston for hurricane and flood exposure.", checks_compare),
        (
            "What about Dallas?",
            lambda r, e, o: check(
                "dallas_tx" in r["resolved"]["hubs"]
                and any(
                    "Dallas" in json.dumps(a) or "dallas" in json.dumps(a) for _, a in tools(r)
                ),
                "Dallas resolved and queried",
                o,
            ),
        ),
        (
            "Which of the three has the highest hurricane exposure?",
            lambda r, e, o: (
                check(
                    set(r["resolved"]["hubs"]) >= {"miami_fl", "houston_tx", "dallas_tx"},
                    "context kept: three hubs",
                    o,
                ),
                check("miami" in r["answer"].lower(), "answers Miami (engine leader)", o),
            ),
        ),
        (
            "Now compare their flood exposure.",
            lambda r, e, o: checks_compare(
                r, e, o, hubs=("miami_fl", "houston_tx", "dallas_tx"), hazards=("flood",)
            ),
        ),
    ]


def conv_b(e):
    return [
        ("What percentage of days in Denver last year had snowfall?", checks_denver),
        ("What about 2024?", lambda r, e, o: checks_denver(r, e, o, 2024, want_trace=False)),
        (
            "Include trace snowfall.",
            lambda r, e, o: checks_denver(
                r, e, o, 2024, "snow_days_trace_inclusive", want_trace=False
            ),
        ),
        (
            "How many days had measurable snowfall?",
            lambda r, e, o: checks_denver(r, e, o, 2024, "snow_days_measurable", want_trace=False),
        ),
    ]


# ------------------------------------------------------------------ runner


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def spawn(no_weather_network: bool) -> tuple[subprocess.Popen, str, Path]:
    port = free_port()
    tmp = Path(tempfile.mkdtemp(prefix="wr_smoke_"))
    env = dict(os.environ, WEATHER_RISK_SESSIONS_PATH=str(tmp / "sessions.db"), LOG_LEVEL="WARNING")
    if no_weather_network:
        env.update(WEATHER_RISK_OFFLINE="true", WEATHER_RISK_CACHE_PATH=str(tmp / "empty.db"),
                   HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9",
                   NO_PROXY="generativelanguage.googleapis.com")  # fmt: skip
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "weather_risk.api.app:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(f"{base}/api/health", timeout=2).status_code == 200:
                return proc, base, tmp
        except httpx.HTTPError:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("server did not start")


PACE_SECONDS = 6.0  # free-tier per-minute quota: space out turns (each turn = 2-4 LLM calls)


def ask(client: httpx.Client, msg: str, sid: str | None) -> dict:
    body = {"message": msg} | ({"session_id": sid} if sid else {})
    for attempt in (1, 2):
        time.sleep(PACE_SECONDS)
        r = client.post("/api/chat", json=body, timeout=240)
        if r.status_code != 429 or attempt == 2:
            break
        time.sleep(60)  # rate-limited: wait for the per-minute window, then retry once
    data = r.json()
    data["_http_status"] = r.status_code
    data["_rate_limited_retry"] = attempt == 2
    return data


def summarize(label: str, msg: str, r: dict, checks: list[str]) -> list[str]:
    a = r.get("agent", {})
    lines = [f"### {label}: {msg}\n",
             f"- HTTP {r['_http_status']} · status `{r.get('status')}` · narrative "
             f"`{r.get('narrative_source')}` · validation valid={r.get('validation', {}).get('valid')} "
             f"attempts={r.get('validation', {}).get('attempts')}",
             f"- model `{a.get('model')}` (version `{a.get('model_version')}`) · iterations "
             f"{a.get('iterations')} · latency {a.get('latency_ms')} ms · tokens in/out/thinking "
             f"{a.get('input_tokens')}/{a.get('output_tokens')}/{a.get('thinking_tokens')}",
             f"- tool calls: `{json.dumps([(t['name'], t['args']) for t in a.get('tool_calls', [])])}`",
             f"- data freshness: {r.get('data_freshness')}"]  # fmt: skip
    if r.get("validation", {}).get("issues"):
        lines.append(f"- validation issues (first attempt rejected): {r['validation']['issues']}")
    lines.append("\n**Answer:**\n\n" + "\n".join("> " + x for x in (r.get("answer") or r.get(
        "detail", "")).splitlines()))  # fmt: skip
    if r.get("premise_correction"):
        lines.append(f"\n**Premise correction:** {r['premise_correction']}")
    if r.get("clarification_question"):
        lines.append(f"\n**Clarification:** {r['clarification_question']}")
    lines.append("\n**Checks:** " + " · ".join(checks) + "\n")
    return lines


def main() -> int:
    logging.disable(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--no-weather-network", action="store_true")
    ap.add_argument("--only", choices=["scenarios", "conversations", "isolation"], default=None)
    ap.add_argument("--out", default="docs/PHASE_3_LIVE_SMOKE.md")
    args = ap.parse_args()
    eng = engine()
    proc = None
    if args.base_url:
        base = args.base_url
    else:
        proc, base, _ = spawn(args.no_weather_network)
    md: list[str] = [
        "# Phase 3 — Real-Gemini Smoke Results (generated)\n",
        f"Run at {datetime.now(UTC).isoformat(timespec='seconds')} via `scripts/live_smoke.py` "
        f"against `{base}` (real uvicorn server, real Gemini API, POST /api/chat). "
        f"Weather network disabled: `{args.no_weather_network}`. These are REAL LLM calls, not "
        "mocks. Checks compare the API's structured output with the deterministic engine.\n",
    ]
    results, total, passed = [], 0, 0
    try:
        with httpx.Client(base_url=base) as client:
            health = client.get("/api/health").json()
            md.append(f"Health: `{json.dumps(health)}`\n")
            groups = []
            if args.only in (None, "scenarios"):
                groups += [("Assignment scenarios (separate sessions)",
                            [[(lbl, q, fn)] for lbl, q, fn in SCENARIOS])]  # fmt: skip
            if args.only in (None, "conversations"):
                groups += [("Multi-turn conversation A", [[(f"A{i + 1}", q, fn) for i, (q, fn)
                                                          in enumerate(conv_a(eng))]]),
                           ("Multi-turn conversation B", [[(f"B{i + 1}", q, fn) for i, (q, fn)
                                                          in enumerate(conv_b(eng))]])]  # fmt: skip
            if args.only in (None, "isolation"):
                groups += [("Session isolation (fresh session, follow-up without context)",
                            [[("I1", "What about 2024?", lambda r, e, o: (
                                check(r.get("status") == "needs_clarification",
                                      "asks for clarification", o),
                                check(not r["analysis"]["weather_stats"]
                                      and not r["analysis"]["profiles"],
                                      "no analysis for an unmentioned hub", o)))]])]  # fmt: skip
            for title, convs in groups:
                md.append(f"## {title}\n")
                for conv in convs:
                    sid = None
                    for label, q, fn in conv:
                        r = ask(client, q, sid)
                        sid = r.get("session_id", sid)
                        out: list[str] = []
                        if r["_http_status"] == 200:
                            check(r["validation"]["valid"] or r["status"] == "fallback",
                                  "schema+grounding valid (or labeled fallback)", out)  # fmt: skip
                            try:
                                fn(r, eng, out)
                            except Exception as exc:  # noqa: BLE001
                                out.append(f"FAIL check error {type(exc).__name__}: {exc}")
                        else:
                            out.append(f"FAIL HTTP {r['_http_status']}: {r.get('error')}")
                        total += len(out)
                        passed += sum(1 for x in out if x.startswith("PASS"))
                        results.append({"label": label, "question": q, "response": r,
                                        "checks": out})  # fmt: skip
                        md += summarize(label, q, r, out)
    finally:
        if proc:
            proc.terminate()
    md.insert(2, f"**Checks passed: {passed}/{total}.**\n")
    out_md = ROOT / args.out
    out_md.write_text("\n".join(md) + "\n")
    (out_md.with_suffix(".json")).write_text(json.dumps(results, indent=1, default=str))
    print(f"checks passed {passed}/{total}; wrote {out_md}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
