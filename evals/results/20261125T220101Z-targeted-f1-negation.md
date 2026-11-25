# WeatherLens evaluation — 20261125T220101Z-targeted-f1-negation

Real Gemini via POST /api/chat · model `gemini-3.5-flash-lite` (fallbacks `gemini-3.6-flash,gemini-3.5-flash`, thinking `low`) · methodology `1.1.0` · dataset `1.0` · weather data: committed snapshot (APIs blocked).

**Cases:** 1 · **pass** 0 · **pass with deterministic fallback** 1 · **fail** 0 · **provider error** 0  
**Case pass rate (LLM-written answers only):** 0% · incl. fallback 100%  
**Assertions:** 3/3 (100%) · **critical failures:** 0  
**Turns:** 1 · LLM validation retries 1 · deterministic fallbacks 1 · turns using a fallback model 0 · latency median 7613 ms, p90 7613 ms

| Case | Category | Outcome | Failed assertions |
|---|---|---|---|
| F1-denver-false-premise | false_premise | **pass_fallback** | — |
