# Phase 5 Report: Evaluation, Performance and QA

**Date:** 2026-11-25 · **Branch:** `phase-5-evaluation` · **Status: complete (updated in Phase 6 on 2026-11-26).**
- When this report was first written, the fixes were verified offline only, because the free-tier quota ran out.
- The user then enabled the paid tier and ran the full suite and the benchmark (§2a, §5). Those runs verified the fixes against real Gemini.
- The earlier failed and crashed runs below are kept unchanged as history.

## 1. Evaluation suite
- **Dataset:** `evals/cases.yaml` v1.0, 22 cases / 29 turns: assignment, ranking, comparison, profile, historical, multi-turn, isolation, false premise, unsupported, fabrication, injection, missing/partial data, ambiguity, provider unavailable.
- **Grading:** objective assertions on the structured API response, with literal expected values plus engine cross-checks. No LLM judge.
- **Commands:** `make eval`, `make eval-smoke`, `uv run python evals/run.py --case <id> --category <name>`.
- **Outcomes:** pass, pass_fallback (deterministic summary, not an LLM success), fail, provider_error. Results are now saved after every case.

## 2. Actual live results (all preserved in `evals/results/`)
Methodology 1.1.0, primary `gemini-3.5-flash-lite`, fallbacks `gemini-3.6-flash`, `gemini-3.5-flash`, thinking `low`, snapshot weather data.

| Run | Pass (LLM) | Pass (fallback) | Fail | Assertions | Critical | Notes |
|---|---|---|---|---|---|---|
| Full, `20261125T151306Z-full` | 9/22 (41%) | 6 (68% incl.) | 7 | 87/95 (92%) | 2 | 16/29 turns used the deterministic summary; 66 provider "unavailable" errors |
| Full "final" | — | — | — | — | — | **Crashed** after 7 cases (6 fail, 1 pass) on a non-JSON response; details lost, console kept (`history/crashed-final-run-console.log`) |
| Rerun of 8 cases, `*-rerun-failed` | 0 | 1 | 7 | 16/43 | 10 | 7 failures were HTTP 500 from the circuit-breaker bug after quota ran out |

### 2a. Final full run (user-run, paid tier): `20261125T161815Z-full`
Same dataset, grader and methodology as the runs above, but on the paid Gemini tier.

| Metric | Result |
|---|---|
| Cases | **22/22 passed**: 20 LLM-written answers, 2 labeled deterministic fallbacks (A4, F1) |
| LLM-specific success | **19/21**. D1 is the no-LLM resilience case, so 21 cases need Gemini; 19 of those were LLM-written and valid |
| Assertions / critical failures | 95/95 · 0 |
| Turns | 29 total; 4 LLM validation retries; 2 deterministic fallbacks; 0 turns needed a fallback model |
| Latency per turn | median 4,824 ms · p90 7,150 ms · max 12,298 ms |

- **What the fallbacks mean:** A4 and F1 passed every assertion, but the AI-written answer failed grounding validation twice. They are counted as `pass_fallback`, never as LLM passes.
- **Phase 6 follow-up:** see the A4/F1 investigation in `docs/PHASE_6_REPORT.md`. The targeted re-runs `20261125T215650Z-targeted-premise` and `20261125T220101Z-targeted-f1-negation` are kept in `evals/results/`. `latest.*` still points to this final full run.

## 3. The seven failures of the first full run
| Case | Cause | Action |
|---|---|---|
| A1 | Provider 503, so the deterministic summary was used; grader rejected `fallback` status; summary lacked the exposure framing | Grader and template changed |
| A2, A3, A4 | Same fallback-status rejection | Grader changed |
| R1, F1 (**critical**) | App bug: summary showed an unregistered "70%" | Fixed: registered fact |
| S1 | With no tool call, the model wrote `{{fact:dummy}}` | Prompt fixed (**not verified live**) |

**Grader change, disclosed:** it was made after seeing results. `status_in: answered` now also accepts a labeled fallback; such cases are still reported as `pass_fallback`, never as an LLM pass. No expected values changed.

## 4. Bugs found and fixed
| Bug | How found | Offline regression test |
|---|---|---|
| Unregistered "70%" in the summary | Live eval | yes |
| Summary header contained "0–100" (a regression from the first fix; explains the A1–A4 failures in the crashed run) | Offline replay | yes |
| Two rankings over different hub subsets reused a fact id → HTTP 500 | Offline probe; **probable**, unconfirmed cause of the crash (no server log then) | yes |
| All models quota-exhausted → `assert` → HTTP 500 instead of 429 (introduced this phase) | Live rerun, traceback | yes |
| Unexpected tool or API exceptions returned non-JSON 500 | Review | tool containment tested |
| Runner crashed on non-JSON and lost results | Crashed run | yes |
| Band thresholds duplicated outside the scoring config | Phase 4 note | yes |

Offline replay of the failed single-turn scenarios (scripted provider, real engine) now passes their assertions. This tests code paths only, **not Gemini quality**.

## 5. Performance
- **Bottleneck (measured):** synthesis. Overloaded primary, 3 retries with waits (about 8–10 s), then a fallback model at default thinking (19–24 s). Tool execution was under 0.1 s; tool selection about 1 s per call.
- **Changes:** fail-fast model chain, `thinking_level=low` (one probe: 4–5 s), daily-quota circuit breaker, compact tool JSON.
- **Before** (`docs/benchmarks/before.json`): 25.3 / 12.3 / 32.0 / 27.4 s, median 26.3 s.
- **After, first attempt (free tier): no valid measurement.** Every request failed. The first eval run's 13.0 s median is **not comparable**, because many turns skipped LLM synthesis.
- **After, final (user-run, paid tier, `docs/benchmarks/after.json`):** 4.5 / 5.3 / 5.8 / 7.4 s, median 5.6 s. The 7.4 s Dallas request ended in a deterministic fallback.
- **Caveat:** the median fell from 26.3 s to 5.6 s, but the gain is **not all from code.** Between the two measurements:
  - the billing tier changed, from free to paid;
  - provider availability changed, with no 503 "high demand" errors in the final run;
  - the thinking configuration changed;
  - the time of day and provider load differed.
  
  The code changes (fail-fast chain, low thinking, compact tool JSON) removed the retry-wait pattern that dominated the "before" trace. This attribution is plausible but was not isolated in a controlled experiment.

## 6. Provider limitations (as found on the free tier; the paid-tier final run hit none of them)
- Free tier: **20 requests per day per model** (seen for `gemini-3.5-flash` and `3.6-flash`); the primary also returned a quota error by the final rerun.
- `gemini-3.5-flash-lite` frequently returned 503 "high demand".
- **Interview risk:** the AI Analyst may show deterministic summaries or be unavailable. Enable billing on the Gemini project, or test quota beforehand. Overview and Methodology work without Gemini.

## 7. Checks and security
- `uv run pytest`: **332 passed**; ruff clean.
- Web: 12 Vitest passed, oxlint, typecheck and build clean.
- Browser inspection at 1440 / 1024 / 390 (no LLM): no console errors or overflow.
- `.env` ignored and untracked; no key-like strings in git history, `web/dist`, results or benchmarks. The Phase 2 key exposure still needs redaction in any later session export.

## 8. Remaining before submission
1. With quota or billing: `make eval`, then `make benchmark LABEL=after`.
2. Phase 6 documentation (one-page overview, session export).

**Readiness (updated):** items 1 and 2 are done; the final full run and the benchmark are recorded above.

## 9. Commits
`76022f6` instrumentation · `e7eb9e6` provider chain · `ab4c7e1` band source · `2c1f8ad` fact-backed summary · `3e74ee1` eval suite · plus this handover commit.
