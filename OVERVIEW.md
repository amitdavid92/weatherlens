# WeatherLens: Project Overview

**Objective.** A logistics company invests each year in weather-resilience upgrades at a few of its US distribution hubs. WeatherLens helps analysts decide which hubs are most exposed to severe weather. They can ask questions in plain English, such as "Which Midwest hubs are most exposed to winter disruption?", and get a ranking or comparison, an explanation and the sources.

**Solution.** A web dashboard (US map, rankings, hub profiles), an AI chat analyst that handles follow-up questions, and a methodology page, all served by one API.

**Technical approach.**
- Public NOAA weather-station records and FEMA National Risk Index data feed a **deterministic scoring engine**. It computes a 0–100 Weather Hazard Exposure Index across five hazards and every authoritative figure.
- **Gemini** chooses which engine tools to call and writes the explanation. It cites results by reference, and the server fills in the values.
- A **heuristic grounding validator** flags unsupported numbers and claims. If an answer still fails after one retry, the user sees a labeled summary taken directly from the engine.

**Measured results.** In the final full run of the 22-case evaluation against the real model:
- 22/22 cases passed, with 95/95 checks and no critical failures;
- in 19 of the 21 AI cases, the AI-written answer passed validation; the other two used the verified fallback;
- the median response time was about 5 seconds.

That run preceded two later changes: the Phase 6 grounding fix and the Phase 7 deployment protections. Both were verified with targeted live questions and automated tests, not a repeat of the full evaluation.

**Assumptions.**
- The index measures **exposure** (how often hazards occur near a hub), **not** the probability of disruption or loss. That would need operational data the brief doesn't provide.
- The 12 hubs are illustrative.
- Missing data is never filled in; Miami, for example, is shown but not ranked overall.
- False premises are corrected: Dallas is *Moderate*, not high.

**Limitations.**
- The weights are documented judgment calls, not validated against real outages.
- The chat depends on Gemini.
- It is a single-instance demo, live at https://weatherlens-rabk.onrender.com behind a demo password (credentials provided privately) with usage limits. It runs on Render's free tier, so the first load after 15 minutes idle takes about a minute.

**How it was built.** In eight reviewed phases:
- **Claude Code** did the research, implementation and testing.
- **ChatGPT** helped plan the phase briefs and independently reviewed the results.

The full redacted AI record is delivered privately (index: `docs/ai-session/`).

[README](README.md) · [Architecture](docs/ARCHITECTURE.md) · [Scoring methodology](docs/SCORING_METHODOLOGY.md)
