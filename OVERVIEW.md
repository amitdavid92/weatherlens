# WeatherLens: Project Overview

**What it is.** WeatherLens is an AI assistant that helps a logistics company's analysts decide which US distribution hubs are most exposed to severe weather. The company uses that to choose where to invest in resilience upgrades. An analyst can ask questions in plain English:
- "Which Midwest hubs are most exposed to winter disruption?"
- "Compare Miami and Houston for hurricane and flood exposure"
- "What percentage of days in Denver last year had snowfall?"

Each answer comes with a ranking or comparison, an explanation, and the sources behind it.

**How it works.**
- **Data:** public government sources, namely NOAA daily weather station records and FEMA's National Risk Index of county hazard frequencies.
- **Scoring:** a deterministic engine turns that data into a 0–100 *Weather Hazard Exposure Index* for five hazards: winter, hurricane, flood, severe storms and extreme heat.
- **The AI model (Google Gemini):**
  - reads the question;
  - calls the engine's analysis tools;
  - writes the explanation.

  It never produces numbers itself. It refers to verified facts, which the system fills in, and a validator rejects any answer with invented or misattributed figures.
- **When the AI answer fails validation,** the user sees a clearly labeled summary taken directly from the engine instead.

**What was delivered.**
- A web application with a dashboard (US map, rankings, hub profiles), an AI chat analyst with follow-up questions, and a methodology page.
- An API, a documented scoring method and a design document.
- 330+ automated tests.
- A 22-case evaluation suite that runs against the real AI model.

**Results.**
- In the final evaluation run, all 22 cases passed, with 95 of 95 checks and no critical errors.
- In 19 of the 21 cases that use the AI, the AI-written answer passed validation. In the other two, the system correctly fell back to its verified summary.
- Typical response time is about 5 seconds.

**Judgment calls made explicit.**
- **Exposure, not disruption.** The index measures how often hazards occur around a hub, not the probability of an outage or a financial loss. That would need operational data the assignment doesn't provide, and the assistant says so.
- **Illustrative hubs.** The 12 hubs are examples, since no real hub list was given.
- **Missing data stays missing.** It is never filled in. For example, Miami's snowfall records are too sparse to use, so Miami is shown but not ranked overall.
- **Premises get checked.** When a question assumes something the data doesn't support ("Why is Dallas's risk high?"), the assistant corrects it: Dallas is *Moderate*, ranked second, driven by severe storms.

**How it was built.** The work was done in seven reviewed phases with an AI coding agent (Claude Code). Each phase was planned, implemented, tested and approved before the next began. The full session record is in `docs/ai-session/`.

**Limitations.**
- It is a local prototype: no authentication, rate limiting or deployment yet.
- The AI chat depends on Gemini's availability.
- The scoring weights are documented judgment calls that haven't been validated against real outage history. That is the main next step if this became a real tool.

**Links:**
- [README](README.md): run instructions and results
- [Architecture](docs/ARCHITECTURE.md)
- [Scoring methodology](docs/SCORING_METHODOLOGY.md)
