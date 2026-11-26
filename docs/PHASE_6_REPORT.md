# Phase 6 Report: Final Engineering Review and Submission Readiness

**Date:** 2026-11-26 · **Branch:** `phase-6-review`, from `main` at `aa450ee`. Not pushed, not deployed.

## 1. Executive summary
- **Requirements:** every mandatory item in the assignment is implemented and evidenced. Neither bonus item (voice, alerts) was built. Deployment is recommended but not done (preferred, not mandatory).
- **Final evaluation (the user's paid-tier run `20261125T161815Z-full`):**
  - **22/22 cases passed** overall; 95/95 assertions; 0 critical failures.
  - **19/21 LLM-specific.** A4 and F1 passed via the labeled deterministic fallback; D1 is the no-LLM case.
- **Review fixes:**
  - one grounding false positive in premise corrections;
  - a targeted correction hint for typed numbers;
  - session-export redaction tooling;
  - `ASSIGNMENT.pdf` is now gitignored.
- **Open findings:** no Critical or High findings remain. Medium items are operational and apply to deployment; they are documented in §4.
- **Before submission:** the user must export the session transcripts, redact them with the provided script, push the code and send the email (§12).

## 2. Requirements traceability (assignment re-read 2026-11-26)
| Requirement | Location | Evidence | Status | Limitation |
|---|---|---|---|---|
| Answer the 4 example questions and generalize | `agent/`, `analytics/engine.py` | Eval A1–A4 pass; 18 more cases; browser run with real Gemini | Met | A4 is answered via the deterministic fallback in the final run |
| Public APIs for weather and hazard data | `data/adapters/` (NOAA GHCN-Daily, Open-Meteo, FEMA NRI) | Live tests (`make test-live`); `docs/PHASE_1_VALIDATION.md` | Met | The eval uses the committed snapshot, for reproducibility |
| Rank or compare by a defined KPI | `analytics/scoring.py`, `config/scoring.yaml` | Determinism and ranking tests; `docs/SCORING_METHODOLOGY.md` | Met | Heuristic exposure index, not validated against outcomes |
| Explain reasoning clearly | `explain_hub_score`, evidence UI | Drivers and contributions; F1/A4 premise correction | Met | — |
| Conversational follow-ups | `agent/session.py`, resolved context | Eval M1 (4 turns), M2 (4 turns); browser follow-up "What about Dallas?" | Met | The last 6 turns are kept in context |
| Deterministic scoring, not only the LLM | `analytics/` has no LLM imports | Unit tests; `/api/rankings` works without a key | Met | — |
| Chat interface (voice is a bonus) | `web/src/components/ChatPanel.tsx` | Vitest; Playwright real-Gemini screenshots | Met | No voice |
| Bonus: alert on score change | — | — | Not done | Listed as future work |
| Agent exposed via an API the chat uses | `POST /api/chat` (`api/app.py`), Vite proxy | `tests/unit/test_api.py`; UI uses only `/api` | Met | — |
| JSON schema between LLM and code | `agent/schema.py` `LLMAnswer`, `response_json_schema` | Schema and validation tests; retry, then fallback | Met | — |
| Small eval set plus a way to run it | `evals/cases.yaml`, `evals/run.py`, `make eval` | `evals/results/*` (every run kept) | Met | 22 cases; single runs, so no variance measured |
| Communicate assumptions, uncertainty and scope | Response `assumptions` / `limitations` / freshness; README; Methodology view | Eval exposure-framing and partial-data assertions | Met | — |
| Source code plus run instructions; live in the interview | `README.md` Quick start | Clean clone: install, tests, build, startup (§10) | Met | The chat needs a Gemini key and network |
| Deploy to a URL (preferred) | `docs/ARCHITECTURE.md` §7 | — | Recommendation only | Not deployed, by instruction |
| Design doc: architecture, repo structure, data storage | `docs/ARCHITECTURE.md` §1–3, 5–9 | — | Met | — |
| Full AI session | `docs/ai-session/` | Phases 0–1 committed; Phases 2–6 and ChatGPT need user export (§12) | **Pending user action** | `/export` is user-only |
| One-page English overview (HR) | `OVERVIEW.md` | — | Met | — |
| GitHub link and submission email | — | — | **Pending user action** | No push or email by instruction |
| Python preferred | Python 3.12 backend | — | Met | — |

## 3. A4 / F1 fallback investigation
- **F1 ("Why is Denver the most exposed hub overall?"):** there were two causes.
  1. **Code (fixed).** The superlative check read the model's correct premise correction ("the premise that Denver is the most exposed hub is incorrect") as a superlative claim about Denver.
     - **Fix:** correction vocabulary exempts a sentence only inside `premise_correction`. Narrative sentences keep the strict rule (D-043).
     - **Tests:** a regression test for the fix, and one proving that narrative wording such as "Contrary to the claim, Denver has the highest exposure" is still rejected.
  2. **Model compliance (documented, not loosened).** Gemini sometimes types a score, e.g. `39.98`, instead of `{{fact:…}}`.
     - The retry feedback now names the exact placeholder. Even so, in the targeted rerun the model typed `39.98` and `73.6` again on both attempts.
     - Rejecting typed numbers is the core control, so the safe fallback stays.
- **A4 (Dallas premise):** this was the same typed-number pattern in the full run. In the targeted rerun `20261125T215650Z-targeted-premise`, A4 passed as an LLM answer on the first attempt.
- **Targeted real-Gemini runs (kept in `evals/results/`):**
  - `…215650Z-targeted-premise`: A4 pass; F1 fail. It failed the `premise_corrected` assertion, because the fallback lacked a premise line when the model also called `rank_hubs`.
  - `…220101Z-targeted-f1-negation`, after the fix: F1 `pass_fallback`, with all assertions passing. The only remaining issues are the typed numbers.
- **What wasn't run:** no full re-evaluation, to save credits. Metrics in this report come from the final full run; `latest.*` still points to it.

## 4. Review findings (independent code and architecture review)
| Sev. | Finding | Action |
|---|---|---|
| High | F1 grounding false positive: premise correction misread as a superlative claim | **Fixed** (a0666d5), with regression tests |
| High | Old API key in the raw session transcript (outside the repo) would leak through `/export` | **Mitigated:** `scripts/redact_session.py` plus a test; documented steps; the dry run removed all 3 occurrences. The author must run it (§12) |
| Medium | `ASSIGNMENT.pdf` was untracked but not ignored, so `git add .` would commit it | **Fixed:** gitignored |
| Medium | `/api/chat` is serialized by one global lock, and there is no deadline on a whole request. Worst case, with the provider degraded: bounded, but minutes | Documented (ARCHITECTURE §4, §7). Fine for a one-user demo; a per-request deadline and per-session locks are needed before any shared deployment |
| Medium | No authentication, rate limiting or spend cap on `/api/chat` | Documented; required before a public URL (§11) |
| Low | Model-typed numbers cause occasional fallbacks (2 of 29 turns in the final run) | Documented limitation; targeted hint added |
| Low | Awkward prose in a not-applicable comparison ("not applicable for Dallas Hub with n/a") | Documented; cosmetic |
| Low | Stale config comment ("declared for later phases") | Fixed |
| Low | Vite build warns about chunk size (map and markdown libraries) | Accepted; local prototype |

**Checks that found no problem:**
- **Hardcoded answers:** scenario strings appear only in UI example cards and the Phase 1 report generator.
- **Numbers bypassing validation:** all rendering goes through the fact registry. The deterministic fallback header contains no digits.
- **Misleading freshness:** labels come from the repository on every response.
- **Silent failures:** the three broad `except` blocks log and return typed errors.
- **Retries:** HTTP and LLM retries are bounded, and the tool loop is capped at 6 iterations and 12 calls.
- **Duplicate turns:** ruled out by the chat lock and the turn number.
- **Dead code and markers:** no TODO/FIXME markers, and no `print` outside the CLI.
- **DECISIONS IDs:** no duplicates (the suspected collision was not real).

## 5. Engineering and AI design assessment
- **Strengths:**
  - a strict separation between the deterministic engine and the LLM;
  - facts-by-reference grounding;
  - honest outcome classes (`pass_fallback` is never counted as an LLM pass);
  - every result is preserved, including failures;
  - reproducible, snapshot-backed evaluations.
- **Heavier than the brief requires:** the validator rule set, the model chain with circuit breaker, and the instrumentation. Each traces to an observed failure, but they cost code surface (agent ≈ 2,000 lines).
  - The superlative and number checks are regex heuristics. They need upkeep as phrasing varies; F1 was exactly such a case.
- **Fallback behaviour:** the deterministic fallback favours correctness over fluency. That is the right trade for an investment-support tool, but the user does see it as a less polished answer.

## 6. Evaluation dataset and grader review
- **Coverage:** 22 cases across every required category. Expected values are literal and cross-checked against the engine at run time. There is no LLM judge.
- **Disclosed grader change (Phase 5):** a fallback counts as `answered`, but is classified `pass_fallback`. No expected values changed in Phase 6.
- **Gaps:**
  - a single run per case, so no variance estimate;
  - few paraphrases per intent;
  - F1 accepts "Low" anywhere in the answer or premise (adequate, but lenient).
- **Recommendation:** run three repeats before relying on the rates.

## 7. Performance (with caveats)
- **Final full run:** median 4.8 s per turn, p90 7.2 s, max 12.3 s.
- **Benchmark:** median 26.3 s before (free tier), 5.6 s after (paid tier).
- **Caveat:** the improvement mixes code changes with changes to the billing tier, provider availability, thinking configuration and load. It was not isolated (PHASE_5_REPORT §5).

## 8. Browser smoke test (isolated ports 8010/5182, real Gemini)
- **Overview, hazard filter, hub profile (Denver, Miami partial), methodology, analyst empty state:** checked at 1440, 1024 and 390 px. No console errors and no horizontal overflow.
  - Values shown match the backend: Houston 73.6 High is #1; Denver 39.98 Low is #11; Miami 61.3 Moderate is partial and not ranked; Miami tops the hurricane ranking.
- **Real Gemini conversation:** "Compare Miami and Houston…" followed by "What about Dallas?". Both were LLM-written and validated.
  - Every displayed score matches `/api/hubs/*/scores`: Miami 86.6/97.0, Houston 77.4/99.0, Dallas 27.0/49.4.
  - Screenshot: `docs/screenshots/real-gemini-followup-dallas.png`.

## 9. Documentation delivered
- **README:** rewritten for a hiring team.
- **`OVERVIEW.md`:** one page, new.
- **`docs/ARCHITECTURE.md`:** completed. It adds the agent sequence, grounding flow, data flow, SQLite rationale, deployment, trade-offs and future work.
- **PHASE_5_REPORT:** final results added, history preserved.
- **DECISIONS:** D-043 added.
- **ai-session index:** phase map, export and redaction steps.

## 10. Exact verification results (2026-11-26)
| Check | Result |
|---|---|
| `uv run pytest` | **336 passed**, 6 live tests deselected |
| `ruff check` / `ruff format --check` (src, tests, scripts, evals) | clean / 73 files formatted |
| `npm test` (Vitest) | **12 passed** |
| `npm run lint` (oxlint) / `npm run typecheck` / `npm run build` | clean / clean / built (chunk-size warning) |
| Clean clone of `phase-6-review` | `uv sync --frozen`, `npm ci`, 336 + 12 tests pass, build OK. Offline server: health OK, rankings correct, chat without a key → structured 503 |
| Secret scan | 0 key patterns in tracked files, git history or `web/dist`; no private email tracked. `.env` (mode 600) and `ASSIGNMENT.pdf` are ignored |

## 11. Deployment recommendation (not deployed)
- **Shape:** a single container. FastAPI serves `web/dist` and `/api`.
- **Secrets and data:**
  - the key goes in a platform secret;
  - the snapshot is baked into the image, with `WEATHER_RISK_OFFLINE=true` for a deterministic demo;
  - SQLite sits on ephemeral disk.
- **Platform settings:** `/api/health` as the probe; a platform timeout of at least 120 s.
- **Before a public URL, add:**
  - per-IP rate limiting;
  - a daily cap;
  - a Gemini budget alert;
  - optional basic auth.
- **Cost:** one small instance on a free or low tier. Gemini Flash-Lite cost is small at demo traffic, but unbounded without caps. Details: ARCHITECTURE §7.

## 12. Manual submission actions (author)
1. Export this Claude Code session with `/export`, saving it to `docs/ai-session/raw/session-phase-2-6.txt` (gitignored).
2. Redact it:
   ```bash
   uv run python scripts/redact_session.py docs/ai-session/raw/session-phase-2-6.txt \
       docs/ai-session/session-phase-2-6.txt --email <private email>
   ```
   Confirm that the `grep` check in `docs/ai-session/README.md` prints 0, and fill in the redaction log.
3. Export the ChatGPT planning/review conversation and redact it the same way (`chatgpt-planning-review.md`).
4. Confirm that the old Gemini key is revoked in Google AI Studio.
5. Review, merge `phase-6-review` into `main`, push to GitHub (keep `ASSIGNMENT.pdf` local), and send the link with `OVERVIEW.md`.
6. Before the interview, check Gemini quota or billing and run `make eval-smoke`.

## 13. Commits (phase-6-review)
- `a0666d5`: grounding fix and targeted runs
- `958eaf9`: redaction tooling and session index
- `ba15f93`: README, OVERVIEW, ARCHITECTURE, Phase 5 results, D-043
- this report

Phase 5 was merged into `main` at `aa450ee`, together with `fe3a7ce` (the user's final eval and benchmark artifacts).
