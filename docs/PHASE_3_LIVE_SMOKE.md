# Phase 3 — Real-Gemini Smoke Results (generated)

Run at 2026-11-25T13:33:30+00:00 via `scripts/live_smoke.py` against `http://127.0.0.1:52390` (real uvicorn server, real Gemini API, POST /api/chat). Weather network disabled: `False`. These are REAL LLM calls, not mocks. Checks compare the API's structured output with the deterministic engine.

**Checks passed: 61/61.**

Health: `{"status": "ok", "methodology_version": "1.1.0", "offline_mode": false, "snapshot_entries": 255, "llm": {"available": true, "provider": "gemini", "model": "gemini-3.5-flash-lite", "reason": null}}`

## Assignment scenarios (separate sessions)

### S1: Which hubs in the Midwest are most exposed to winter disruption?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.6-flash`) · iterations 2 · latency 33924.4 ms · tokens in/out/thinking 7011/1217/2911
- tool calls: `[["rank_hubs", {"region": "Midwest", "hazard": "winter"}]]`
- data freshness: {'fema_nri': ['cache'], 'noaa_ghcn_daily': ['cache']}

**Answer:**

> Note that these risk scores measure weather-hazard EXPOSURE (a heuristic metric), not operational disruption.
> 
> Among Midwest hubs, Minneapolis Hub is the most exposed to winter weather, ranking #1 with a High exposure score of 74.0, driven by a winter weather score of 89.8 and a freezing days score of 79.5.
> 
> Detroit Hub ranks #2 with a High exposure score of 71.4, featuring a high ice storm score of 99.2.
> 
> The remaining Midwest hubs fall into the Moderate exposure band:
> - Chicago Hub ranks #3 with a score of 62.9.
> - Columbus Hub ranks #4 with a score of 58.8.
> - Kansas City Hub ranks #5 with a score of 57.2.
> - Indianapolis Hub ranks #6 with a score of 57.1.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS called rank_hubs · PASS ranking order equals engine ['minneapolis_mn', 'detroit_mi', 'chicago_il', 'columbus_oh', 'kansas_city_mo', 'indianapolis_in'] · PASS answer names #1 minneapolis_mn

### S2: Compare Miami and Houston in terms of hurricane and flood exposure.

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 23716.4 ms · tokens in/out/thinking 6038/1152/0
- tool calls: `[["compare_hubs", {"hazards": ["hurricane", "flood"], "hubs": ["miami_fl", "houston_tx"]}]]`
- data freshness: {'fema_nri': ['cache'], 'noaa_ghcn_daily': ['cache']}

**Answer:**

> When comparing Miami and Houston, note that scores measure weather-hazard EXPOSURE (heuristic), not operational disruption. Miami Hub is the leading hub for hurricane hazard exposure with a score 86.6, leading Houston Hub by a difference of 9.2 points, as Houston Hub has a score of 77.4. The FEMA annualized hurricane frequency is 0.305 per year (about 1 in 3 years) for Miami Hub and 0.184 per year (about 1 in 5 years) for Houston Hub. For flood hazard exposure, Houston Hub is the leading hub with a score of 99.0, leading Miami Hub (score 97.0) by a difference of 2.0 points. Additionally, FEMA annualized coastal flooding frequency is 2.25 per year for Miami Hub and 3.76 per year for Houston Hub, while inland flooding frequency is 4 per year for Miami Hub and 5.14 per year for Houston Hub.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS called compare_hubs · PASS hurricane leader = miami_fl · PASS flood leader = houston_tx · PASS compared ['houston_tx', 'miami_fl']

### S3: What percentage of days in Denver last year had snowfall?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 14906.3 ms · tokens in/out/thinking 8336/1336/0
- tool calls: `[["get_weather_stat", {"metric": "snow_days_measurable", "hub": "denver_co", "period": "last year"}], ["get_weather_stat", {"period": "last year", "hub": "denver_co", "metric": "snow_days_trace_inclusive"}]]`
- data freshness: {'noaa_ghcn_daily': ['cache'], 'fema_nri': ['cache']}

**Answer:**

> In 2025, the Denver Hub recorded measurable snowfall on 7.14% of valid days (26 of 364 valid days). When including trace amounts, the trace-inclusive percentage for the Denver Hub rises to 12.36%, representing 45 event days. There were 1 missing day on 2025-05-21.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS weather stat snow_days_measurable 2025 retrieved · PASS event_days = 26 · PASS answer states the engine's value · PASS answer states the year 2025 · PASS answer also gives trace-inclusive % · PASS answer discloses missing observation(s)

### S4: Why is the Dallas hub's weather disruption risk high?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.6-flash`) · iterations 2 · latency 36097.5 ms · tokens in/out/thinking 7661/1688/3753
- tool calls: `[["explain_hub_score", {"hub": "dallas_tx", "claimed_band": "High"}]]`
- data freshness: {'fema_nri': ['cache'], 'noaa_ghcn_daily': ['cache']}

**Answer:**

> Scores measure weather-hazard exposure heuristic levels, not operational disruption. Dallas Hub's overall weather-hazard exposure is in the Moderate band with a score of 58.7 (ranking #2 out of 11 hubs). However, specific High hazard components push its exposure upward:
> 
> - **Severe Convective**: Dallas Hub's primary driver with a High hazard score of 94.6, contributing 18.9 points to overall index. Key drivers are NRI hail frequency (8.92 per year, indicator score 98.4) and NRI tornado frequency (0.928 per year, indicator score 97.3).
> - **Extreme Heat**: High hazard score of 81.7, contributing 16.3 points, featuring 65.0 extreme heat days per year.
> - **Flood**: Moderate hazard score of 49.4, contributing 9.9 points, led by inland flooding frequency of 4.61 per year.
> 
> Dallas Hub also has Moderate winter exposure (score 40.6) and Low hurricane exposure (score 27.0).

**Premise correction:** Dallas Hub's overall weather-hazard exposure is in the Moderate band, not High. Scores measure weather-hazard exposure rather than operational disruption. Dallas Hub has an overall score of 58.7, ranking #2 out of 11 hubs.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS called explain_hub_score · PASS premise_correction present · PASS states band Moderate · PASS states its rank · PASS names primary driver severe_convective

## Multi-turn conversation A

### A1: Compare Miami and Houston for hurricane and flood exposure.

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 12646.9 ms · tokens in/out/thinking 6032/1201/0
- tool calls: `[["compare_hubs", {"hazards": ["hurricane", "flood"], "hubs": ["miami_fl", "houston_tx"]}]]`
- data freshness: {'fema_nri': ['cache'], 'noaa_ghcn_daily': ['cache']}

**Answer:**

> Please note that these scores measure weather-hazard EXPOSURE (heuristic), not operational disruption. For hurricane exposure, Miami Hub has score 86.6 while Houston Hub has score 77.4, making Miami Hub the leading hub with a difference of 9.2 points. Miami Hub's annualized hurricane frequency is 0.305 per year (about 1 in 3 years), compared to Houston Hub at 0.184 per year (about 1 in 5 years). For flood exposure, Houston Hub has score 99.0 and Miami Hub has score 97.0, making Houston Hub the leading hub with a difference of 2.0 points. FEMA annualized frequencies for flooding show coastal flooding at 2.25 per year for Miami Hub and 3.76 per year for Houston Hub, while inland flooding occurs at 4 per year for Miami Hub and 5.14 per year for Houston Hub.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS called compare_hubs · PASS hurricane leader = miami_fl · PASS flood leader = houston_tx · PASS compared ['houston_tx', 'miami_fl']

### A2: What about Dallas?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.6-flash`) · iterations 3 · latency 25059.0 ms · tokens in/out/thinking 9550/1071/2241
- tool calls: `[["compare_hubs", {"hubs": ["dallas_tx"], "hazards": ["hurricane", "flood"]}], ["compare_hubs", {"hazards": ["hurricane", "flood"], "hubs": ["dallas_tx", "miami_fl", "houston_tx"]}]]`
- data freshness: {'fema_nri': ['cache'], 'noaa_ghcn_daily': ['cache']}

**Answer:**

> Scores measure weather-hazard EXPOSURE (heuristic), not operational disruption.
> 
> Comparing Dallas Hub alongside Miami Hub and Houston Hub:
> 
> **Hurricane Exposure:**
> Dallas Hub registers a score of 27.0, with an annualized hurricane frequency of 0.0115 per year (about 1 in 87 years). Houston Hub has a score of 77.4, while Miami Hub leads hurricane exposure with a score of 86.6.
> 
> **Flood Exposure:**
> Dallas Hub receives a flood score of 49.4, driven by an inland flooding frequency of 4.61 per year (coastal flooding is n/a). Houston Hub leads flood exposure with a score of 99.0, while Miami Hub scores 97.0.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS Dallas resolved and queried

### A3: Which of the three has the highest hurricane exposure?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 8408.1 ms · tokens in/out/thinking 6624/686/0
- tool calls: `[["rank_hubs", {"hubs": ["dallas_tx", "houston_tx", "miami_fl"], "hazard": "hurricane"}]]`
- data freshness: {'fema_nri': ['cache'], 'noaa_ghcn_daily': ['cache']}

**Answer:**

> Among the three hubs evaluated, Miami Hub has the highest hurricane exposure with a score 86.6 (band High, rank #1). Houston Hub follows at rank #2 with a score 77.4 (band High). Dallas Hub records the lowest exposure among the three at rank #3 with a score 27.0 (band Low). Note that these scores measure weather-hazard EXPOSURE (heuristic), not operational disruption.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS context kept: three hubs · PASS answers Miami (engine leader)

### A4: Now compare their flood exposure.

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 5133.4 ms · tokens in/out/thinking 7274/944/0
- tool calls: `[["compare_hubs", {"hubs": ["miami_fl", "houston_tx", "dallas_tx"], "hazards": ["flood"]}]]`
- data freshness: {'fema_nri': ['cache'], 'noaa_ghcn_daily': ['cache']}

**Answer:**

> Comparing flood hazard EXPOSURE across the hubs (note that scores measure weather-hazard EXPOSURE heuristically, not operational disruption), Houston Hub leads with a score 99.0, edging out Miami Hub (score 97.0) by a difference of 2.0 points. Dallas Hub shows significantly lower exposure with a score of 49.4. For FEMA annualized frequencies, Houston Hub experiences coastal flooding 3.76 per year and inland flooding 5.14 per year. Miami Hub records coastal flooding 2.25 per year and inland flooding 4 per year. Dallas Hub records inland flooding 4.61 per year, while coastal flooding is n/a as it is not applicable.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS called compare_hubs · PASS flood leader = houston_tx · PASS compared ['dallas_tx', 'houston_tx', 'miami_fl']

## Multi-turn conversation B

### B1: What percentage of days in Denver last year had snowfall?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 15161.8 ms · tokens in/out/thinking 8336/1333/0
- tool calls: `[["get_weather_stat", {"metric": "snow_days_measurable", "period": "last year", "hub": "denver_co"}], ["get_weather_stat", {"hub": "denver_co", "metric": "snow_days_trace_inclusive", "period": "last year"}]]`
- data freshness: {'noaa_ghcn_daily': ['cache'], 'fema_nri': ['cache']}

**Answer:**

> In 2025, the Denver Hub recorded measurable snowfall on 7.14% of valid days (26 of 364 valid days). When including trace amounts, the trace-inclusive percentage for the Denver Hub rises to 12.36% across 45 days, capturing minor dustings alongside measurable accumulation. There was 1 missing day on 2025-05-21 for the Denver Hub, with no excluded hubs.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS weather stat snow_days_measurable 2025 retrieved · PASS event_days = 26 · PASS answer states the engine's value · PASS answer states the year 2025 · PASS answer also gives trace-inclusive % · PASS answer discloses missing observation(s)

### B2: What about 2024?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.5-flash-lite`) · iterations 2 · latency 12797.4 ms · tokens in/out/thinking 8405/1252/0
- tool calls: `[["get_weather_stat", {"period": "2024", "metric": "snow_days_measurable", "hub": "denver_co"}], ["get_weather_stat", {"hub": "denver_co", "period": "2024", "metric": "snow_days_trace_inclusive"}]]`
- data freshness: {'noaa_ghcn_daily': ['cache'], 'fema_nri': ['cache']}

**Answer:**

> In 2024, the Denver Hub recorded measurable snowfall on 6.28% of valid days (23 of 366 valid days). When including trace amounts, the Denver Hub experienced snow on 13.39% of valid days (49 days). The higher trace-inclusive percentage accounts for days with trace amounts of snow that are excluded from measurable totals. There were 0 missing days.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS weather stat snow_days_measurable 2024 retrieved · PASS event_days = 23 · PASS answer states the engine's value · PASS answer states the year 2024

### B3: Include trace snowfall.

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.6-flash`) · iterations 2 · latency 31116.8 ms · tokens in/out/thinking 6906/813/2469
- tool calls: `[["get_weather_stat", {"hub": "denver_co", "metric": "snow_days_trace_inclusive", "period": "2024"}]]`
- data freshness: {'noaa_ghcn_daily': ['cache'], 'fema_nri': ['cache']}

**Answer:**

> In 2024, Denver Hub experienced trace-inclusive snowfall on 13.39% of valid days, accounting for 49 days out of 366 valid days. Trace-inclusive snowfall combines days with measurable accumulation and days with trace amounts that do not yield measurable depth. There were 0 missing days in the dataset.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS weather stat snow_days_trace_inclusive 2024 retrieved · PASS event_days = 49 · PASS answer states the engine's value · PASS answer states the year 2024

### B4: How many days had measurable snowfall?

- HTTP 200 · status `answered` · narrative `llm` · validation valid=True attempts=1
- model `gemini-3.5-flash-lite` (version `gemini-3.6-flash`) · iterations 2 · latency 27224.2 ms · tokens in/out/thinking 7150/1140/2779
- tool calls: `[["get_weather_stat", {"metric": "snow_days_measurable", "hub": "denver_co", "period": "2024"}]]`
- data freshness: {'noaa_ghcn_daily': ['cache'], 'fema_nri': ['cache']}

**Answer:**

> In 2024, Denver Hub experienced measurable snowfall on 6.28% of days, totaling 23 of 366 valid days.
> 
> Data coverage for Denver Hub was 100.00%, with 0 missing days and 0 excluded days.

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS weather stat snow_days_measurable 2024 retrieved · PASS event_days = 23 · PASS answer states the engine's value · PASS answer states the year 2024

## Session isolation (fresh session, follow-up without context)

### I1: What about 2024?

- HTTP 200 · status `needs_clarification` · narrative `llm` · validation valid=True attempts=2
- model `gemini-3.5-flash-lite` (version `gemini-3.6-flash`) · iterations 1 · latency 18593.1 ms · tokens in/out/thinking 3222/405/923
- tool calls: `[]`
- data freshness: {}

**Answer:**

> Could you please specify which logistics hub, weather hazard, or operational metric you would like to evaluate for 2024?

**Clarification:** Could you please specify which logistics hub, weather hazard, or operational metric you would like to evaluate for 2024?

**Checks:** PASS schema+grounding valid (or labeled fallback) · PASS asks for clarification · PASS no analysis for an unmentioned hub

