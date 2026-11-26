# AI Collaboration Record

The assignment requires the full session with the AI agent: the plan and everything else relevant to the conversation.

**The full, redacted transcripts are delivered privately to Moveo with the submission. They are not published in this repository.** They contain the author's working prompts and local environment details, which do not belong in a public repo. This page is the public index: what the record contains, how it was produced, and how it was redacted.

## What the private package contains
| File (private package) | Covers | Source |
|---|---|---|
| `claude-code-session-phase-0-1.txt` | Phase 0 planning and research, Phase 1 data layer | Claude Code `/export` by the author (reviewed 2026-11-25; no credentials) |
| `claude-code-session-phase-2-7.txt` | Phases 2–7 and the final reviews | Claude Code `/export` at the end of the session, redacted with `scripts/redact_session.py` |
| `chatgpt-planning-review.md` | The author's separate ChatGPT conversation used to plan and review the phase briefs | ChatGPT export, redacted the same way |
| `REDACTIONS.txt` | Counts and reasons for every redaction | Output of the redaction script |

- **Tool:** Claude Code (VS Code extension), model Claude Opus 5.5.
- **Session:** one long session (`5281f355…`), continued across several automatic context compactions.
- **Fidelity:** the transcripts are not edited, reordered or reconstructed. The only change is redaction, which replaces each item with `[REDACTED: <reason>]`.

## Where the work is visible in this repository
| Phase | Content | Report |
|---|---|---|
| 0 | Requirements, live data-source research, plan | [PHASE_0_PLAN.md](../PHASE_0_PLAN.md) |
| 1 | Data layer: adapters, cache, snapshot, catalog | [PHASE_1_REPORT.md](../PHASE_1_REPORT.md) |
| 2 | Deterministic scoring engine, methodology 1.1.0 | [PHASE_2_REPORT.md](../PHASE_2_REPORT.md) |
| 3 | Agent, tools, grounding, API | [PHASE_3_REPORT.md](../PHASE_3_REPORT.md) |
| 4 | WeatherLens web app | [PHASE_4_REPORT.md](../PHASE_4_REPORT.md) |
| 5 | Real-Gemini evaluation, performance, QA | [PHASE_5_REPORT.md](../PHASE_5_REPORT.md) |
| 6 | Final review and submission readiness | [PHASE_6_REPORT.md](../PHASE_6_REPORT.md) |
| 7 | Deployment preparation, demo protection, viewport fit, pre-publication review | [PHASE_7_REPORT.md](../PHASE_7_REPORT.md), [PRE_PUBLICATION_REVIEW.md](../PRE_PUBLICATION_REVIEW.md) |

Decisions are logged in [DECISIONS.md](../DECISIONS.md). Every evaluation run, including the failed ones, is in [evals/results/](../../evals/results/).

## Redaction procedure
Run the script once per export, writing to a folder outside the repo or to the gitignored `docs/ai-session/raw/`:
```bash
uv run python scripts/redact_session.py <raw export> <redacted output> --email <private address>
grep -cE 'AIza[0-9A-Za-z_-]{30,}|AQ\.[0-9A-Za-z_-]{20,}' <redacted output>   # must print 0
```
- **Removed:** Google API keys (`AIza…`, `AQ.…`), `sk-…` keys, GitHub tokens, private-key blocks, real `GEMINI_API_KEY=` values, and the given private email address.
- **Not removed:** the GitHub noreply address (public in commit metadata), plus local paths and the username, which matches the public GitHub handle.
- **Known items:** a Gemini key that was exposed early on (typed into a working copy of `.env.example`, never committed) appears 3 times in the Claude Code transcript. It has been rotated, and the script removes it. The author's private email address appears 19 times; it is removed as well. Phase 6 dry run: 22 redactions, 0 residual matches.

## History note (2026-11-26)
The Phase 0–1 export was committed in Phase 2. Before the first publication, with the author's approval, it was removed from the repository's **entire** history so that no transcript is public:
- **Method:** `git filter-branch --index-filter 'git rm --cached --ignore-unmatch docs/ai-session/session-phase-0-1.txt' -- --all`.
- **Unchanged:** every commit's author, date, message and all other file contents. This was verified commit by commit.
- **Changed:** commit IDs from that commit onward. Commit IDs cited in the phase reports were updated to the new IDs. IDs quoted inside older **commit messages** cannot change and refer to the pre-rewrite history.
- **Kept privately:** the author holds a private backup of the original history and the transcript. The transcript is part of the private package.
