# Phase 3 Report: AI Agent & Backend API

**Date:** 2026-11-25 · **Branch:** `phase-3-agent-api` (from `main` at merge `f2f7ed2`) · **Status:** complete, awaiting review. Phase 4 has not started.

## 1. Implementation summary
- **Conversational agent** on real **Gemini** (`google-genai` SDK). It uses the deterministic analytics engine (methodology 1.1.0) as its only source of numbers.
- **Tools:** six typed tools with server-side Pydantic validation. Every number a tool returns is a registered **fact** with a stable id.
- **Two-phase execution:**
  1. a bounded tool loop;
  2. a provider-native JSON-schema synthesis (`LLMAnswer`), followed by Pydantic and **grounding validation**, one corrective retry, and otherwise a labeled deterministic fallback.
- **Sessions:** SQLite-backed, with bounded history and resolved context. A deterministic **unreferenced-hub guard** prevents silent guessing.
- **FastAPI** with typed models, structured errors, input limits and narrow CORS. Deterministic endpoints work without Gemini.
- **Tests:** 304 offline tests (scripted fake provider + real engine on the snapshot); **real-Gemini smoke scenarios** through HTTP; documentation.

| New / changed | Purpose |
|---|---|
| `agent/llm.py`, `gemini.py`, `fake.py` | Provider interface + typed errors; Gemini implementation; scripted test provider |
| `agent/tools.py`, `facts.py` | Typed tools; per-turn fact registry |
| `agent/schema.py` | `LLMAnswer` (LLM ↔ code schema) and `ChatRequest`/`ChatResponse` (API) |
| `agent/grounding.py` | Validation + deterministic rendering + fallback summary |
| `agent/orchestrator.py`, `session.py` | Agent loop, prompts, guard; SQLite sessions |
| `api/app.py` | FastAPI app factory and endpoints |
| `analytics/formatting.py` | Band-safe score display (D-026) |
| `scripts/live_smoke.py` | Real-Gemini smoke suite (spawns uvicorn, checks against engine) |
| `docs/ARCHITECTURE.md` | Components, flow, repository structure, storage choice, security |

## 2. Security and methodology checks (before implementation)
| Check | Result |
|---|---|
| `.env` gitignored and untracked | Yes (`git check-ignore`; not in `git ls-files`) |
| `.env.example` free of credentials | Yes. 0 non-empty `GEMINI_API_KEY=` lines, and 0 ever committed (`git log -p`) |
| Gemini key configured | Yes. Checked only as a boolean; never printed, copied or logged (loaded as `SecretStr`) |
| Session redaction requirement | Preserved: the next transcript export must redact the key that leaked into the session in Phase 2 (see `docs/ai-session/README.md`). **Rotate that key.** |
| Denver around the 40 boundary | Unrounded 39.975 is **Low**, but was displayed as "40.0". New rounding policy (D-026): bands use the unrounded score; the display adds decimals rather than cross a band, so it shows **39.98**. Regression tests added. |
| Hybrid anchors wording | Now described as a **heuristic modeling assumption**, not a universal scientific standard (methodology doc, `scoring.yaml`, D-022) |

## 3. Agent execution flow
```
POST /api/chat {message, session_id?}
 ├─ load session: last 6 turns + resolved context (hubs, hazards, metric, period)
 ├─ TOOL PHASE  (≤ 6 iterations, ≤ 12 tool calls)
 │    Gemini(system rules + history + 6 tool declarations, automatic calling disabled)
 │    for each call: unreferenced-hub guard → Pydantic args → engine → facts → compact payload
 ├─ SYNTHESIS   Gemini(JSON schema = LLMAnswer, no tools) → Pydantic → grounding validation
 │    invalid → 1 retry with the exact issues → still invalid → deterministic fallback
 ├─ RENDER      {{fact:id}} → deterministic display; attach analysis/facts/sources/freshness
 └─ store turn in SQLite; return ChatResponse
```

## 4. Model selection
Probed live on 2026-11-25, without assuming any capability:

| Model | Result |
|---|---|
| `gemini-2.5-flash` | 404: no longer available to new users |
| `gemini-3.8-flash` | 503: overloaded at probe time |
| `gemini-3.5-flash` | Function calling OK (18 s on the first call). **Tools + schema in one call skipped the tool call** (D-028). API reports `model_version` = `gemini-3.6-flash`. |
| **`gemini-3.5-flash-lite`** | Function calling and JSON-schema output OK, ~0.7 s per probe call |

**Configuration:**
- **Primary:** `gemini-3.5-flash-lite`, the cost-effective, fast choice for tool routing plus constrained synthesis.
- **Fallback:** `gemini-3.5-flash`, used only on 503 or timeout after retries.
- Both are set in `.env`, along with a 45 s timeout and 3 attempts.
- **On 429, the agent:**
  1. honors Gemini's `retryDelay`, capped at 20 s;
  2. otherwise returns HTTP 429 `llm_quota_exceeded`;
  3. does not switch models.

## 5. Tool contracts
All arguments are strict Pydantic models (`extra=forbid`, enums, length limits), declared to Gemini as JSON schema.

| Tool | Arguments | Output (LLM-facing; every number is `{fact, value[, unit]}`) |
|---|---|---|
| `list_hubs` | `region?` ∈ Midwest/South/West/Northeast | Hub cards (illustrative) |
| `get_hub_profile` | `hub` (id/name/alias) | Overall + 5 hazards + indicators, eligibility, notes |
| `rank_hubs` | `hazard?` ∈ 5 hazards, `region?`, `hubs?` (≤ 12) | Ranked (rank + score facts), not-ranked with reasons, top contributors |
| `compare_hubs` | `hubs` (2–6), `hazards?` | Per-hazard scores, leader, difference, FEMA frequencies |
| `get_weather_stat` | `hub`, `metric` ∈ 5 metrics, `period` (last year, YYYY, ranges, last N years, past 12 months, climatology), `source` ∈ noaa/open_meteo | % of valid days, counts, coverage, missing dates, period |
| `explain_hub_score` | `hub`, `claimed_band?` ∈ Low/Moderate/High | Hazard-level contributions, top indicators, rank, premise check |

**Tool errors:** returned as typed payloads; never raised to the LLM as numbers. The types are `invalid_arguments`, `unsupported_hub`, `ambiguous_hub`, `unreferenced_hub`, `invalid_request`, `data_unavailable`, `payload_too_large` (24 KB cap) and `unknown_tool`.

## 6. Structured output schema (`LLMAnswer`)
| Field | Content |
|---|---|
| `status` | `answered` / `needs_clarification` / `unsupported` / `insufficient_data` |
| `intent` | rank / compare / weather_stat / explain / profile / list_hubs / clarify / other |
| `narrative` | Markdown, ≤ 4000 characters. Numbers **only** as `{{fact:<id>}}` |
| `cited_facts[]` | `{fact_id, hub_id}` |
| `resolved_hubs[]`, `resolved_hazards[]`, `resolved_metric`, `resolved_period` | What the answer is about |
| `premise_correction`, `clarification_question` | Same placeholder rules as the narrative |
| `follow_up_suggestions[]` | ≤ 3 |

The API `ChatResponse` adds:
- the rendered `answer` and `narrative_source` (llm / deterministic_fallback / none);
- `resolved`, the verified `facts` used, and `analysis` (authoritative engine payloads: rankings, comparisons, weather_stats, explanations, profiles);
- `sources`, `data_freshness`, `methodology_version`, `assumptions`, `limitations`;
- `validation` (valid, attempts, issues, retry_reasons, fallback_used);
- `agent` (provider, model, model_version, iterations, tool calls, tokens, latency).

## 7. Grounding and validation strategy
1. **Schema:** provider-native `response_json_schema`, then Pydantic `LLMAnswer`.
2. **Fact existence:** every placeholder and citation must exist in *this turn's* registry.
3. **Attribution:**
   - a citation's `hub_id` must match the fact's owner (null means unspecified);
   - a placeholder may not sit in a sentence that names other hubs but not its owner.

   A real number from a different hub or metric therefore fails.
4. **No typed numbers:** digits outside placeholders are rejected, except:
   - small counts (≤ 12);
   - years present in fact periods or the user's question;
   - constants from tool definition text.

   This applies to the narrative, premise correction and clarification.
5. **Topic-aware superlatives:** "highest / most exposed / leads" about a hub must match the rank-1 hub or the comparison leader *for the hazard named in the sentence*.
6. **Premise:** if the engine marked the user's claim unsupported, `premise_correction` is required.
7. **Consistency:**
   - resolved hubs must be catalog ids;
   - analytical answers must cite facts;
   - "answered" needs at least one successful tool;
   - a clarification needs its question.

**Guard against silent guessing (D-030):** tool calls are refused for hubs that neither the message nor the recent context mentions.

**Prompt injection:** user text is wrapped as untrusted, and the validator blocks injected numbers regardless of the model.

**Known gap:** validation guarantees the provenance and attribution of numbers, not the full *semantic* correctness of every sentence. A misleading but number-free phrasing can still pass. The authoritative payloads are returned alongside the narrative for this reason.

## 8. Session management
- **Storage:** SQLite `data/cache/sessions.db` (gitignored), with tables `sessions` and `turns` (user message + full response JSON).
- **Session ids:** random (`secrets.token_urlsafe(16)`), server-generated. An unknown id returns 404.
- **Context:** the last 6 turns go to the model, plus a `[resolved context: …]` line taken from the previous structured answer. A new session starts empty (isolation verified offline and live).
- **Ambiguity:** handled by prompt rules plus the deterministic guard, which yields `needs_clarification`.

## 9. API endpoints
| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | Methodology version, offline mode, snapshot size, LLM availability (provider, model, reason) |
| GET | `/api/hubs` | Illustrative catalog |
| GET | `/api/hubs/{hub_id}/scores` | Deterministic `HubProfile` (no LLM). 404 unknown hub; 422 malformed id; 503 data unavailable |
| POST | `/api/chat` | `{message (1–2000 chars), session_id?}` → `ChatResponse`. Errors: 422 invalid, 404 unknown session, 503 `llm_unavailable` / `llm_auth_error`, 429 `llm_quota_exceeded`, 504 `llm_timeout` |
| GET | `/api/sessions/{session_id}` | Conversation history |

- Errors use one shape: `{error, detail, retryable}`.
- OpenAPI docs are at `/docs`.
- CORS allows only `http://localhost:5173` and `http://127.0.0.1:5173` (configurable), and only GET/POST.

## 10. Real-Gemini results
All results go through `POST /api/chat` on a real uvicorn server. Full answers, tool calls and metrics are in [PHASE_3_LIVE_SMOKE.md](PHASE_3_LIVE_SMOKE.md) and [PHASE_3_LIVE_SMOKE_NO_WEATHER_NETWORK.md](PHASE_3_LIVE_SMOKE_NO_WEATHER_NETWORK.md). Each check compares the structured response with the v1.1.0 engine.

**Final runs (code at `be39f26`):**

| Run | Turns | Checks passed | Narrative source | Retries | Deterministic fallbacks |
|---|---|---|---|---|---|
| Full: 4 scenarios + conversations A, B + isolation (live weather/cache) | 13 | **61/61** | LLM 13/13 | 1 (I1) | 0 |
| Weather APIs blocked (dead proxy; Gemini excluded) + empty cache | 4 | **22/22** | LLM 4/4 | 1 (S4) | 0 |

In the blocked run, every turn reported `data_freshness = {noaa_ghcn_daily: [snapshot], fema_nri: [snapshot]}`, so the snapshot fallback and its labels work with a real LLM.

### Actual answers (full run, verbatim, rendered from fact ids)
**S1: Which hubs in the Midwest are most exposed to winter disruption?** (tool `rank_hubs{hazard: winter, region: Midwest}`)
> Among Midwest hubs, Minneapolis Hub is the most exposed to winter weather, ranking #1 with a High exposure score of 74.0, driven by a winter weather score of 89.8 and a freezing days score of 79.5. Detroit Hub ranks #2 with a High exposure score of 71.4, featuring a high ice storm score of 99.2. The remaining Midwest hubs fall into the Moderate exposure band: Chicago #3 (62.9), Columbus #4 (58.8), Kansas City #5 (57.2), Indianapolis #6 (57.1).

The order matches the engine exactly.

**S2: Compare Miami and Houston in terms of hurricane and flood exposure.** (tool `compare_hubs{[miami_fl, houston_tx], [hurricane, flood]}`)
> Miami Hub is the leading hub for hurricane hazard exposure with a score 86.6, leading Houston Hub by a difference of 9.2 points … FEMA annualized hurricane frequency is 0.305 per year (about 1 in 3 years) for Miami Hub and 0.184 per year (about 1 in 5 years) for Houston Hub. For flood hazard exposure, Houston Hub is the leading hub with a score of 99.0, leading Miami Hub (score 97.0) by a difference of 2.0 points …

The leaders match the engine. Miami's partial snow data did not block the comparison.

**S3: What percentage of days in Denver last year had snowfall?** (two `get_weather_stat` calls: measurable and trace-inclusive, period "last year", resolved to 2025)
> In 2025, the Denver Hub recorded measurable snowfall on 7.14% of valid days (26 of 364 valid days). When including trace amounts, the trace-inclusive percentage for the Denver Hub rises to 12.36%, representing 45 event days. There were 1 missing day on 2025-05-21.

The values equal the engine's. There is a minor grammar slip ("There were 1 missing day").

**S4: Why is the Dallas hub's weather disruption risk high?** (tool `explain_hub_score{dallas_tx, claimed_band: High}`)
> **Premise correction:** Dallas Hub's overall weather-hazard exposure is in the Moderate band, not High. … overall score of 58.7, ranking #2 out of 11 hubs.
> Severe Convective: Dallas Hub's primary driver with a High hazard score of 94.6, contributing 18.9 points … hail (8.92 per year, indicator score 98.4) and tornado (0.928 per year, indicator score 97.3). Extreme Heat: 81.7, contributing 16.3 points … Flood 49.4 … winter 40.6 and Low hurricane exposure (27.0).

This distinguishes Dallas's relatively high rank (#2) from its Moderate band, and corrects the premise.

### Multi-turn conversations (full run)
| Turn | Tool calls (actual) | Result |
|---|---|---|
| A1 "Compare Miami and Houston for hurricane and flood exposure." | `compare_hubs` | Leaders hurricane = Miami, flood = Houston ✓ |
| A2 "What about Dallas?" | `compare_hubs` × 2 (first had invalid args, corrected by the model) | Dallas added to the same hazards ✓ |
| A3 "Which of the three has the highest hurricane exposure?" | `rank_hubs{hubs: 3, hurricane}` | "Miami … rank #1 … Houston #2 … Dallas #3" ✓ |
| A4 "Now compare their flood exposure." | `compare_hubs{3 hubs, flood}` | Flood leader Houston ✓ |
| B1 "What percentage of days in Denver last year had snowfall?" | `get_weather_stat` × 2 | 7.14% / 12.36%, 2025 ✓ |
| B2 "What about 2024?" | `get_weather_stat` × 2 (2024) | Values equal the engine (23 days measurable) ✓ |
| B3 "Include trace snowfall." | trace-inclusive, 2024 | 13.39%, 49 of 366 valid days ✓ |
| B4 "How many days had measurable snowfall?" | measurable, 2024 | "23 of 366 valid days … 0 missing days" ✓ |
| I1 (fresh session) "What about 2024?" | none | `needs_clarification`: "Could you please specify which logistics hub…" ✓ |

### Latency, tokens and models (actual; per turn, including all LLM calls)
| Run | Latency per turn | Tokens in / out (+ thinking) per turn | Turns finished by fallback model* |
|---|---|---|---|
| Full (13 turns) | **5.1–36.1 s, median 18.6 s** | ~3.2k–9.6k / 0.4k–1.7k (+0–3.8k) | 6/13 |
| Blocked weather (4 turns) | 18.4–45.2 s | ~6.0k–9.9k / 1.2k–1.7k (+0–2.7k) | 1/4 |

\* `model_version` of the last LLM call was `gemini-3.6-flash`. That is the version the API reports for the configured fallback `gemini-3.5-flash`, which is used after the primary returns 503 or times out. Thinking tokens appear only on those turns.

**Rate limits:**
- **During development:** two turns of an earlier conversation run returned HTTP 429. That was the free-tier per-minute limit, which recovered within a minute.
- **Response:** the provider now honors `retryDelay`, and the smoke script paces turns by 6 s and retries a 429'd turn once after 60 s. No 429 occurred in the final runs.

**Latency** is high: primary overload pushed requests to the slower fallback, and each turn makes 2–4 LLM calls. As instructed, I did not optimize it in this phase (candidate for Phase 5).

### Earlier live runs (development history, not hidden)
Each of these was caught by a live run and led to a fix:
- **S4 fallback:** the model typed "58.7" in `premise_correction`, which wasn't validated at the time. Validation now covers every LLM text field.
- **Over-strict check:** a follow-up suggestion mentioning another year was rejected. Suggestions are now excluded from the numeric check.
- **Weak isolation check:** "What about 2024?" in a fresh session was answered **about Chicago**, and my smoke check didn't catch it. The fix is the unreferenced-hub guard plus a stricter check.
- **Superlatives:** the check accepted a hub that led a *different* hazard. It is now topic-aware.
- **Null citations:** a citation with `hub_id: null` was rejected as a mismatch. Null now means "unspecified".

## 11. Offline test results
| Command | Result |
|---|---|
| `uv run pytest` | **304 passed**, 6 deselected (live) |
| `uv run ruff check src tests scripts` / `ruff format --check` | All checks passed / 62 files formatted |
| Fresh `git clone` → `uv sync --frozen` → `pytest` | 304 passed. Without a key: `/api/hubs/denver_co/scores` 200, `/api/chat` 503 `llm_unavailable` |

**What the new tests cover (offline):**
- **Tools:** argument validation (8 error types); payload numbers are fact references that match the engine.
- **Agent with the scripted provider:**
  - grounded rendering;
  - invalid JSON → retry; schema violation twice → labeled fallback; no tool results → error (not an answer);
  - unknown facts, fabricated numbers, prompt-injected numbers;
  - wrong-hub attribution (citation and sentence); topic-aware superlatives;
  - false premise required; premise digits validated; unsupported hub; clarification;
  - multi-turn context; session isolation; unknown session;
  - iteration and tool-call limits; unreferenced-hub guard; typed provider errors.
- **Gemini provider (stubbed SDK):** error classification (401/403/400-key/429/5xx/timeout/connect), `retryDelay` parsing, bounded retries, fallback on 503, no retry on auth errors, no fallback on 429.
- **API:** deterministic endpoints without an LLM, 503 instead of a fake model, structured 404/422, input validation, full contract, history, error-to-status mapping, narrow CORS, OpenAPI paths.
- **Formatting:** band-safe rounding (Denver 39.98, and the 39.9999 edge case).

The fake-provider tests verify our code paths. **They are not LLM evaluations.** Real behavior is measured by `make smoke-live`.

## 12. Security checks (final)
- Every staged diff was scanned for `AIza…`, `AQ.…`, non-empty `GEMINI_API_KEY=` and Gmail addresses: clean in every commit. `.env` was never staged; `.env.example` contains only empty placeholders.
- The key is held as a `SecretStr`. Logs record model, latency, token counts and error kinds, never the key or full prompts.
- The LLM has six read-only tools and no code, HTTP or database access. Inputs are length-limited and tool payloads size-capped.
- **Prototype limitations:**
  - no API authentication or rate limiting;
  - a single process with a lock serializing engine access;
  - no TLS;
  - sessions are not encrypted at rest;
  - the session id is the only access control.

## 13. Known limitations, deviations, blockers
1. **Latency** is 5–45 s per turn: 2–4 LLM calls per turn, plus fallback usage when the primary is overloaded. Not optimized, as instructed.
2. **Model availability:** preview-era model names change (2.5-flash already retired for new users). The fallback model served about 40% of final live turns.
3. **Reliability is measured on a small sample:** 17 final live turns, all valid, 2 of them after one corrective retry. That is a smoke test, not a statistically meaningful evaluation; Phase 5 adds the behavioral suite. The validator caught real model errors (typed numbers) in both runs.
4. **Semantic validation is partial** (see §7). The style has minor grammar issues ("There were 1 missing day").
5. **Free-tier quota:** bursts can hit per-minute limits, which return 429 `llm_quota_exceeded` to the client.
6. **Deviation:** the smoke scenarios are a script (`scripts/live_smoke.py`, `make smoke-live`), not pytest. That keeps them out of the default suite and makes them easy to run against a live server.
7. **No blockers.** **Action for you:** rotate the Gemini key exposed during Phase 2, and redact it from the next session export.

## 14. Commits (branch `phase-3-agent-api`)
| Hash | Message |
|---|---|
| `f2f7ed2` | Merge branch 'phase-2-risk-engine' (on `main`) |
| `4df462f` | feat(agent): Gemini-backed grounded agent with typed tools, fact registry and validation |
| `1fac3eb` | feat(api): FastAPI endpoints for health, hubs, hub scores, chat and session history |
| `55ee878` | test(agent,api): offline tests for tools, grounding, retries, sessions, limits and API contracts |
| `be39f26` | feat(scripts): real-Gemini smoke scenarios through the HTTP API; band-safe scores in reports |
| (next) | docs: Phase 3 report, architecture, live smoke results, decisions, README |

Nothing has been pushed. `ASSIGNMENT.pdf` remains untracked.

## 15. Readiness for Phase 4
Phase 3 is **ready.** The chat UI can rely on:
- `POST /api/chat`: `answer` for display; `analysis` for tables and charts; `facts`, `sources` and `data_freshness` for provenance; `validation` and `narrative_source` for trust labels; `follow_up_suggestions`; `clarification_question`; `premise_correction`.
- `GET /api/sessions/{id}`: conversation history.
- `GET /api/hubs` and `/api/hubs/{id}/scores`: deterministic views that work even when Gemini is unavailable.

CORS is already configured for the Vite dev server (`localhost:5173`). The UI should show the latency and a loading state, and label fallback answers.
