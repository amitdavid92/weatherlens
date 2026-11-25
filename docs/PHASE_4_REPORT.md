# Phase 4 Report: WeatherLens Web Application

**Date:** 2026-11-25 · **Branch:** `phase-4-web-app` (from `main` at merge `c4b8206`) · **Status:** complete, awaiting review. Phase 5 has not started.

## 1. Implementation summary
**WeatherLens — Logistics Weather Risk Intelligence** is a React + TypeScript + Vite application on top of the existing FastAPI backend and Gemini agent. It has three views (Overview, AI Analyst, Methodology & Data), plus an AI Analyst panel docked beside the dashboard on screens ≥ 1280 px.

**Data integrity:**
- Every score, band, rank and statistic comes from the backend; the frontend computes none of them.
- Scores are shown using the backend's band-safe `*_display` strings, so Denver appears as **39.98 (Low)**.
- Partial hubs are shown but never ranked as comparable.

**Small additive backend change:**
- Three deterministic endpoints: `/api/overview`, `/api/rankings` and `/api/methodology`.
- Computed `*_display` fields on result models.

**Not built:** voice, alerts, authentication, deployment.

## 2. Screens and functionality
| View | What it shows |
|---|---|
| **Overview** | KPIs: 12 hubs; 11 ranked · 1 partial; highest exposure Houston 73.6 (High); 1 high-exposure hub. **US map** placing each hub at its backend coordinates (Albers USA), colored by exposure band for the selected scope, with dashed markers for partial data and keyboard support. **Exposure ranking** with an Overall / Winter / Hurricane / Flood / Severe storms / Heat switch and a region filter. Partial hubs appear under "Not ranked: incomplete data" with the readable backend reason. **Hub profile**: overall score, band and rank; five hazard scores; primary drivers (points of the overall index); NOAA data completeness per indicator; sources with freshness; methodology version; and **Ask the AI Analyst**. |
| **AI Analyst** | The four assignment questions as prominent examples. The user message appears immediately; then an honest waiting state with an elapsed-seconds counter, plus a "longer than usual (5–45 s)" note after 20 s. No fake streaming or stages. **Answer card:** premise-check banner, safe Markdown narrative, and evidence blocks rendered from the structured payload (ranking table with bars, hub comparison with leader marks and FEMA frequencies, statistic with numerator/denominator/missing/coverage, hazard-contribution drivers, profile). Footer: freshness chips, methodology version, "Facts verified" badge, sources/assumptions/limitations, model and latency. Follow-up chips; New conversation; session restored after reload; friendly 429/503/timeout/network errors with **Retry** (no duplicate turns). |
| **Methodology & Data** | What the index measures and why it is not a disruption probability; the five hazards, indicator and hazard weights; climate anchors and thresholds; the hybrid FEMA normalization (anchors labeled a *heuristic modeling assumption*); bands and the rounding policy; missing-data, not-applicable and partial-ranking rules (with Miami as the example); sources with licenses; the snapshot and freshness order; and current freshness. All numbers come from `/api/methodology`. |
| **Status bar** | Separate pills for *Analytics available* and *AI agent online/unavailable*, plus data-freshness chips (Live / Cached / Stale cache / Snapshot). |

## 3. Frontend architecture and dependencies
```
web/src/
  api/types.ts, client.ts     typed API contracts; fetch with timeouts (chat 120 s) and structured errors
  hooks/useChat.ts            conversation state shared by the full page and the docked panel
  components/                 Overview, UsMap, HubProfilePanel, ChatPanel, AnswerCard, Methodology, ui
  format.ts, examples.ts      labels only; no score math
  index.css                   design tokens + styles (navy/slate/teal; amber/red only for bands)
  test/                       Vitest setup, fetch router, recorded real API responses
web/e2e/                      Playwright: inspect.mjs (layout/console/overflow), real-gemini.mjs
```

| Dependency | Why |
|---|---|
| react, react-dom | UI |
| d3-geo, topojson-client, us-atlas | Self-contained US map: no tiles, key or network |
| react-markdown | Safe rendering of model Markdown (`skipHtml`, links disabled) |
| lucide-react | One consistent icon set |
| @fontsource-variable/inter | Self-hosted font, works offline |
| *dev:* vite, typescript, vitest, @testing-library/*, jsdom, oxlint, @playwright/test | Build, tests, lint, real-browser checks |

**Design approach** (impeccable skill, *Operate* mode):
- `PRODUCT.md` was written from your brief, without an interview.
- One sans family with tabular numerals.
- Band colors are used only for exposure.
- Teal is used for actions, selection and focus.
- Browser surfaces are themed: selection, focus ring, caret and scrollbars.
- `prefers-reduced-motion` is respected.
- The design detector (`impeccable detect`) reported **no findings**.

## 4. API integration
| Endpoint | Used by | Change in this phase |
|---|---|---|
| `GET /api/health` | Status bar, AI availability | — |
| `GET /api/overview` | KPIs, map, profile header, freshness | **New** (deterministic) |
| `GET /api/rankings?hazard=&region=` | Ranking switch | **New** (deterministic) |
| `GET /api/hubs/{id}/scores` | Hub profile | Gains `*_display` fields |
| `GET /api/methodology` | Methodology view | **New** (read-only configuration) |
| `POST /api/chat`, `GET /api/sessions/{id}` | AI Analyst | Payloads gain `*_display` fields |

- The browser calls only the Vite origin, which proxies `/api` to `127.0.0.1:8000`, so the **Gemini key never reaches the browser**.
- New backend tests cover the overview counts, the Denver display boundary, Miami partial-but-hurricane-eligible, ranking-vs-engine equality, 422 for invalid filters, and methodology content.

## 5. Screenshots (actual app, Chromium via Playwright, 2× scale)
| # | Requested view | File |
|---|---|---|
| 1 | Desktop overview dashboard | `docs/screenshots/desktop-1440-overview.png` (+ `desktop-1440-overview-miami.png`: partial profile) |
| 2 | Midwest winter ranking answer (real Gemini) | `docs/screenshots/real-gemini-1-midwest-winter.png` |
| 3 | Miami vs Houston comparison (real Gemini) | `docs/screenshots/real-gemini-2-miami-houston.png` |
| 4 | Dallas exposure explanation (real Gemini) | `docs/screenshots/real-gemini-4-dallas.png` |
| 5 | Methodology view | `docs/screenshots/desktop-1440-methodology.png` |
| 6 | Mobile layout (390 × 844) | `docs/screenshots/mobile-390-overview.png`, `mobile-390-analyst-answer.png` |
| + | Denver snowfall (real Gemini); docked panel; 1024 layout | `real-gemini-3-denver-snow.png`, `real-gemini-5-docked-panel.png`, `laptop-1024-overview.png` |

## 6. Browser validation (actual results, `web/e2e/inspect.mjs`, no LLM)
Run at 1440 × 900, 1024 × 768 and 390 × 844. Final run after the fixes below; raw output is in `docs/screenshots/inspect-results.json`.

| Check | 1440 | 1024 | 390 |
|---|---|---|---|
| Console errors / page errors / failed requests | 0 | 0 | 0 |
| Horizontal overflow: Overview / Profile / Methodology / Analyst | none | none | none |
| Ranking rows / map hubs | 11 / 12 | 11 / 12 | 11 / 12 |
| Denver profile | `39.98 Low · rank #11` | same | same |
| Miami profile | `61.3 Moderate · Partial data` | same | same |
| Hurricane filter, first row | Miami | Miami | Miami |

**Issues found by looking at the rendered app, all fixed:**
1. The nav tabs wrapped to two lines at 1440 px.
2. Exclusion reasons showed raw identifiers (`snow_days_measurable (insufficient_coverage)`). They now show readable labels (display wording only).
3. The docked panel toolbar was cramped.
4. A 29 px horizontal overflow on the mobile Analyst view, caused by a no-wrap button; it was caught by the overflow check.
5. Methodology showed raw freshness codes.

**Known artifact:** full-page screenshots show the sticky header partway down long pages. That is how Playwright captures sticky elements; it is not a layout bug.

## 7. Real-Gemini browser tests (`web/e2e/real-gemini.mjs`; REAL LLM, not mocked)
Each question was clicked in a fresh conversation on the real UI. The displayed structured values were then compared with the backend's deterministic endpoints. Raw output is in `docs/screenshots/real-gemini-results.json`.

| Question | Time to answer | Loading shown / send disabled | Displayed values vs backend |
|---|---|---|---|
| Which hubs in the Midwest are most exposed to winter disruption? | 64.8 s | yes / yes | ✅ six rows equal `/api/rankings?hazard=winter&region=Midwest` (Minneapolis 74.0 … Indianapolis 57.1) |
| Compare Miami and Houston in terms of hurricane and flood exposure. | 60.2 s | yes / yes | ✅ hurricane 86.6 vs 77.4 (Miami highest); flood 97.0 vs 99.0 (Houston highest) |
| What percentage of days in Denver last year had snowfall? | 17.4 s | yes / yes | ✅ 7.14% (26 of 364 valid days) and 12.36% including trace; 1 missing day; 2025 |
| Why is the Dallas hub's weather disruption risk high? | 79.8 s | yes / yes | ✅ 58.7 Moderate, rank #2 of 11; premise banner "Moderate, not High" |
| *Ask the AI Analyst* from the Dallas profile (docked panel) | — | docked panel opened | ✅ answer rendered beside the dashboard |

- **4 of 4 questions:** answered and validated, with displayed values matching the backend.
- **Errors:** 0 console errors.
- **Latency was higher than in Phase 3** (17–80 s against a median of 18.6 s), presumably from provider load and fallback-model use. The UI's 20-second "longer than usual" note appeared, and the 120 s client timeout was never reached. I did not optimize latency in this phase.
- **Narrative quality:** the narrative sometimes puts a numbered list in one paragraph. That is how the model writes Markdown; the UI does not rewrite model prose.

**Additional browser tests with mocked transport (not LLM evaluations):** the Vitest suite below uses recorded **real** API responses, including two real Gemini answers, served by a fetch router.

## 8. Commands and results (2026-11-25)
| Command | Result |
|---|---|
| `uv run pytest` | **307 passed**, 6 deselected (304 + 3 new endpoint tests) |
| `uv run ruff check src tests scripts` / `ruff format --check` | All checks passed / 62 files formatted |
| `cd web && npm test` (Vitest) | **9 passed** |
| `cd web && npm run lint` (oxlint) | 0 findings |
| `cd web && npm run typecheck` | OK |
| `cd web && npm run build` | OK. JS 498 kB (162 kB gzip) including map geometry; CSS 21 kB |
| `impeccable detect --json web/src` | `[]` (no design findings) |
| Fresh `git clone` → `uv sync --frozen` → pytest; `npm ci` → test/lint/typecheck/build | All pass (307 / 9 / 0 / OK / OK) |
| `make dev WEB_PORT=5181` | API and app both served; `/api/health` through the proxy returned 200 |
| `node e2e/inspect.mjs` (3 viewports) | See §6 |
| `node e2e/real-gemini.mjs` | See §7 |

**What the Vitest tests cover:**
- **Dashboard:** KPIs and ranking from API data; Denver shows 39.98 Low and never "40.0"; Dallas is #2 and Moderate.
- **Miami:** partial and listed as not ranked with a readable reason; ranked #1 for hurricane after the filter call.
- **Hub profile:** completeness, sources and the Ask action.
- **Errors:** analytics-unavailable error state.
- **Chat:**
  - immediate message, loading state, send disabled, Enter-while-pending sends nothing and keeps the draft;
  - structured statistic rendering (value, "26 of 364 valid days", Facts verified, NOAA), with no script elements;
  - ranking evidence equal to the payload; a follow-up reuses the session id;
  - a 429 shows friendly copy, and Retry produces exactly one user turn and two requests;
  - network error copy;
  - missing LLM configuration: AI pill unavailable, analytics still available, composer and examples disabled.

## 9. Known limitations and deviations
1. **Latency is 17–80 s for real answers.** The UI is honest about it, but it hurts the experience; optimization (fewer LLM calls, model choice) is a Phase 5 candidate, as agreed.
2. **No streaming:** the API is request/response, by design for this phase.
3. **Mobile is functional, not optimized:** the analyst page height is computed from viewport units, and long answers scroll inside the chat log.
4. **The map** shows Alaska and Hawaii outlines with no hubs, from the Albers USA geometry, and has no zoom. Labels appear on hover or selection, which avoids overlaps in the dense Midwest cluster.
5. **Default port 5173** was in use on this machine by an unrelated project, so the port is configurable (`WEB_PORT`) and testing ran on 5180/5181.
6. **Model prose formatting** (such as inline numbered lists) is shown as written; the structured evidence carries the authoritative values.
7. **Bundle size:** 162 kB gzip, mostly React, react-markdown and map geometry. Not split; acceptable for an internal tool.
8. **Rounding duplication:** the frontend uses backend display strings everywhere. The bands' 0/40/70 thresholds also sit in `format_score` defaults on the backend, so changing the bands in config also needs that default updated (noted for Phase 5).
9. **Deviation:** no separate mocked-provider browser suite. Mocked behavior is covered by Vitest; the browser runs used the real Gemini only.

## 10. Commits (branch `phase-4-web-app`)
| Hash | Message |
|---|---|
| `c4b8206` | Merge branch 'phase-3-agent-api' (on `main`) |
| `adcb8c6` | feat(api): deterministic overview, rankings and methodology endpoints; backend display strings |
| `48bffc6` | feat(web): WeatherLens React app — overview dashboard, AI Analyst, methodology |
| `bd0f1dc` | test(web): Vitest integration tests on recorded real API responses; Playwright browser scripts |
| `8dba198` | chore: make dev (full stack), web-* targets, frontend ignore rules |
| (next) | docs: Phase 4 report, screenshots, README, architecture, decisions |

Nothing has been pushed. `ASSIGNMENT.pdf` remains untracked.

## 11. Readiness for Phase 5
**Ready.** The full stack runs with one command and passes lint, type checks and tests from a clean clone. It has been checked in a real browser at three sizes and answered the four assignment questions end-to-end with real Gemini, with displayed values equal to the deterministic engine.

Suggested Phase 5 focus:
- a broader behavioral evaluation suite (follow-ups, unsupported and fabrication attempts) through `/api/chat`;
- latency reduction;
- a single source of truth for band thresholds in display formatting.
