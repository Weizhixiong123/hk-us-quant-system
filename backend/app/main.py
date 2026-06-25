from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    app.state.quant_state = AppState(app.state.live_state, live_params)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "docs": "/docs",
            "dashboard": "/api/dashboard",
        }

    return app


app = create_app()
