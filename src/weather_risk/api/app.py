"""FastAPI application.

    uv run uvicorn weather_risk.api.app:app --reload        (or: make api)

Deterministic endpoints (/api/health, /api/hubs, /api/hubs/{id}/scores) never need the LLM.
/api/chat needs a configured Gemini key; otherwise it returns 503 `llm_unavailable` — it never
substitutes a fake model.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from weather_risk.analytics.models import HubProfile
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
        self.lock = threading.Lock()  # single-process prototype: serialize engine/agent access
        self.agent = Agent(engine, provider, sessions) if provider else None


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
                                      max_attempts=settings.llm_max_attempts)  # fmt: skip
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
        return err(exc.status_code, d["error"], d["detail"], d.get("retryable", False))

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

    @app.post("/api/chat", tags=["agent"], response_model=ChatResponse, responses=ERRORS,
              summary="Ask the grounded agent (requires Gemini)")  # fmt: skip
    def chat(request: Request, body: ChatRequest) -> ChatResponse:
        c = ctx(request)
        if c.agent is None:
            raise HTTPException(503, {"error": "llm_unavailable", "detail":
                                      f"The AI agent is not available: {c.provider_error}. "
                                      "Deterministic endpoints still work.", "retryable": False})  # fmt: skip
        try:
            with c.lock:
                return c.agent.chat(body.message, body.session_id)
        except SessionNotFoundError:
            raise HTTPException(404, {"error": "unknown_session", "detail":
                                      "session_id not found; omit it to start a new session"}) from None  # fmt: skip
        except LLMAuthError as exc:
            raise HTTPException(503, {"error": "llm_auth_error", "detail": str(exc)}) from None
        except LLMQuotaError as exc:
            raise HTTPException(429, {"error": "llm_quota_exceeded", "detail": str(exc),
                                      "retryable": True}) from None  # fmt: skip
        except LLMTimeoutError as exc:
            raise HTTPException(504, {"error": "llm_timeout", "detail": str(exc),
                                      "retryable": True}) from None  # fmt: skip
        except LLMUnavailableError as exc:
            raise HTTPException(503, {"error": "llm_unavailable", "detail": str(exc),
                                      "retryable": True}) from None  # fmt: skip
        except LLMError as exc:
            raise HTTPException(503, {"error": "llm_error", "detail": str(exc)}) from None

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

    return app


app = create_app()
