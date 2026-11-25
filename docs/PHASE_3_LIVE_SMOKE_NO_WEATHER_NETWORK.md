# Phase 3 — Real-Gemini Smoke Results (generated)

Run at 2026-11-25T13:44:48+00:00 via `scripts/live_smoke.py` against `http://127.0.0.1:52799` (real uvicorn server, real Gemini API, POST /api/chat). Weather network disabled: `True`. These are REAL LLM calls, not mocks. Checks compare the API's structured output with the deterministic engine.

**Checks passed: 22/22.**

Health: `{"status": "ok", "methodology_version": "1.1.0", "offline_mode": true, "snapshot_entries": 255, "llm": {"available": true, "provider": "gemini", "model": "gemini-3.5-flash-lite", "reason": null}}`

## Assignment scenarios (separate sessions)

### S1: Which hubs in the Midwest are most exposed to winter disruption?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 44184.9 ms · tokens in/out/thinking 7011/1394/0
- tool calls: `[["rank_hubs", {"region": "Midwest", "hazard": "winter"}]]`
- data freshness: {'fema_nri': ['snapshot'], 'noaa_ghcn_daily': ['snapshot']}

**Answer:**

> Based on heuristic weather-hazard EXPOSURE scores (not operational disruption), the leading hub in the Midwest for winter hazard exposure is the Minneapolis Hub, ranking #1 with score 74.0, driven by indicators such as winter weather (score 89.8) and freezing days (score 79.5). Following closely in the High band, the Detroit Hub ranks #2 with score 71.4, where top indicators include ice storms (score 99.2) and winter weather (score 76.0). In the Moderate band, the Chicago Hub ranks #3 with score 62.9; the Columbus Hub ranks #4 with score 58.8; the Kansas City Hub ranks #5 with score 57.2; and the Indianapolis Hub ranks #6 with score 57.1.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS called rank_hubs · PASS ranking order equals engine ['minneapolis_mn', 'detroit_mi', 'chicago_il', 'columbus_oh', 'kansas_city_mo', 'indianapolis_in'] · PASS answer names #1 minneapolis_mn

### S2: Compare Miami and Houston in terms of hurricane and flood exposure.

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 19192.1 ms · tokens in/out/thinking 6038/1218/0
- tool calls: `[["compare_hubs", {"hubs": ["miami_fl", "houston_tx"], "hazards": ["hurricane", "flood"]}]]`
- data freshness: {'fema_nri': ['snapshot'], 'noaa_ghcn_daily': ['snapshot']}

**Answer:**

> Comparing Miami and Houston for hurricane and flood weather-hazard EXPOSURE (heuristic), not operational disruption: for hurricanes, Miami Hub is the leading exposure location with a score 86.6, while Houston Hub has a score 77.4 (a difference of 9.2 points). FEMA annualized frequencies show hurricanes occur at 0.305 per year (about 1 in 3 years) for Miami Hub and 0.184 per year (about 1 in 5 years) for Houston Hub. For floods, Houston Hub is the most exposed with a score 99.0, compared to Miami Hub with a score 97.0 (a difference of 2.0 points). FEMA annualized frequencies for coastal flooding are 2.25 per year for Miami Hub and 3.76 per year for Houston Hub, while inland flooding frequencies are 4 per year for Miami Hub and 5.14 per year for Houston Hub.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS called compare_hubs · PASS hurricane leader = miami_fl · PASS flood leader = houston_tx · PASS compared ['houston_tx', 'miami_fl']

### S3: What percentage of days in Denver last year had snowfall?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.6-flash`) · iterations 2 · latency 45204.4 ms · tokens in/out/thinking 8324/1500/2729
- tool calls: `[["get_weather_stat", {"hub": "Denver", "period": "last year", "metric": "snow_days_measurable"}], ["get_weather_stat", {"period": "last year", "metric": "snow_days_trace_inclusive", "hub": "Denver"}]]`
- data freshness: {'noaa_ghcn_daily': ['snapshot'], 'fema_nri': ['snapshot']}

**Answer:**

> In 2025, Denver Hub experienced measurable snowfall on 7.14% of valid days (26 of 364 valid days).
> 
> When including trace snowfall, 12.36% of valid days recorded snowfall (45 of 364 valid days). Measurable snowfall reflects days with accumulating snow (>0), whereas trace-inclusive adds days with light flurries that did not accumulate.
> 
> There was 1 missing day on 2025-05-21.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS weather stat snow_days_measurable 2025 retrieved · PASS event_days = 26 · PASS answer states the engine's value · PASS answer states the year 2025 · PASS answer also gives trace-inclusive % · PASS answer discloses missing observation(s)

### S4: Why is the Dallas hub's weather disruption risk high?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=2
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 18368.7 ms · tokens in/out/thinking 9942/1694/0
- tool calls: `[["explain_hub_score", {"claimed_band": "High", "hub": "dallas_tx"}]]`
- data freshness: {'fema_nri': ['snapshot'], 'noaa_ghcn_daily': ['snapshot']}

**Answer:**

> The premise that the Dallas Hub has a high overall weather-hazard exposure score is incorrect; its overall weather-hazard EXPOSURE score is 58.7, which places it in the Moderate band at rank #2 out of 11 hubs. Note that these scores measure weather-hazard EXPOSURE (heuristic), not operational disruption. The primary driver hazard is severe convective with a score of 94.6, contributing 18.9 points to the overall index. Extreme heat is another high hazard with a score of 81.7, contributing 16.3 points. Flood and winter hazards are in the moderate band, with scores of 49.4 and 40.6, while hurricane is low with a score of 27.0.

**Premise correction:** The Dallas Hub's overall weather-hazard exposure is Moderate (score 58.7, rank #2 of 11), not High.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS called explain_hub_score · PASS premise_correction present · PASS states band Moderate · PASS states its rank · PASS names primary driver severe_convective

