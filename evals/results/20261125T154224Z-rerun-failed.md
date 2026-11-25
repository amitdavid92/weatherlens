# WeatherLens evaluation — 20261125T154224Z-rerun-failed

Real Gemini via POST /api/chat · model `gemini-3.5-flash-lite` (fallbacks `gemini-3.6-flash,gemini-3.5-flash`, thinking `low`) · methodology `1.1.0` · dataset `1.0` · weather data: committed snapshot (APIs blocked).

**Cases:** 8 · **pass** 0 · **pass with deterministic fallback** 1 · **fail** 7 · **provider error** 0  
**Case pass rate (LLM-written answers only):** 0% · incl. fallback 12%  
**Assertions:** 16/43 (37%) · **critical failures:** 10  
**Turns:** 9 · LLM validation retries 0 · deterministic fallbacks 1 · turns using a fallback model 0 · latency median 15868 ms, p90 15868 ms

| Case | Category | Outcome | Failed assertions |
|---|---|---|---|
| A1-midwest-winter | assignment | **pass_fallback** | — |
| A2-miami-houston | assignment | **fail** | status_in: status=None<br>tool_called: calls=[]<br>comparison_leader (CRITICAL): no comparison/ranking for hazard<br>comparison_leader (CRITICAL): no comparison/ranking for hazard<br>resolved_hubs_include: resolved=[] |
| A3-denver-snow-2025 | assignment | **fail** | status_in: status=None<br>tool_called: calls=[]<br>weather_stat (CRITICAL): stats=[]<br>answer_contains_all (CRITICAL): missing=['7.14%', '2025']<br>answer_contains_any: none of ['missing', '2025-05-21']<br>answer_contains_any: none of ['trace'] |
| A4-dallas-premise | assignment | **fail** | status_in: status=None<br>tool_called: calls=[]<br>explanation (CRITICAL): no explanation<br>premise_corrected (CRITICAL): premise=''<br>answer_or_premise_contains_all: missing=['Moderate']<br>answer_contains_any: none of ['severe convective', 'Severe Convective', 'severe storms', 'convective'] |
| R1-overall-partial-miami | partial_data | **fail** | tool_called: calls=[]<br>ranking_excludes (CRITICAL): no overall ranking in analysis<br>engine_overall_ranking (CRITICAL): got=None<br>answer_contains_any: none of ['partial', 'not ranked', 'incomplete', 'excluded'] |
| C1-three-hub-winter | comparison | **fail** | resolved_hubs_include: resolved=[]<br>comparison_leader (CRITICAL): no comparison/ranking for hazard |
| S1-session-isolation | isolation | **fail** | status_in: status=None<br>status_in: status=None |
| F1-denver-false-premise | false_premise | **fail** | premise_corrected (CRITICAL): premise=''<br>answer_or_premise_contains_all: missing=['Low'] |
