"""FastAPI application.

    uv run uvicorn weather_risk.api.app:app --reload        (or: make api)

Deterministic endpoints (/api/health, /api/hubs, /api/hubs/{id}/scores) never need the LLM.
/api/chat needs a configured Gemini key; otherwise it returns 503 `llm_unavailable` — it never
substitutes a fake model.
"""

from __future__ import annotations

import base64
import logging
import secrets
import threading
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from weather_risk.agent.gemini import GeminiProvider
from weather_risk.agent.llm import (
    LLMAuthError,
    LLMError,
    LLMNotConfiguredError,
    LLMProvider,
    LLMQuotaError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from weather_risk.agent.orchestrator import Agent
from weather_risk.agent.schema import ChatRequest, ChatResponse, ErrorResponse
from weather_risk.agent.session import SessionNotFoundError, SessionStore
from weather_risk.analytics.config import load_scoring_config
from weather_risk.analytics.engine import AnalyticsEngine
from weather_risk.analytics.models import HubProfile, RankingResult
from weather_risk.api.guard import ChatSlots, DailyCounter, SlidingWindowLimiter, client_ip
from weather_risk.catalog import load_catalog
from weather_risk.config import PROJECT_ROOT, Settings, get_settings
from weather_risk.data.errors import DataUnavailableError, UnsupportedHubError
from weather_risk.data.repository import build_repository
from weather_risk.logging_setup import configure_logging

log = logging.getLogger("weather_risk.api")

ERRORS = {
    400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
    429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}, 504: {"model": ErrorResponse},
}  # fmt: skip


class AppState:
    def __init__(self, settings: Settings, engine: AnalyticsEngine,
                 provider: LLMProvider | None, provider_error: str | None,
                 sessions: SessionStore) -> None:  # fmt: skip
        self.settings = settings
        self.engine = engine
        self.provider = provider
        self.provider_error = provider_error
        self.sessions = sessions
        # Serializes ENGINE access only (dashboard endpoints and agent tool execution). The LLM
        # calls of a chat turn run outside it, so the dashboard never waits for Gemini.
        self.lock = threading.RLock()
        self.agent = Agent(engine, provider, sessions, engine_lock=self.lock) if provider else None
        s = settings
        self.ip_minute = SlidingWindowLimiter(s.chat_limit_per_ip_minute, 60)
        self.ip_hour = SlidingWindowLimiter(s.chat_limit_per_ip_hour, 3600)
        self.session_hour = SlidingWindowLimiter(s.chat_limit_per_session_hour, 3600)
        self.daily = DailyCounter(s.chat_daily_limit)
        # One AI request at a time: the provider and session turn numbering keep per-turn state.
        self.chat_slots = ChatSlots(1, s.chat_max_waiting, s.chat_queue_timeout_seconds)


def build_state(settings: Settings, *, provider: LLMProvider | None = None,
                engine: AnalyticsEngine | None = None) -> AppState:  # fmt: skip
    if engine is None:
        engine = AnalyticsEngine(build_repository(settings), load_catalog(settings.hubs_path),
                                 load_scoring_config(PROJECT_ROOT / "config" / "scoring.yaml"))  # fmt: skip
    error = None
    if provider is None:
        try:
            key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
            provider = GeminiProvider(api_key=key, model=settings.gemini_model,
                                      fallback_model=settings.gemini_fallback_model,
                                      timeout_seconds=settings.llm_timeout_seconds,
                                      max_attempts=settings.llm_max_attempts,
                                      thinking_level=settings.llm_thinking_level or None)  # fmt: skip
        except LLMNotConfiguredError as exc:
            provider, error = None, str(exc)
    return AppState(settings, engine, provider, error, SessionStore(settings.sessions_path))


def create_app(state: AppState | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "ctx", None) is None:
            s = get_settings()
            configure_logging(s.log_level)
            app.state.ctx = build_state(s)
        try:  # warm the deterministic engine so the first dashboard request is fast
            with app.state.ctx.lock:
                app.state.ctx.engine.rank_hubs()
        except Exception:  # noqa: BLE001 - endpoints report data problems themselves
            log.warning("engine_warmup_failed", exc_info=True)
        yield

    app = FastAPI(
        title="Weather Risk Intelligence Agent API",
        version="0.3.0",
        description=(
            "Grounded AI agent over a deterministic Weather Hazard Exposure Index (heuristic "
            "0–100 exposure, not disruption probability) for 12 illustrative US distribution "
            "hubs. Numbers come from the analytics engine; the LLM only selects tools and writes "
            "narrative referencing verified fact ids."
        ),
        lifespan=lifespan,
    )
    app.state.ctx = state
    settings = state.settings if state else get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def ctx(request: Request) -> AppState:
        return request.app.state.ctx

    @app.middleware("http")
    async def protect(request: Request, call_next):
        """Optional shared demo password (HTTP Basic) plus baseline security headers."""
        c: AppState | None = request.app.state.ctx
        pw = c.settings.demo_password if c else None
        if pw and request.url.path != "/api/health" and not _authorized(request, c.settings):
            return Response(status_code=401, content="Authentication required",
                            headers={"WWW-Authenticate": 'Basic realm="WeatherLens demo"'})  # fmt: skip
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith(("/api/chat", "/api/sessions")):
            response.headers["Cache-Control"] = "no-store"
        return response

    def err(status: int, error: str, detail: str, retryable: bool = False) -> JSONResponse:
        return JSONResponse(status_code=status,
                            content=ErrorResponse(error=error, detail=detail,
                                                  retryable=retryable).model_dump())  # fmt: skip

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        detail = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                           for e in exc.errors())[:500]  # fmt: skip
        return err(422, "invalid_request", detail)

    @app.exception_handler(HTTPException)
    async def http_handler(_: Request, exc: HTTPException):
        d = exc.detail if isinstance(exc.detail, dict) else {"error": "http_error",
                                                              "detail": str(exc.detail)}  # fmt: skip
        resp = err(exc.status_code, d["error"], d["detail"], d.get("retryable", False))
        for k, v in (exc.headers or {}).items():
            resp.headers[k] = v
        return resp

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.error("unhandled_error", exc_info=exc)
        return err(500, "internal_error", "The server could not process the request.")

    @app.get("/api/health", tags=["system"], summary="Service, data and LLM status")
    def health(request: Request) -> dict[str, Any]:
        c = ctx(request)
        snap = c.engine.repo.snapshot
        return {
            "status": "ok",
            "methodology_version": c.engine.cfg.methodology_version,
            "offline_mode": c.settings.offline,
            "snapshot_entries": len(snap) if snap is not None else 0,
            "llm": {"available": c.provider is not None,
                    "provider": c.provider.name if c.provider else None,
                    "model": c.provider.model if c.provider else None,
                    "reason": c.provider_error},
        }  # fmt: skip

    @app.get("/api/hubs", tags=["hubs"], summary="List the illustrative hub catalog")
    def hubs(request: Request) -> dict[str, Any]:
        cat = ctx(request).engine.catalog
        return {
            "illustrative": True,
            "note": "Assumed example hubs chosen for geographic diversity; not company facilities.",
            "hubs": [{"hub_id": h.id, "name": h.display_name, "city": h.city, "state": h.state,
                      "region": h.region.value, "latitude": h.latitude, "longitude": h.longitude,
                      "hazard_county": h.hazard_county.model_dump(),
                      "noaa_station": h.noaa_station.id} for h in cat.hubs],
        }  # fmt: skip

    @app.get("/api/hubs/{hub_id}/scores", tags=["hubs"], response_model=HubProfile,
             responses=ERRORS, summary="Deterministic exposure profile of one hub (no LLM)")  # fmt: skip
    def hub_scores(request: Request,
                   hub_id: str = Path(..., pattern=r"^[a-z][a-z0-9_]{1,40}$")) -> HubProfile:  # fmt: skip
        c = ctx(request)
        try:
            c.engine.catalog.get(hub_id)
            with c.lock:
                return c.engine.get_hub_profile(hub_id)
        except UnsupportedHubError:
            raise HTTPException(404, {"error": "unknown_hub", "detail":
                                      f"'{hub_id}' is not a catalog hub id"}) from None  # fmt: skip
        except DataUnavailableError as exc:
            raise HTTPException(503, {"error": "data_unavailable", "detail": str(exc),
                                      "retryable": True}) from None  # fmt: skip

    def _freshness(c: AppState, hub_ids: list[str]) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {}
        for hid in hub_ids:
            for src in c.engine.get_hub_profile(hid).sources:
                out.setdefault(src.source_id.value, set()).add(src.freshness)
        return {k: sorted(v) for k, v in out.items()}

    @app.get("/api/overview", tags=["hubs"], responses=ERRORS,
             summary="Dashboard summary for all hubs (deterministic, no LLM)")  # fmt: skip
    def overview(request: Request) -> dict[str, Any]:
        c = ctx(request)
        try:
            with c.lock:
                eng = c.engine
                ranking = eng.rank_hubs()
                ranks = {e.hub_id: e.rank for e in ranking.ranked}
                hubs = []
                for h in eng.catalog.hubs:
                    p = eng.get_hub_profile(h)
                    el = p.ranking_eligibility
                    drivers = sorted(p.hazards.values(),
                                     key=lambda r: -(r.contribution_to_overall or 0))  # fmt: skip
                    hubs.append({
                        "hub_id": h.id, "name": h.display_name, "city": h.city, "state": h.state,
                        "region": h.region.value, "latitude": h.latitude, "longitude": h.longitude,
                        "overall": {"score": p.overall_score, "score_display": p.overall_score_display,
                                    "band": p.overall_band, "status": p.overall_status,
                                    "rank": ranks.get(h.id), "eligible": el["overall"].eligible,
                                    "exclusion_reason": el["overall"].reason},
                        "hazards": {hz.value: {"score": r.score, "score_display": r.score_display,
                                               "band": r.band, "status": r.status,
                                               "eligible": el[hz.value].eligible,
                                               "exclusion_reason": el[hz.value].reason}
                                    for hz, r in p.hazards.items()},
                        "primary_driver": drivers[0].hazard.value if drivers[0].score is not None
                        else None,
                    })  # fmt: skip
                statuses = [x["overall"]["status"] for x in hubs]
                top = ranking.ranked[0] if ranking.ranked else None
                snap = eng.repo.snapshot
                return {
                    "illustrative": True,
                    "methodology_version": eng.cfg.methodology_version,
                    "nri_version": eng.percentiles().nri_version,
                    "climate_period": eng.climatology.label,
                    "counts": {"hubs": len(hubs), "ranked": len(ranking.ranked),
                               "partial": statuses.count("partial"),
                               "unavailable": statuses.count("unavailable"),
                               "high": sum(1 for x in hubs if x["overall"]["band"] == "High")},
                    "highest": None if top is None else {
                        "hub_id": top.hub_id, "name": top.display_name,
                        "score_display": top.score_display, "band": top.band},
                    "data_freshness": _freshness(c, [h.id for h in eng.catalog.hubs]),
                    "snapshot_generated_at": (snap.manifest.generated_at.isoformat()
                                              if snap is not None and snap.manifest else None),
                    "hubs": hubs,
                }  # fmt: skip
        except DataUnavailableError as exc:
            raise HTTPException(503, {"error": "data_unavailable", "detail": str(exc),
                                      "retryable": True}) from None  # fmt: skip

    @app.get("/api/rankings", tags=["hubs"], response_model=RankingResult, responses=ERRORS,
             summary="Deterministic ranking (overall or one hazard, optional region)")  # fmt: skip
    def rankings(
        request: Request,
        hazard: Literal["winter", "hurricane", "flood", "severe_convective", "extreme_heat"]
        | None = Query(None),
        region: Literal["Midwest", "South", "West"] | None = Query(None),
    ) -> RankingResult:
        c = ctx(request)
        try:
            with c.lock:
                return c.engine.rank_hubs(hazard=hazard, region=region)
        except DataUnavailableError as exc:
            raise HTTPException(503, {"error": "data_unavailable", "detail": str(exc),
                                      "retryable": True}) from None  # fmt: skip

    @app.get("/api/methodology", tags=["system"],
             summary="Scoring configuration, data sources and versions (read-only)")  # fmt: skip
    def methodology(request: Request) -> dict[str, Any]:
        c = ctx(request)
        cfg = c.engine.cfg
        snap = c.engine.repo.snapshot
        from weather_risk.data.snapshot import LICENSES

        with c.lock:
            nri_version = c.engine.percentiles().nri_version
        return {
            "methodology_version": cfg.methodology_version,
            "nri_version": nri_version,
            "climate": {"source": cfg.climate.source.value, "period": cfg.climate.period,
                        "min_coverage": cfg.climate.min_coverage,
                        "exclude_quality_flagged": cfg.climate.exclude_quality_flagged},
            "thresholds": cfg.thresholds.model_dump(),
            "coverage_policy": cfg.coverage.model_dump(),
            "bands": [b.model_dump() for b in cfg.bands],
            "hazard_weights": {k.value: v for k, v in cfg.hazard_weights.items()},
            "hazards": {k.value: {"label": h.label, "indicators": [
                {"id": i.id, "kind": i.kind, "weight": i.weight,
                 "metric": i.metric.value if i.metric else None,
                 "nri_hazard": i.nri_hazard.name if i.nri_hazard else None,
                 "anchor": i.anchor.model_dump() if i.anchor else None, "unit": i.unit}
                for i in h.indicators]} for k, h in cfg.hazards.items()},
            "nri_normalization": cfg.nri_normalization.model_dump(),
            "sources": [{"source_id": k, "license": v} for k, v in LICENSES.items()],
            "snapshot": {"entries": len(snap) if snap is not None else 0,
                         "generated_at": snap.manifest.generated_at.isoformat()
                         if snap is not None and snap.manifest else None},
            "offline_mode": c.settings.offline,
        }  # fmt: skip

    @app.post("/api/chat", tags=["agent"], response_model=ChatResponse, responses=ERRORS,
              summary="Ask the grounded agent (requires Gemini)")  # fmt: skip
    def chat(request: Request, body: ChatRequest) -> ChatResponse:
        c = ctx(request)
        if c.agent is None:
            raise HTTPException(503, {"error": "llm_unavailable", "detail":
                                      "The AI Analyst is not available on this server. "
                                      "The dashboard and methodology still work.",
                                      "retryable": False})  # fmt: skip
        _enforce_limits(c, request, body.session_id)
        if not c.chat_slots.acquire():
            raise HTTPException(503, {"error": "busy", "detail": "The AI Analyst is busy with "
                                      "other questions. Please try again in a moment.",
                                      "retryable": True}, headers={"Retry-After": "10"})  # fmt: skip
        try:
            return c.agent.chat(body.message, body.session_id,
                                deadline_seconds=c.settings.chat_deadline_seconds)  # fmt: skip
        except SessionNotFoundError:
            raise HTTPException(404, {"error": "unknown_session", "detail":
                                      "session_id not found; omit it to start a new session"}) from None  # fmt: skip
        except LLMError as exc:
            # Provider details go to the server log only, never to the client.
            log.warning("chat_llm_error", extra={"kind": exc.kind, "detail": str(exc)[:300]})
            status, error, detail = _LLM_ERRORS.get(type(exc), _LLM_ERRORS[LLMError])
            raise HTTPException(status, {"error": error, "detail": detail,
                                         "retryable": exc.retryable or status == 429}) from None  # fmt: skip
        finally:
            c.chat_slots.release()

    @app.get("/api/sessions/{session_id}", tags=["agent"], responses=ERRORS,
             summary="Conversation history of a session")  # fmt: skip
    def session_history(request: Request,
                        session_id: str = Path(..., pattern=r"^[A-Za-z0-9_-]{8,64}$")) -> dict:  # fmt: skip
        c = ctx(request)
        if not c.sessions.exists(session_id):
            raise HTTPException(404, {"error": "unknown_session", "detail": "session not found"})
        turns = c.sessions.history(session_id, 50)
        return {"session_id": session_id,
                "turns": [{"turn": t["turn"], "created_at": t["created_at"],
                           "user_message": t["user_message"], "response": t["response"]}
                          for t in turns]}  # fmt: skip

    _mount_frontend(app, settings)
    return app


_LLM_ERRORS: dict[type, tuple[int, str, str]] = {
    LLMAuthError: (503, "llm_auth_error", "The AI provider rejected the server's credentials."),
    LLMQuotaError: (429, "llm_quota_exceeded", "The AI provider's usage quota is exhausted. "
                    "Please try again later; the dashboard still works."),
    LLMTimeoutError: (504, "llm_timeout", "The AI Analyst took too long to answer. "
                      "Please try again or ask a narrower question."),
    LLMUnavailableError: (503, "llm_unavailable", "The AI provider is temporarily unavailable. "
                          "Please try again shortly."),
    LLMError: (503, "llm_error", "The AI Analyst could not answer this question."),
}  # fmt: skip


def _authorized(request: Request, settings: Settings) -> bool:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return False
    try:
        user, _, pw = base64.b64decode(header[6:], validate=True).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    expected = settings.demo_password.get_secret_value() if settings.demo_password else ""
    ok_user = secrets.compare_digest(user.encode(), settings.demo_username.encode())
    ok_pw = secrets.compare_digest(pw.encode(), expected.encode())
    return ok_user and ok_pw


def _enforce_limits(c: AppState, request: Request, session_id: str | None) -> None:
    ip = client_ip(request, c.settings.trusted_proxy_hops)
    wait = c.ip_minute.hit(ip) or c.ip_hour.hit(ip)
    if wait is None and session_id:
        wait = c.session_hour.hit(session_id)
    if wait is not None:
        log.info("chat_rate_limited", extra={"retry_after_s": round(wait)})
        raise HTTPException(429, {"error": "rate_limited", "detail": "Too many questions in a "
                                  f"short time. Please wait about {round(wait)} s.",
                                  "retryable": True},
                            headers={"Retry-After": str(round(wait))})  # fmt: skip
    if not c.daily.hit():
        log.warning("chat_daily_limit_reached", extra={"limit": c.daily.limit})
        raise HTTPException(429, {"error": "daily_limit_reached", "detail": "The demo's daily "
                                  "AI question limit has been reached. The dashboard still "
                                  "works; the AI Analyst resets at 00:00 UTC.",
                                  "retryable": False})  # fmt: skip


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve the built React app from the same origin (production). /api routes take priority."""
    dist = settings.web_dist_dir.resolve()
    index = dist / "index.html"
    if not settings.serve_frontend or not index.is_file():
        return

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content={"error": "not_found",
                                "detail": "unknown API route", "retryable": False})  # fmt: skip
        target = (dist / path).resolve()
        if path and target.is_file() and target.is_relative_to(dist):
            cache = ("public, max-age=31536000, immutable" if path.startswith("assets/")
                     else "no-cache")  # fmt: skip
            return FileResponse(target, headers={"Cache-Control": cache})
        # SPA fallback: unknown paths get index.html, so refreshes and deep links keep working.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
