# AI Collaboration Session

The assignment requires submitting the full session with the AI agent. This folder holds the reviewed exports.

## Source of truth
- **Tool:** Claude Code (VS Code extension), model Claude Opus 5.5.
- **Raw transcript:** Claude Code writes it automatically, outside the repo, at
  `~/.claude/projects/-Users-amitdavid-IdeaProjects-Tasks-Moveo-moveo-weather-risk/<session-id>.jsonl`.
  The Phase 0 and Phase 1 session is `5281f355-2997-426b-847f-1827c1714b11.jsonl`.
- **Raw files stay out of git** (`*.jsonl` is gitignored) until they have been reviewed for secrets and personal data.

## Export procedure (each phase end)
1. In Claude Code, run `/export`. It is a user-run slash command; the agent cannot invoke it. Save the result as `docs/ai-session/phase-N.md` (or `.txt`).
2. At delivery, also copy the reviewed raw `.jsonl` file or files into this folder.
3. If the work spans several sessions, export each one and list it in the index below.
4. **Before committing**, review every file for:
   - API keys and tokens, e.g. `GEMINI_API_KEY` values, `AIza…`, `sk-…`;
   - personal data such as email addresses and home-directory usernames;
   - anything else sensitive.

   Redact only those items, replacing each with `[REDACTED: <reason>]`, and log every redaction below.

**Never** edit, reorder or reconstruct conversation content. Only redact.

## Index
| File | Phases | Session id | Notes |
|---|---|---|---|
| [session-phase-0-1.txt](session-phase-0-1.txt) | 0–1 | 5281f355-2997-426b-847f-1827c1714b11 | `/export` by the user (94,157 bytes), moved into the repo unmodified. Covers Phase 0 planning/research and the Phase 1 data layer. |
| _(pending: `session-phase-2-6.txt`)_ | 2–6 | 5281f355-2997-426b-847f-1827c1714b11 | Same session, continued across several automatic context compactions. **Must be redacted before committing** (see below). |
| _(pending: `chatgpt-planning-review.md`)_ | planning/review alongside all phases | — (ChatGPT) | External ChatGPT conversation that the author used to plan and review the phase briefs. It is not in Claude Code's logs, so the author must export it from ChatGPT and run the same redaction. |

### Phase map (session 5281f355…)
| Phase | Content | Report |
|---|---|---|
| 0 | Requirements, live data-source research, plan | `docs/PHASE_0_PLAN.md` |
| 1 | Data layer: adapters, cache, snapshot, catalog | `docs/PHASE_1_REPORT.md` |
| 2 | Deterministic scoring engine, methodology 1.1.0 | `docs/PHASE_2_REPORT.md` |
| 3 | Agent, tools, grounding, API | `docs/PHASE_3_REPORT.md` |
| 4 | WeatherLens web app | `docs/PHASE_4_REPORT.md` |
| 5 | Real-Gemini evaluation, performance, QA | `docs/PHASE_5_REPORT.md` |
| 6 | Final review and submission readiness | `docs/PHASE_6_REPORT.md` |

### Exact steps for the author (agent cannot run `/export`)
1. In this Claude Code session, type `/export` and save as
   `docs/ai-session/raw/session-phase-2-6.txt`. The folder `docs/ai-session/raw/` is gitignored.
2. Redact into the committed location. The script prints counts only:
   ```bash
   uv run python scripts/redact_session.py docs/ai-session/raw/session-phase-2-6.txt \
       docs/ai-session/session-phase-2-6.txt --email <your private email>
   ```
3. Verify that nothing remains, then add the counts to the redaction log below:
   ```bash
   grep -cE 'AIza[0-9A-Za-z_-]{30,}|AQ\.[0-9A-Za-z_-]{20,}' docs/ai-session/session-phase-2-6.txt   # expect 0
   ```
4. Repeat steps 1–3 for the ChatGPT export (ChatGPT: share/export the conversation), saving it as `chatgpt-planning-review.md`.
5. Optional: copy the raw `.jsonl` through the same script for a machine-readable record.

## Review log
| File | Reviewed | Findings | Action |
|---|---|---|---|
| session-phase-0-1.txt | 2026-11-25 (pattern scan: Google `AIza…`/`AQ.…` keys, `sk-`, `ghp_`, non-empty `GEMINI_API_KEY=`, private keys, email addresses, local paths) | No credentials. The two `GEMINI_API_KEY=` matches are the placeholder `your-key-here`. Personal data: the GitHub noreply author address (already public in commit metadata, by choice) and local `/Users/amitdavid/...` paths. No private email address. | None. Content preserved verbatim. |

## Redaction log
| File | Location | What | Why |
|---|---|---|---|
| — | — | No redactions so far | — |

> **Phase 6 scan (2026-11-26) of the raw transcript `5281f355….jsonl`:**
> - one distinct Google API key (`AQ.` format, 3 occurrences): the old, exposed key;
> - 19 occurrences of the author's private email address (from tool context);
> - **the current key does not appear.**
>
> A dry run of `scripts/redact_session.py` removed all of them, with 0 residual matches. Neither the old key nor the private address is in any tracked file or in git history.
>
> **Known item for the next export:** during Phase 2 a real-looking Gemini API key was typed into the tracked `.env.example`. A file-change notification echoed it into this session, so the Phase 2+ transcript contains it. Before that export is committed, the key must be replaced with `[REDACTED: API key]` and logged here, and the key must be rotated. `.env.example` itself was never staged or committed.
