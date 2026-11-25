# WeatherLens evaluation — 20261125T215650Z-targeted-premise

Real Gemini via POST /api/chat · model `gemini-3.5-flash-lite` (fallbacks `gemini-3.6-flash,gemini-3.5-flash`, thinking `low`) · methodology `1.1.0` · dataset `1.0` · weather data: committed snapshot (APIs blocked).

**Cases:** 2 · **pass** 1 · **pass with deterministic fallback** 0 · **fail** 1 · **provider error** 0  
**Case pass rate (LLM-written answers only):** 50% · incl. fallback 50%  
**Assertions:** 9/10 (90%) · **critical failures:** 1  
**Turns:** 2 · LLM validation retries 1 · deterministic fallbacks 1 · turns using a fallback model 0 · latency median 5770 ms, p90 4532 ms

| Case | Category | Outcome | Failed assertions |
|---|---|---|---|
| A4-dallas-premise | assignment | **pass** | — |
| F1-denver-false-premise | false_premise | **fail** | premise_corrected (CRITICAL): premise='' |
