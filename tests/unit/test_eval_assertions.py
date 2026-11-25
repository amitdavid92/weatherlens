"""Offline tests of the EVALUATOR itself (evals/run.py assertions) on a recorded real response.

These check that the grader detects correct and incorrect answers; they are not LLM evaluations.
"""

from __future__ import annotations

import copy
import importlib.util
import json

import pytest

from tests.unit.test_analytics_engine import make_engine
from weather_risk.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("eval_run", PROJECT_ROOT / "evals" / "run.py")
eval_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eval_run)

DENVER_Q = "What percentage of days in Denver last year had snowfall?"


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    return make_engine(tmp_path_factory.mktemp("evalasserts"))


@pytest.fixture
def denver() -> dict:
    r = json.loads((PROJECT_ROOT / "web/src/test/fixtures/chat_denver.json").read_text())
    r["_http_status"] = 200
    return r


def chk(engine, r, kind, **spec):
    return eval_run.check(kind, spec, eval_run.Ctx(engine, r, DENVER_Q, None))


def test_correct_recorded_answer_passes_literal_and_grounding_checks(engine, denver):
    ok, _ = chk(engine, denver, "weather_stat", hub="denver_co", metric="snow_days_measurable",
                start="2025-01-01", event_days=26, valid_days=364, value_display="7.14%")  # fmt: skip
    assert ok
    assert chk(engine, denver, "grounded_numbers")[0]
    assert chk(engine, denver, "fact_attribution")[0]
    assert chk(engine, denver, "tool_called", name="get_weather_stat",
               args={"hub": "denver_co", "metric": "snow_days_measurable"})[0]  # fmt: skip


def test_wrong_expected_value_fails(engine, denver):
    ok, detail = chk(engine, denver, "weather_stat", hub="denver_co", metric="snow_days_measurable",
                     start="2025-01-01", event_days=27)  # fmt: skip
    assert not ok and "event_days 26" in detail


def test_fabricated_number_in_answer_is_detected(engine, denver):
    bad = copy.deepcopy(denver)
    bad["answer"] += " Overall, Denver had snow on 50% of days."
    ok, detail = chk(engine, bad, "grounded_numbers")
    assert not ok and "50%" in detail
    assert not chk(engine, bad, "answer_not_regex", pattern=r"50(\.0+)?\s?%")[0]


def test_fact_from_another_hub_is_detected(engine, denver):
    bad = copy.deepcopy(denver)
    bad["facts"].append(
        {"fact_id": "miami_fl.overall.score", "hub_id": "miami_fl", "display": "61.3"}
    )
    assert not chk(engine, bad, "fact_attribution")[0]


def test_status_and_analysis_checks(engine, denver):
    assert chk(engine, denver, "status_in", values=["answered"])[0]
    assert not chk(engine, denver, "no_analysis")[0]
    empty = copy.deepcopy(denver)
    empty["analysis"] = {k: [] for k in empty["analysis"]}
    assert chk(engine, empty, "no_analysis")[0]


def test_dataset_is_well_formed():
    import yaml

    data = yaml.safe_load((PROJECT_ROOT / "evals" / "cases.yaml").read_text())
    ids = [c["id"] for c in data["cases"]]
    assert len(ids) == len(set(ids)) and 20 <= len(ids) <= 25
    known = eval_run.KNOWN_ASSERTIONS
    for c in data["cases"]:
        assert c["category"] and c["criticality"] in {"critical", "high", "normal"} and c["turns"]
        for t in c["turns"]:
            for a in t["expect"]:
                assert a["type"] in known, f"{c['id']}: unknown assertion {a['type']}"
    cats = {c["category"] for c in data["cases"]}
    for needed in (
        "assignment",
        "multi_turn",
        "isolation",
        "false_premise",
        "unsupported",
        "fabrication",
        "prompt_injection",
        "missing_data",
        "partial_data",
        "ambiguous",
        "provider_unavailable",
    ):
        assert needed in cats


def test_every_known_assertion_is_implemented(engine, denver):
    for kind in eval_run.KNOWN_ASSERTIONS - {"deterministic_endpoints_ok"}:
        try:
            _, detail = eval_run.check(kind, {"values": [], "names": [], "value": "x", "hazard": None,
                                              "hub": "denver_co", "leader": "x", "expected": [],
                                              "pattern": "zzz", "status": 200, "error": "x",
                                              "metric": "snow_days_measurable", "period": "2025",
                                              "start": "2025-01-01", "band": "Low", "rank": 1,
                                              "name": "x"},
                                       eval_run.Ctx(engine, denver, DENVER_Q, None))  # fmt: skip
        except Exception:  # noqa: BLE001 - only the dispatch is under test here
            detail = ""
        assert "unknown assertion" not in detail, kind


def test_runner_records_non_json_and_transport_errors():
    import httpx

    assert (
        eval_run._body(httpx.Response(500, text="Internal Server Error"))["error"]
        == "non_json_response"
    )

    class Down:
        def post(self, *a, **k):
            raise httpx.ConnectError("refused")

    r, _ = eval_run.post(Down(), "hi", None)
    assert r["_http_status"] == 0 and r["error"].startswith("transport_error")
