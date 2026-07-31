from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings
from app.services.state import AppState
from quant.live.params import LiveParams
from quant.live.runtime_manager import RuntimeManager
from quant.live.state import LiveGatewayState

logger = logging.getLogger(__name__)


def _safe_validation_errors(exc: RequestValidationError) -> list[dict]:
    """Return field errors without echoing request values into logs or responses."""
    return [
        {key: value for key, value in error.items() if key != "input"}
        for error in exc.errors()
    ]


def create_app() -> FastAPI:
    live_state = LiveGatewayState()
    live_params = LiveParams()
    runtime_manager = RuntimeManager(live_state, live_params)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.runtime_manager.start()
        try:
            yield
        finally:
            await app.state.runtime_manager.stop()

    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description="FastAPI service for the HK/US dual-strategy quant system.",
        lifespan=lifespan,
    )
    app.state.live_state = live_state
    app.state.runtime_manager = runtime_manager
    app.state.quant_state = AppState(
        app.state.live_state,
        live_params,
        persist_strategy_params=True,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    @app.exception_handler(RequestValidationError)
    async def _log_unprocessable(request: Request, exc: RequestValidationError):
        errors = _safe_validation_errors(exc)
        logger.warning(
            "422 Unprocessable Content %s %s: %s",
            request.method,
            request.url.path,
            errors,
        )
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(Exception)
    async def _internal_server_error(request: Request, exc: Exception):
        logger.error(
            "Unhandled exception for %s %s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})

    frontend_dist = _frontend_dist_dir()
    if frontend_dist is not None:
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    else:
        @app.get("/")
        def root() -> dict[str, str]:
            return {
                "name": settings.app_name,
                "docs": "/docs",
                "dashboard": "/api/dashboard",
            }

    return app


def _frontend_dist_dir() -> Path | None:
    env_dir = os.getenv("FRONTEND_DIST_DIR")
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = Path(__file__).resolve().parents[1]
    candidates = [
        Path(env_dir) if env_dir else None,
        repo_root / "frontend" / "dist",
        backend_root / "static",
    ]

    for candidate in candidates:
        if candidate and (candidate / "index.html").exists():
            return candidate
    return None


app = create_app()
