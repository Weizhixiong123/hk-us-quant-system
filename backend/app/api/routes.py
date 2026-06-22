from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from app.models.schemas import (
    BacktestRequest,
    BacktestResult,
    DashboardSnapshot,
    Order,
    Position,
    Signal,
    StrategyConfig,
    StrategyParamsUpdate,
    StrategyToggleRequest,
    TradeLog,
    WatchSymbol,
)
from app.services.state import AppState

router = APIRouter()


def get_state(request: Request) -> AppState:
    return request.app.state.quant_state


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    return {
        "status": "ok",
        "service": request.app.title,
        "mode": "simulated",
    }


@router.get("/dashboard", response_model=DashboardSnapshot)
def dashboard(request: Request) -> DashboardSnapshot:
    return get_state(request).dashboard()


@router.get("/strategies", response_model=list[StrategyConfig])
def strategies(request: Request) -> list[StrategyConfig]:
    return get_state(request).strategies


@router.patch("/strategies/{strategy_id}/toggle", response_model=StrategyConfig)
def toggle_strategy(
    strategy_id: str,
    payload: StrategyToggleRequest,
    request: Request,
) -> StrategyConfig:
    try:
        return get_state(request).set_strategy_enabled(strategy_id, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/strategies/{strategy_id}/params", response_model=StrategyConfig)
def update_strategy_params(
    strategy_id: str,
    payload: StrategyParamsUpdate,
    request: Request,
) -> StrategyConfig:
    try:
        return get_state(request).update_strategy_params(strategy_id, payload.params)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/positions", response_model=list[Position])
def positions(request: Request) -> list[Position]:
    return get_state(request).positions


@router.get("/watchlist", response_model=list[WatchSymbol])
def watchlist(request: Request) -> list[WatchSymbol]:
    return get_state(request).watchlist


@router.get("/signals", response_model=list[Signal])
def signals(request: Request) -> list[Signal]:
    return get_state(request).signals


@router.get("/orders", response_model=list[Order])
def orders(request: Request) -> list[Order]:
    return get_state(request).orders


@router.get("/logs", response_model=list[TradeLog])
def logs(request: Request) -> list[TradeLog]:
    return get_state(request).logs


@router.get("/backtests", response_model=list[BacktestResult])
def backtests(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[BacktestResult]:
    return get_state(request).list_backtests(limit)


@router.post("/backtests", response_model=BacktestResult)
def run_backtest(payload: BacktestRequest, request: Request) -> BacktestResult:
    try:
        return get_state(request).run_backtest(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.websocket("/ws/stream")
async def stream_dashboard(websocket: WebSocket) -> None:
    await websocket.accept()
    state: AppState = websocket.app.state.quant_state
    try:
        while True:
            snapshot = state.tick()
            await websocket.send_json(
                {
                    "event": "snapshot",
                    "data": snapshot.model_dump(mode="json"),
                }
            )
            await asyncio.sleep(2.5)
    except WebSocketDisconnect:
        return

