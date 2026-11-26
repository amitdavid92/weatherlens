# Phase 7 Report: Secure Deployment Preparation

**Date:** 2026-11-26 · **Branch:** `phase-7-deployment`, from `main` at `d9d2506` (Phase 6 merged).

**Status:** deployment-ready. Nothing has been pushed, provisioned, purchased or published. Per the scope decision, no bonus features (voice, alerts) were added.

## 1. Deployment architecture
```
Browser ──HTTPS──► platform proxy (TLS) ──► one container, one uvicorn worker
                                            FastAPI
                                             ├─ /api/*        API (deterministic + chat)
                                             ├─ /assets/*     built React app (immutable cache)
                                             └─ /*            index.html (SPA fallback)
                                            data/snapshot/    committed data, baked into the image
                                            data/cache/       SQLite cache + sessions (ephemeral)
```
- **`Dockerfile`, multi-stage:**
  - `node:22-slim` runs `npm ci && npm run build`;
  - `python:3.12-slim` runs `uv sync --frozen --no-dev`, so dependencies install exactly as locked, with no dev tools;
  - the image includes `src`, `config`, `data/snapshot` and `web/dist`;
  - the process runs as a non-root user. Only `data/cache` is writable.
- **Startup command:** `uvicorn weather_risk.api.app:app --host 0.0.0.0 --port $PORT --workers 1`. There is exactly one worker, because the limits live in process memory.
- **Production defaults in the image:**
  - `WEATHER_RISK_OFFLINE=true`: dashboard data comes from the committed snapshot, so outages of the NOAA, FEMA or Open-Meteo APIs can't affect the demo;
  - `WEATHER_RISK_TRUSTED_PROXY_HOPS=1`;
  - CORS off (same origin).
- **`.dockerignore`** excludes `.env*` (except the example), `.git`, `docs`, eval results, `ASSIGNMENT.pdf`, `*.jsonl` and local caches.
- **`render.yaml`:** a Render Blueprint, one Docker web service with `numInstances: 1` and health check `/api/health`. Secrets are marked `sync: false`, so they are entered in the dashboard and never stored in git. Committing it creates nothing.
- **Gemini key:** server-side only. The browser talks only to the same origin, and the key never appears in the bundle (§4).

## 2. Hosting options
Prices are as listed by the providers in November 2026. Confirm them on each pricing page before purchase; Railway and Render changed prices in 2026.

| Option | Cost | Always on? | Request timeout | Memory | Persistent disk | Notes |
|---|---|---|---|---|---|---|
| **Render Starter** (recommended) | $7/month | Yes | Long (minutes; well above the ~90 s we need) | 512 MB | Paid add-on (not needed) | Native Docker, Blueprint file, health checks, zero-downtime deploys, simple dashboard secrets |
| Render Free | $0 (750 instance-hours/month) | **No**: sleeps after 15 min idle, ~1 min wake-up | Same | 512 MB, 0.1 CPU | No | Viable only if the service is woken shortly before the interview; sleeping also clears sessions |
| Railway Hobby | $5/month, includes $5 of usage | Yes | Long (minutes) | Usage-based | Volumes available | Comparable; usage-based billing is less predictable |
| Google Cloud Run | Free tier usually covers demo traffic | Scales to zero (cold starts) unless min-instances, which are billed | Up to 60 min | Configurable | No (stateless) | Must pin max-instances=1 for in-memory limits; more setup (Artifact Registry, IAM) |
| Fly.io | Usage-based, a few $/month | Configurable | Long | 256 MB+ | Volumes | More CLI setup; check current trial terms |

**Recommendation: Render Starter, for the interview window.**
- It is always on, so interviewers never hit a cold start.
- It builds this Dockerfile as-is, and `render.yaml` encodes the safe settings (one instance, health check, secrets prompted).
- The cost is a known, small, flat monthly fee. Downgrade or delete the service after the interview.
- **Free alternative:** Render Free. Open the URL a few minutes before the interview to wake it.

**Memory:** the server measured **240 MB RSS** after a full dashboard walk-through on macOS (Linux is similar or lower), well inside 512 MB.
- Before the D-044 fix it was **424 MB**, too close to the limit, because the engine held every 10-year daily dataset.
- The fix is a bounded LRU of 4 datasets. Results are unchanged, and a reload costs about 60 ms.

## 3. Public demo protection
All settings are environment variables, documented in `.env.example`. A value ≤ 0 disables a limit.

| Safeguard | Variable (default → recommended in `render.yaml`) | Behaviour when hit |
|---|---|---|
| Per-IP limits | `WEATHER_RISK_CHAT_LIMIT_PER_IP_MINUTE` 10 → 6 · `…_PER_IP_HOUR` 60 → 40 | `429 rate_limited` + `Retry-After` |
| Per-session limit | `WEATHER_RISK_CHAT_LIMIT_PER_SESSION_HOUR` 40 → 30 | `429 rate_limited` |
| App-wide daily cap (UTC day) | `WEATHER_RISK_CHAT_DAILY_LIMIT` 300 → 200 | `429 daily_limit_reached`; the dashboard keeps working |
| Bounded AI concurrency | 1 running; `WEATHER_RISK_CHAT_MAX_WAITING` 4, `WEATHER_RISK_CHAT_QUEUE_TIMEOUT_SECONDS` 30 | `503 busy` + `Retry-After` |
| Overall turn deadline | `WEATHER_RISK_CHAT_DEADLINE_SECONDS` 60; per-call `WEATHER_RISK_LLM_TIMEOUT_SECONDS` 45 → 30 | If tools already ran: labeled deterministic summary; otherwise `504 llm_timeout` |
| Demo access | `WEATHER_RISK_DEMO_PASSWORD` (unset = open), `WEATHER_RISK_DEMO_USERNAME` (`moveo`) | Browser login prompt (HTTP Basic); `/api/health` exempt |
| Client IP behind a proxy | `WEATHER_RISK_TRUSTED_PROXY_HOPS` 0 → 1 | Uses the right-most `X-Forwarded-For` entry. Client-supplied entries to its left are ignored, so a client can't spoof its way past a limit |

- **Deadline enforcement:**
  - No Gemini call or retry starts after the deadline.
  - A call's own timeout is capped at the time remaining.
  - No call starts with under 10 s left. Gemini rejects shorter per-request deadlines with HTTP 400; this was found in the rehearsal and fixed in `7d25ce6`.
  - Practical worst case: about 30 s queue wait plus 60 s deadline. The frontend's chat timeout is 120 s.
- **Errors:**
  - Provider error text (which can include project details) is logged server-side only.
  - Clients get fixed messages.
  - The synthesis-failure note in `validation.issues` carries only the error kind.
  - The frontend has clear copy for `rate_limited`, `daily_limit_reached` and `busy`.
- **Sessions:**
  - The id is a 128-bit random token (`secrets.token_urlsafe(16)`) and works as a bearer capability. It is shown only to its creator.
  - There is no endpoint that lists sessions; an unknown id returns 404.
  - `/api/chat` and `/api/sessions/*` responses are `Cache-Control: no-store`.
  - **Limitation:** anyone holding an id, for example from a shared screenshot of the network tab, can read that conversation. That is acceptable for a demo. Real use needs user accounts.
- **Security headers:** `nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`. The server header is disabled.
- **The dashboard doesn't wait for the AI.** The engine lock now covers only engine work; the agent holds it only while a tool runs. Previously one lock covered whole chat turns, so dashboard requests waited behind Gemini.
- **Not covered:** these are in-memory, single-instance controls. They do not replace a **Gemini budget alert or quota cap** in Google Cloud, which is the real spending guarantee (§7).

## 4. Storage and resilience on the selected host
| Data | Where | After a restart or redeploy | Recoverable? |
|---|---|---|---|
| Weather and hazard data | `data/snapshot/` in the image | Unchanged | Yes, it is committed and baked in |
| HTTP response cache | `data/cache/cache.db` (ephemeral disk) | Lost | Not needed in offline mode; rebuilt on demand otherwise |
| Conversations | `data/cache/sessions.db` (ephemeral disk) | **Lost** | No. Users see "This conversation has expired" and start a new one |
| Rate-limit and daily counters | Process memory | Reset | Not needed |

- **Persistent storage:** Render offers persistent disks only as a paid add-on, and attaching one disables zero-downtime deploys. It isn't needed here, so the recommendation does not use one.
- **Losing conversations on restart** is acceptable for an interview demo. No external database is introduced.
- **Without Gemini** (no key, outage or exhausted quota), the dashboard and methodology work fully from the snapshot. Chat returns a clear message. This was verified locally with no key in Phase 6, and the paths are unit-tested.

## 5. Verification (actual results, 2026-11-26)
**Docker build not run: no container runtime is installed on this machine.** Instead, every Dockerfile step was rehearsed in a clean clone, and the production server was run with production settings: `npm ci`, `npm run build`, `uv sync --frozen --no-dev` (dev tools confirmed absent), then the same uvicorn command and environment. The first real `docker build` will happen on Render, or locally if Docker is installed (§8, step 2).

| Check | Result |
|---|---|
| Backend tests | **355 passed**, 6 live tests deselected. 19 new tests in `tests/unit/test_deploy_guards.py` |
| Frontend | Vitest **14 passed**; oxlint, typecheck and build clean |
| Frontend served by FastAPI | `/` → 200 HTML; `/assets/*.js` → 200 with `immutable` cache; deep link `/analyst/x` → index.html; `/api/nope` → JSON 404; HEAD `/` → 200 (after fix) |
| Navigation after refresh | Methodology and Analyst views survive a reload (Playwright) |
| Dashboard from snapshot | Overview, rankings, methodology and hub profiles → 200; UI top row = API (Houston 73.6 High); 390 px with no overflow; no console errors |
| Real Gemini chat (production server) | "Compare Miami and Houston…" → LLM answer, valid, 4.6 s; follow-up "What about Dallas?" in the same session → valid, Dallas 27.0 / 49.4 = API. Browser: Midwest winter (Minneapolis 74.0) + "What about Denver?" (winter 56.6 = API) |
| Access protection | No credentials → 401; wrong password → 401; malformed header → 401; correct → 200; `/api/health` open; `/docs` protected |
| Per-IP limit | 2nd chat from the same IP within a minute → 429 `rate_limited`, `Retry-After: 55` |
| Spoof resistance | Changing the left-hand `X-Forwarded-For` entry did not bypass the limit; the right-most (proxy-added) entry is the key |
| Daily cap | 7th request of the day → 429 `daily_limit_reached` (tested with requests that stop before calling Gemini); dashboard still 200 |
| Session isolation | Guessed id → 404; no listing route; `no-store` on chat and history |
| Deadline (live) | 5 s budget → immediate 504 `llm_timeout`, no Gemini call. 14 s budget → normal LLM answer in 4.8 s. The rehearsal first exposed Gemini's 10 s minimum (400 → generic error); fixed and re-verified |
| Secrets | Real key: 0 matches in `web/dist`, server logs and the sessions DB; no `GEMINI` string in the bundle; demo password not logged |
| Memory | 240 MB RSS after a dashboard walk-through (424 MB before D-044) |

- **Gemini usage for this verification:** about 7 real chat turns, plus 2 that were refused by design.
- **No full evaluation was run.** Agent reasoning is unchanged. The changes affect limits, timeouts and error text, and the real-Gemini turns above all passed validation.

## 6. Deployment instructions
| Variable | Value | Secret? |
|---|---|---|
| `GEMINI_API_KEY` | Your Gemini key | **Yes** (Render: Environment → secret) |
| `WEATHER_RISK_DEMO_PASSWORD` | A new random password, e.g. `openssl rand -base64 18` | **Yes** |
| `WEATHER_RISK_DEMO_USERNAME` | `moveo` | no |
| `WEATHER_RISK_OFFLINE` | `true` | no |
| `WEATHER_RISK_TRUSTED_PROXY_HOPS` | `1` | no |
| Limits, deadline, LLM timeout | as in `render.yaml` | no |

- **Build:** Docker (`Dockerfile`). Render builds it automatically.
- **Start:** the image's `CMD`. Render provides `$PORT`.
- **Health check:** `GET /api/health` returns `{"status":"ok", "llm": {"available": true}, …}` and needs no password.
- **Demo access:** open the URL; the browser asks for the username and password once per session. Share both with the interviewers in the submission email, not in the repository.
- **Expected cost:**
  - Render Starter: $7/month flat.
  - Gemini usage is bounded by the daily cap: at most 200 chat turns a day, about 2–4 model calls each. Set a budget alert to cover the rest.

## 7. Manual steps for you
1. **Review and merge:** check `phase-7-deployment`, merge it into `main`, then push `main` to GitHub. Keep `ASSIGNMENT.pdf` local; it is gitignored.
2. **Optional local Docker check,** if Docker Desktop or OrbStack is installed:
   ```bash
   docker build -t weatherlens .
   docker run --rm -p 8000:8000 --env-file .env -e WEATHER_RISK_DEMO_PASSWORD=test weatherlens
   ```
   Then open http://localhost:8000 and log in as `moveo` / `test`.
3. **Protect the Gemini credit** (Google Cloud console, the key's project):
   - Billing → Budgets & alerts: set a budget, e.g. the prepaid amount, with email alerts at 50/90/100%.
   - Optionally, AI Studio / APIs & Services → Quotas: lower the requests-per-day for the Gemini API.
   - Consider a **dedicated key** for the deployment, so it can be revoked independently of your local key.
4. **Create the service on Render.**
   - Sign in at render.com with GitHub.
   - Choose **New → Blueprint** and select the repository. Render reads `render.yaml`.
   - Confirm the **Starter** plan (paid), or switch to Free.
   - When prompted, enter `GEMINI_API_KEY` and `WEATHER_RISK_DEMO_PASSWORD`.
   - Click Apply. The first build takes about 3–5 minutes.
5. **Verify the live URL** (`https://weatherlens-xxxx.onrender.com`):
   - `curl https://<url>/api/health` shows `"llm": {"available": true}`;
   - the browser prompts for login, and the dashboard loads;
   - ask one assignment question, then a follow-up;
   - check the Render logs: there should be no `chat_llm_error` and nothing secret.
6. **Tell me the URL** if you want a scripted post-deploy smoke check (about 3 Gemini calls).
7. **Submit:** add the URL and the demo credentials to the submission email. Do not put them in the repository.
8. **After the interview:** suspend or delete the Render service and revoke the deployment key.

## 8. Commits
- `d0af737`: single-service production build and public-demo protection
- `7d25ce6`: Gemini 10 s minimum-deadline fix; HEAD on the frontend route
- `4f9c235`: bounded climate cache (D-044)
- `dd012a0`: docs, decisions D-044/D-045 and this report
