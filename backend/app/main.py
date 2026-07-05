from __future__ import annotations

import os
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings
from app.services.state import AppState
from quant.live.params import LiveParams
from quant.live.runtime_manager import RuntimeManager
from quant.live.state import LiveGatewayState


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

    # 把 422 校验失败的具体字段级错误打到日志,便于定位是哪条 manual_symbol / 哪个字段不合规。
    # 同时把 detail 原样返回给前端,前端可直接展示。
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    import logging as _logging

    _log = _logging.getLogger("app.api.routes")

    @app.exception_handler(RequestValidationError)
    async def _log_unprocessable(request: Request, exc: RequestValidationError):
        _log.warning(
            "422 Unprocessable Content %s %s: %s",
            request.method,
            request.url.path,
            exc.errors(),
        )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    # 临时诊断:把未处理异常的完整 traceback 直接返回到响应,方便在浏览器排查 500。
    # 定位修复后应移除这段。 RequestValidationError 由上面的专用 handler 处理。
    @app.exception_handler(Exception)
    async def _debug_traceback_handler(request: Request, exc: Exception):
        if isinstance(exc, RequestValidationError):
            raise exc
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return PlainTextResponse(detail, status_code=500)

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
