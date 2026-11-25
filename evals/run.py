"""WeatherLens evaluation runner — REAL Gemini through POST /api/chat (not mocked).

    uv run python evals/run.py                       # all cases
    uv run python evals/run.py --smoke               # quick demo subset
    uv run python evals/run.py --case A3-denver-snow-2025 --category multi_turn
    uv run python evals/run.py --base-url http://127.0.0.1:8000   # use a running server

Spawns a server with weather data from the committed snapshot (weather APIs blocked, empty
cache) so data conditions are identical across runs; a second server without a key serves the
provider-unavailable case. Assertions check the STRUCTURED response against literal expectations
(independently verified) and the deterministic engine. Writes evals/results/<run>.json, and
evals/results/latest.{json,md}.

Case outcome:
  pass            all assertions passed and every answer was written by the LLM
  pass_fallback   all assertions passed but a labeled deterministic fallback was used (qualified)
  fail            at least one assertion failed (critical failures listed separately)
  provider_error  the provider could not answer (rate limit / overload), assertions not evaluable
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weather_risk.agent.orchestrator import mentioned_hubs  # noqa: E402
from weather_risk.analytics.config import ClimateMetric, load_scoring_config  # noqa: E402
from weather_risk.analytics.engine import AnalyticsEngine  # noqa: E402
from weather_risk.catalog import load_catalog  # noqa: E402
from weather_risk.config import get_settings  # noqa: E402
from weather_risk.data.repository import build_repository  # noqa: E402

PACE_SECONDS = 8.0
KNOWN_ASSERTIONS = frozenset({
    "status_in", "tool_called", "any_tool_called", "any_tool_args_mention", "ranking_order",
    "engine_ranking", "engine_overall_ranking", "ranking_excludes", "ranking_first",
    "comparison_leader", "resolved_hubs_include", "resolved_hubs_exclude", "weather_stat",
    "engine_weather_stat", "weather_stat_status", "explanation", "premise_corrected",
    "answer_contains_all", "answer_or_premise_contains_all", "answer_contains_any",
    "answer_not_regex", "exposure_framing", "grounded_numbers", "fact_attribution",
    "freshness_only", "no_analysis", "no_analysis_for_unmentioned", "http_error",
    "deterministic_endpoints_ok",
})  # fmt: skip
PROVIDER_ERRORS = {"llm_quota_exceeded", "llm_unavailable", "llm_timeout", "llm_error"}


# ---------------------------------------------------------------- servers
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def spawn(with_llm: bool) -> tuple[subprocess.Popen, str]:
    port, tmp = _free_port(), Path(tempfile.mkdtemp(prefix="wr_eval_"))
    env = dict(os.environ, LOG_LEVEL="WARNING", WEATHER_RISK_OFFLINE="true",
               WEATHER_RISK_CACHE_PATH=str(tmp / "cache.db"),
               WEATHER_RISK_SESSIONS_PATH=str(tmp / "sessions.db"),
               HTTPS_PROXY="http://127.0.0.1:9", HTTP_PROXY="http://127.0.0.1:9",
               NO_PROXY="generativelanguage.googleapis.com")  # fmt: skip
    if not with_llm:
        env["GEMINI_API_KEY"] = ""
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "weather_risk.api.app:app",
                             "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=(tmp / "server.log").open("w"))  # fmt: skip
    print(f"server log: {tmp / 'server.log'}", flush=True)
    base = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            if httpx.get(f"{base}/api/health", timeout=2).status_code == 200:
                httpx.get(f"{base}/api/overview", timeout=120)  # warm the engine
                return proc, base
        except httpx.HTTPError:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("eval server did not start")


# ---------------------------------------------------------------- assertions
class Ctx:
    def __init__(self, engine: AnalyticsEngine, r: dict, message: str, client: httpx.Client):
        self.engine, self.r, self.message, self.client = engine, r, message, client

    @property
    def a(self) -> dict:
        return self.r.get("analysis") or {}

    def text(self, premise: bool = False) -> str:
        parts = [self.r.get("answer") or ""]
        if premise:
            parts.append(self.r.get("premise_correction") or "")
        return "\n".join(parts)

    def hub(self, v: Any) -> str:
        try:
            return self.engine.hub(str(v)).id
        except Exception:  # noqa: BLE001
            return str(v).lower()

    def tools(self) -> list[dict]:
        return (self.r.get("agent") or {}).get("tool_calls") or []


def _ranking(c: Ctx, hazard, region):
    for rk in c.a.get("rankings", []):
        if rk.get("hazard") == hazard and rk.get("region") == region:
            return rk
    return None


def _num_tokens(text: str) -> list[str]:
    return re.findall(r"(?<![\w-])\d+(?:\.\d+)?%?", text)


def check(kind: str, spec: dict, c: Ctx) -> tuple[bool, str]:  # noqa: C901 - flat dispatch
    if kind not in KNOWN_ASSERTIONS:
        return False, f"unknown assertion type {kind}"
    r = c.r
    if kind == "status_in":
        values = list(spec["values"])
        if "answered" in values:  # a labeled grounded fallback answers it (case -> pass_fallback)
            values.append("fallback")
        return r.get("status") in values, f"status={r.get('status')}"
    if kind == "tool_called":
        for t in c.tools():
            if t["name"] != spec["name"]:
                continue
            ok = True
            for k, v in (spec.get("args") or {}).items():
                got = t["args"].get(k)
                if k == "hub":
                    ok &= c.hub(got) == v
                elif isinstance(v, str):
                    ok &= str(got).lower() == v.lower()
                else:
                    ok &= got == v
            if ok:
                return True, f"{t['name']}({t['args']})"
        return False, f"calls={[(t['name'], t['args']) for t in c.tools()]}"
    if kind == "any_tool_called":
        names = [t["name"] for t in c.tools()]
        return any(n in names for n in spec["names"]), f"calls={names}"
    if kind == "any_tool_args_mention":
        blob = json.dumps([t["args"] for t in c.tools()]).lower()
        return spec["value"] in blob, blob[:160]
    if kind == "ranking_order":
        rk = _ranking(c, spec["hazard"], spec.get("region"))
        got = [e["hub_id"] for e in rk["ranked"]] if rk else None
        return got == spec["expected"], f"got={got}"
    if kind == "engine_ranking":
        rk = _ranking(c, spec["hazard"], spec.get("region"))
        exp = [
            e.hub_id
            for e in c.engine.rank_hubs(hazard=spec["hazard"], region=spec.get("region")).ranked
        ]
        got = [e["hub_id"] for e in rk["ranked"]] if rk else None
        return got == exp, f"got={got} engine={exp}"
    if kind == "engine_overall_ranking":
        rk = _ranking(c, None, None)
        exp = [e.hub_id for e in c.engine.rank_hubs().ranked]
        got = [e["hub_id"] for e in rk["ranked"]] if rk else None
        return got == exp, f"got={got}"
    if kind == "ranking_excludes":
        rk = _ranking(c, spec["hazard"], None)
        if not rk:
            return False, "no overall ranking in analysis"
        ranked = [e["hub_id"] for e in rk["ranked"]]
        not_ranked = [e["hub_id"] for e in rk["not_ranked"]]
        return spec["hub"] not in ranked and spec["hub"] in not_ranked, f"not_ranked={not_ranked}"
    if kind == "ranking_first":
        rk = _ranking(c, spec["hazard"], None)
        first = rk["ranked"][0]["hub_id"] if rk and rk["ranked"] else None
        return first == spec["hub"], f"first={first}"
    if kind == "comparison_leader":
        for comp in c.a.get("comparisons", []):
            for row in comp["rows"]:
                if row["hazard"] == spec["hazard"]:
                    return row["leader"] == spec["leader"], f"leader={row['leader']}"
        rk = _ranking(c, spec["hazard"], None)  # a hazard ranking over the hubs also answers it
        if rk and rk["ranked"]:
            return rk["ranked"][0]["hub_id"] == spec[
                "leader"
            ], f"ranking first={rk['ranked'][0]['hub_id']}"
        return False, "no comparison/ranking for hazard"
    if kind in ("resolved_hubs_include", "resolved_hubs_exclude"):
        hubs = (r.get("resolved") or {}).get("hubs") or []
        if kind.endswith("include"):
            return set(spec["values"]) <= set(hubs), f"resolved={hubs}"
        return not any(v in h for v in spec["values"] for h in hubs), f"resolved={hubs}"
    if kind == "weather_stat":
        for s in c.a.get("weather_stats", []):
            if (s["hub_id"], s["metric"], s["period"]["start"]) == (
                spec["hub"],
                spec["metric"],
                spec["start"],
            ):
                errs = []
                if "event_days" in spec and s["event_days"] != spec["event_days"]:
                    errs.append(f"event_days {s['event_days']}")
                if "valid_days" in spec and s["coverage"]["valid_days"] != spec["valid_days"]:
                    errs.append(f"valid_days {s['coverage']['valid_days']}")
                if "value_display" in spec and s.get("value_display") != spec["value_display"]:
                    errs.append(f"value {s.get('value_display')}")
                return not errs, "; ".join(errs) or "match"
        return (
            False,
            f"stats={[(s['hub_id'], s['metric'], s['period']['start']) for s in c.a.get('weather_stats', [])]}",
        )
    if kind == "engine_weather_stat":
        exp = c.engine.get_weather_stat(spec["hub"], ClimateMetric(spec["metric"]), spec["period"])
        for s in c.a.get("weather_stats", []):
            if (
                s["hub_id"] == spec["hub"]
                and s["metric"] == spec["metric"]
                and s["period"]["start"] == exp.period.start.isoformat()
            ):
                return s[
                    "event_days"
                ] == exp.event_days, f"got={s['event_days']} engine={exp.event_days}"
        return False, "stat not retrieved"
    if kind == "weather_stat_status":
        sts = [s["status"] for s in c.a.get("weather_stats", []) if s["hub_id"] == spec["hub"]]
        return spec["status"] in sts and all(st == spec["status"] for st in sts), f"statuses={sts}"
    if kind == "explanation":
        for e in c.a.get("explanations", []):
            if e["hub_id"] == spec["hub"]:
                ok = e["overall_band"] == spec["band"] and e["rank_among_catalog"] == spec["rank"]
                return ok, f"band={e['overall_band']} rank={e['rank_among_catalog']}"
        return False, "no explanation"
    if kind == "premise_corrected":
        pc = (r.get("premise_correction") or "").strip()
        return bool(pc) or "not supported" in c.text().lower(), f"premise={pc[:80]!r}"
    if kind in ("answer_contains_all", "answer_or_premise_contains_all"):
        t = c.text(premise=kind.startswith("answer_or")).lower()
        missing = [v for v in spec["values"] if v.lower() not in t]
        return not missing, f"missing={missing}"
    if kind == "answer_contains_any":
        t = c.text(premise=True).lower()
        return any(v.lower() in t for v in spec["values"]), f"none of {spec['values']}"
    if kind == "answer_not_regex":
        blob = "\n".join([c.text(premise=True), r.get("clarification_question") or ""])
        m = re.search(spec["pattern"], blob)
        return m is None, f"matched {m.group(0)!r}" if m else "no match"
    if kind == "exposure_framing":
        return "exposure" in c.text().lower(), "mentions exposure"
    if kind == "grounded_numbers":
        allowed = set()
        for f in r.get("facts") or []:
            allowed |= {t.rstrip("%") for t in _num_tokens(str(f.get("display")))}
            allowed |= {t.rstrip("%") for t in _num_tokens(str(f.get("label")))}
        allowed |= {t.rstrip("%") for t in _num_tokens(c.message)}
        for s in c.a.get("weather_stats", []):
            allowed |= set(re.findall(r"\d{4}", s["period"]["label"]))
        bad = []
        for tok in _num_tokens(c.text(premise=True)):
            core = tok.rstrip("%")
            if core in allowed or (core.isdigit() and int(core) <= 12 and "%" not in tok):
                continue
            if core.isdigit() and 2016 <= int(core) <= 2026 and "%" not in tok:
                continue  # years of supported periods
            bad.append(tok)
        return not bad, f"ungrounded={bad}" if bad else "all numbers from verified facts"
    if kind == "fact_attribution":
        hubs = set((r.get("resolved") or {}).get("hubs") or [])
        for comp in c.a.get("comparisons", []):
            hubs |= set(comp["hub_ids"])
        bad = [
            f["fact_id"]
            for f in r.get("facts") or []
            if f.get("hub_id") and f["hub_id"] not in hubs
        ]
        return not bad, f"facts outside resolved hubs={bad}"
    if kind == "freshness_only":
        labels = {lbl for v in (r.get("data_freshness") or {}).values() for lbl in v}
        return bool(labels) and labels <= set(spec["values"]), f"freshness={labels}"
    if kind == "no_analysis":
        n = sum(len(v) for v in c.a.values()) if c.a else 0
        return n == 0, f"analysis items={n}"
    if kind == "no_analysis_for_unmentioned":
        allowed = mentioned_hubs(c.engine, c.message)
        hubs = {s["hub_id"] for s in c.a.get("weather_stats", [])}
        hubs |= {p["hub_id"] for p in c.a.get("profiles", [])} | {
            e["hub_id"] for e in c.a.get("explanations", [])
        }
        return hubs <= allowed, f"analysed={sorted(hubs)}"
    if kind == "http_error":
        return (r.get("_http_status") == spec["status"] and r.get("error") == spec["error"],
                f"HTTP {r.get('_http_status')} {r.get('error')}")  # fmt: skip
    if kind == "deterministic_endpoints_ok":
        codes = [
            c.client.get(p).status_code for p in ("/api/overview", "/api/hubs/dallas_tx/scores")
        ]
        return codes == [200, 200], f"codes={codes}"
    return False, f"unknown assertion type {kind}"


# ---------------------------------------------------------------- runner
def _body(resp: httpx.Response) -> dict:
    """Parsed JSON object, or a recorded error for HTML/plain-text/empty bodies."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    return {"error": "non_json_response", "detail": resp.text[:200]}


def save(results: list[dict], meta: dict, complete: bool) -> tuple[dict, str]:
    """Write after every case so a crash never loses finished results."""
    summary, md = summarize(results, meta)
    summary["complete"] = complete
    if not complete:
        md = "> **INCOMPLETE RUN** (interrupted or still running).\n\n" + md
    out = ROOT / "evals" / "results"
    out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"summary": summary, "results": results}, indent=1, default=str)
    for name in (meta["run_id"], "latest"):
        (out / f"{name}.json").write_text(payload)
        (out / f"{name}.md").write_text(md)
    return summary, md


def post(client: httpx.Client, message: str, sid: str | None) -> tuple[dict, list[str]]:
    notes = []
    for attempt in (1, 2):
        t = time.perf_counter()
        try:
            resp = client.post("/api/chat", json={"message": message} | ({"session_id": sid} if sid else {}),
                           timeout=240)  # fmt: skip
        except httpx.HTTPError as exc:
            return {
                "error": f"transport_error: {type(exc).__name__}",
                "_http_status": 0,
                "_wall_ms": round((time.perf_counter() - t) * 1000),
            }, notes
        d = _body(resp)
        d["_http_status"], d["_wall_ms"] = resp.status_code, round((time.perf_counter() - t) * 1000)
        if resp.status_code == 200 or d.get("error") not in PROVIDER_ERRORS or attempt == 2:
            return d, notes
        wait = 65 if d.get("error") == "llm_quota_exceeded" else 20
        notes.append(f"provider {d.get('error')} -> waited {wait}s and retried once")
        time.sleep(wait)
    return d, notes


def run_case(case: dict, engine: AnalyticsEngine, clients: dict[str, httpx.Client]) -> dict:
    client = clients["no_llm" if case.get("mode") == "no_llm" else "llm"]
    sid, turns, provider_error = None, [], False
    for i, turn in enumerate(case["turns"]):
        if turn.get("new_session"):
            sid = None
        if i or case.get("mode") != "no_llm":
            time.sleep(PACE_SECONDS if case.get("mode") != "no_llm" else 0)
        r, notes = post(client, turn["say"], sid)
        sid = r.get("session_id", sid)
        is_provider_err = r["_http_status"] != 200 and r.get("error") in PROVIDER_ERRORS
        expects_http_error = any(a["type"] == "http_error" for a in turn["expect"])
        if is_provider_err and not expects_http_error:
            provider_error = True
        ctx = Ctx(engine, r, turn["say"], client)
        results = []
        for a in turn["expect"]:
            if is_provider_err and not expects_http_error:
                results.append({"type": a["type"], "ok": None, "critical": bool(a.get("critical")),
                                "detail": "not evaluable (provider error)"})  # fmt: skip
                continue
            try:
                ok, detail = check(a["type"], a, ctx)
            except Exception as exc:  # noqa: BLE001 - a broken response fails the assertion
                ok, detail = False, f"error {type(exc).__name__}: {exc}"
            results.append({"type": a["type"], "ok": bool(ok), "critical": bool(a.get("critical")),
                            "detail": detail})  # fmt: skip
        agent = r.get("agent") or {}
        turns.append({
            "say": turn["say"], "new_session": bool(turn.get("new_session")),
            "expected_http_error": expects_http_error,
            "http": r["_http_status"], "error": r.get("error"), "status": r.get("status"),
            "narrative_source": r.get("narrative_source"), "wall_ms": r["_wall_ms"],
            "validation": r.get("validation"), "notes": notes,
            "tools": [(t["name"], t["args"]) for t in agent.get("tool_calls", [])],
            "models_used": sorted({c["model"] for c in agent.get("llm_calls", []) if c.get("ok")}),
            "llm_errors": [c.get("error") for c in agent.get("llm_calls", []) if c.get("ok") is False],
            "timings_ms": agent.get("timings_ms"), "answer": r.get("answer"),
            "premise_correction": r.get("premise_correction"), "assertions": results,
        })  # fmt: skip
    evaluated = [a for t in turns for a in t["assertions"] if a["ok"] is not None]
    failed = [a for a in evaluated if not a["ok"]]
    fallback = any(t["narrative_source"] == "deterministic_fallback" for t in turns)
    if provider_error:
        outcome = "provider_error"
    elif failed:
        outcome = "fail"
    else:
        outcome = "pass_fallback" if fallback else "pass"
    return {"id": case["id"], "category": case["category"], "criticality": case.get("criticality"),
            "outcome": outcome, "critical_failures": [a for a in failed if a["critical"]],
            "turns": turns}  # fmt: skip


def summarize(results: list[dict], meta: dict) -> tuple[dict, str]:
    by = {k: [r["id"] for r in results if r["outcome"] == k]
          for k in ("pass", "pass_fallback", "fail", "provider_error")}  # fmt: skip
    asserts = [
        a for r in results for t in r["turns"] for a in t["assertions"] if a["ok"] is not None
    ]
    turns = [t for r in results for t in r["turns"]]
    llm_turns = [t for t in turns if t["http"] == 200 and t.get("validation")]
    walls = [t["wall_ms"] for t in llm_turns]
    primary = meta["model"]
    summary = {
        **meta, "cases": len(results), **{f"n_{k}": len(v) for k, v in by.items()}, "ids": by,
        "case_pass_rate": round(len(by["pass"]) / len(results), 3) if results else None,
        "case_pass_rate_incl_fallback": round((len(by["pass"]) + len(by["pass_fallback"])) / len(results), 3) if results else None,
        "assertions": len(asserts), "assertions_passed": sum(a["ok"] for a in asserts),
        "assertion_pass_rate": round(sum(a["ok"] for a in asserts) / len(asserts), 3) if asserts else None,
        "critical_failures": [(r["id"], a["type"], a["detail"]) for r in results for a in r["critical_failures"]],
        "turns": len(turns),
        "llm_retries": sum(1 for t in llm_turns if (t["validation"] or {}).get("attempts", 1) > 1),
        "deterministic_fallbacks": sum(1 for t in turns if t["narrative_source"] == "deterministic_fallback"),
        "provider_errors": sum(1 for t in turns if t["http"] != 200 and t["error"] in PROVIDER_ERRORS
                               and not t["expected_http_error"]),
        "turns_using_fallback_model": sum(1 for t in llm_turns if any(m != primary for m in t["models_used"])),
        "latency_ms": {"median": round(statistics.median(walls)) if walls else None,
                       "p90": round(sorted(walls)[int(0.9 * (len(walls) - 1))]) if walls else None,
                       "max": max(walls) if walls else None},
    }  # fmt: skip
    md = [f"# WeatherLens evaluation — {meta['run_id']}\n",
          f"Real Gemini via POST /api/chat · model `{meta['model']}` (fallbacks `{meta['fallbacks']}`, "
          f"thinking `{meta['thinking']}`) · methodology `{meta['methodology']}` · dataset "
          f"`{meta['dataset_version']}` · weather data: committed snapshot (APIs blocked).\n",
          f"**Cases:** {summary['cases']} · **pass** {summary['n_pass']} · **pass with deterministic fallback** "
          f"{summary['n_pass_fallback']} · **fail** {summary['n_fail']} · **provider error** {summary['n_provider_error']}  ",
          f"**Case pass rate (LLM-written answers only):** {summary['case_pass_rate']:.0%} · incl. fallback "
          f"{summary['case_pass_rate_incl_fallback']:.0%}  ",
          f"**Assertions:** {summary['assertions_passed']}/{summary['assertions']} "
          f"({summary['assertion_pass_rate']:.0%}) · **critical failures:** {len(summary['critical_failures'])}  ",
          f"**Turns:** {summary['turns']} · LLM validation retries {summary['llm_retries']} · deterministic "
          f"fallbacks {summary['deterministic_fallbacks']} · turns using a fallback model "
          f"{summary['turns_using_fallback_model']} · latency median {summary['latency_ms']['median']} ms, "
          f"p90 {summary['latency_ms']['p90']} ms\n",
          "| Case | Category | Outcome | Failed assertions |", "|---|---|---|---|"]  # fmt: skip
    for r in results:
        fails = [f"{a['type']}{' (CRITICAL)' if a['critical'] else ''}: {a['detail']}"
                 for t in r["turns"] for a in t["assertions"] if a["ok"] is False]  # fmt: skip
        md.append(
            f"| {r['id']} | {r['category']} | **{r['outcome']}** | {'<br>'.join(fails) or '—'} |"
        )
    return summary, "\n".join(md) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append")
    ap.add_argument("--category", action="append")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--label", default="full")
    ap.add_argument("--base-url")
    args = ap.parse_args()
    data = yaml.safe_load((ROOT / "evals" / "cases.yaml").read_text())
    cases = data["cases"]
    if args.smoke:
        cases = [c for c in cases if c.get("smoke")]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    if args.category:
        cases = [c for c in cases if c["category"] in args.category]
    s = get_settings().model_copy(update={"offline": True})
    engine = AnalyticsEngine(build_repository(s), load_catalog(s.hubs_path),
                             load_scoring_config(ROOT / "config" / "scoring.yaml"))  # fmt: skip
    procs, clients = [], {}
    try:
        if args.base_url:
            clients["llm"] = httpx.Client(base_url=args.base_url)
        else:
            p, b = spawn(with_llm=True)
            procs.append(p)
            clients["llm"] = httpx.Client(base_url=b)
        if any(c.get("mode") == "no_llm" for c in cases):
            p, b = spawn(with_llm=False)
            procs.append(p)
            clients["no_llm"] = httpx.Client(base_url=b)
        health = clients["llm"].get("/api/health").json()
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{args.label}"
        meta = {"run_id": run_id, "model": health["llm"]["model"], "fallbacks": s.gemini_fallback_model,
                "thinking": s.llm_thinking_level, "methodology": health["methodology_version"],
                "dataset_version": data["dataset_version"], "selected_cases": [c["id"] for c in cases]}  # fmt: skip
        results = []
        for case in cases:
            try:
                res = run_case(case, engine, clients)
            except Exception as exc:  # noqa: BLE001 - record it and keep going
                res = {
                    "id": case["id"],
                    "category": case["category"],
                    "criticality": case.get("criticality"),
                    "outcome": "fail",
                    "critical_failures": [],
                    "turns": [],
                    "runner_error": f"{type(exc).__name__}: {exc}"[:300],
                }
            results.append(res)
            save(results, meta, complete=False)
            print(f"{res['outcome']:<15} {case['id']:<30} "
                  + " ".join(f"{t['wall_ms'] / 1000:.1f}s" for t in res["turns"]), flush=True)  # fmt: skip
    finally:
        for p in procs:
            p.terminate()
    summary, md = save(results, meta, complete=True)
    print("\n" + md)
    return 0 if summary["n_fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
