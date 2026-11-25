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
| _(pending `/export`)_ | 2 and later | 5281f355-2997-426b-847f-1827c1714b11 | Same session, continued. **Needs one redaction before committing** (see below). |

## Review log
| File | Reviewed | Findings | Action |
|---|---|---|---|
| session-phase-0-1.txt | 2026-11-25 (pattern scan: Google `AIza…`/`AQ.…` keys, `sk-`, `ghp_`, non-empty `GEMINI_API_KEY=`, private keys, email addresses, local paths) | No credentials. The two `GEMINI_API_KEY=` matches are the placeholder `your-key-here`. Personal data: the GitHub noreply author address (already public in commit metadata, by choice) and local `/Users/amitdavid/...` paths. No private email address. | None. Content preserved verbatim. |

## Redaction log
| File | Location | What | Why |
|---|---|---|---|
| — | — | No redactions so far | — |

> **Known item for the next export:** during Phase 2 a real-looking Gemini API key was typed into the tracked `.env.example`. A file-change notification echoed it into this session, so the Phase 2+ transcript contains it. Before that export is committed, the key must be replaced with `[REDACTED: API key]` and logged here, and the key must be rotated. `.env.example` itself was never staged or committed.
