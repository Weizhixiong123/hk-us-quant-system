from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.services.state import AppState
from quant.live.state import LiveGatewayState


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description="FastAPI service for the HK/US dual-strategy quant system.",
    )
    app.state.live_state = LiveGatewayState()
    app.state.quant_state = AppState(app.state.live_state)
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
