"""Latency benchmark of the REAL agent through HTTP (needs GEMINI_API_KEY + network).

    uv run python scripts/benchmark.py --label before
    uv run python scripts/benchmark.py --label after --repeat 2

Comparable conditions: a fresh server with weather data from the committed snapshot
(WEATHER_RISK_OFFLINE=true, empty cache), engine warmed via /api/overview before timing, the
same four assignment questions in fresh sessions, fixed pacing between requests.
Writes docs/benchmarks/<label>.json and prints a breakdown table.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from live_smoke import spawn  # noqa: E402

QUESTIONS = [
    "Which hubs in the Midwest are most exposed to winter disruption?",
    "Compare Miami and Houston in terms of hurricane and flood exposure.",
    "What percentage of days in Denver last year had snowfall?",
    "Why is the Dallas hub's weather disruption risk high?",
]
PACE_SECONDS = 8.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    proc, base, _ = spawn(no_weather_network=True)
    rows = []
    try:
        with httpx.Client(base_url=base, timeout=240) as c:
            health = c.get("/api/health").json()
            t = time.perf_counter()
            c.get("/api/overview").raise_for_status()  # warm the deterministic engine
            warm_ms = (time.perf_counter() - t) * 1000
            for rep in range(args.repeat):
                for q in QUESTIONS:
                    time.sleep(PACE_SECONDS)
                    t = time.perf_counter()
                    r = c.post("/api/chat", json={"message": q})
                    wall = (time.perf_counter() - t) * 1000
                    d = r.json()
                    a = d.get("agent", {})
                    calls = a.get("llm_calls", [])
                    rows.append({
                        "rep": rep, "question": q, "http": r.status_code, "wall_ms": round(wall),
                        "status": d.get("status") or f"HTTP {r.status_code} {d.get('error')}", "valid": d.get("validation", {}).get("valid"),
                        "attempts": d.get("validation", {}).get("attempts"),
                        "timings_ms": a.get("timings_ms", {}),
                        "llm_http_calls": len([x for x in calls if "latency_ms" in x]),
                        "llm_errors": [x.get("error") for x in calls if x.get("ok") is False],
                        "models": sorted({x["model"] for x in calls if x.get("ok")}),
                        "iterations": a.get("iterations"),
                        "tools": [x["name"] for x in a.get("tool_calls", [])],
                        "tokens": [a.get("input_tokens"), a.get("output_tokens"),
                                   a.get("thinking_tokens")],
                        "llm_calls": calls,
                    })  # fmt: skip
                    print(f"{rows[-1]['wall_ms'] / 1000:6.1f}s  {rows[-1]['status']:<20} "
                          f"{q[:55]}", flush=True)  # fmt: skip
    finally:
        proc.terminate()

    ok = [r["wall_ms"] for r in rows if r["http"] == 200]
    summary = {
        "label": args.label, "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": health["llm"]["model"], "methodology": health["methodology_version"],
        "engine_warmup_ms": round(warm_ms), "n": len(rows),
        "median_ms": round(statistics.median(ok)) if ok else None,
        "mean_ms": round(statistics.mean(ok)) if ok else None,
        "max_ms": max(ok) if ok else None, "rows": rows,
    }  # fmt: skip
    out = ROOT / "docs" / "benchmarks" / f"{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1))
    print(f"\n{'question':<42} {'wall':>6} {'sel-LLM':>8} {'tools':>6} {'syn-LLM':>8} "
          f"{'wait':>6} {'calls':>5} {'iter':>4} {'thinkTok':>8} models")  # fmt: skip
    for r in rows:
        tm = r["timings_ms"]
        print(f"{r['question'][:42]:<42} {r['wall_ms'] / 1000:6.1f} "
              f"{tm.get('tool_selection_llm_ms', 0) / 1000:8.1f} "
              f"{tm.get('tool_execution_ms', 0) / 1000:6.2f} {tm.get('synthesis_llm_ms', 0) / 1000:8.1f} "
              f"{tm.get('provider_wait_ms', 0) / 1000:6.1f} {r['llm_http_calls']:5d} "
              f"{r['iterations'] or 0:4d} {r['tokens'][2] or 0:8d} {','.join(r['models'])}"
              f"{' errors=' + str(r['llm_errors']) if r['llm_errors'] else ''}")  # fmt: skip
    if ok:
        print(f"\nmedian {summary['median_ms'] / 1000:.1f}s · mean {summary['mean_ms'] / 1000:.1f}s · "
              f"max {summary['max_ms'] / 1000:.1f}s · {len(ok)}/{len(rows)} HTTP 200 · wrote {out}")  # fmt: skip
    else:
        print(f"\nno successful requests · wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
