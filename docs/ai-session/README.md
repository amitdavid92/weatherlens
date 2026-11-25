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
| _(pending user `/export`)_ | 0–1 | 5281f355-2997-426b-847f-1827c1714b11 | Planning, research, Phase 1 data layer |

## Redaction log
| File | Location | What | Why |
|---|---|---|---|
| — | — | — | — |
