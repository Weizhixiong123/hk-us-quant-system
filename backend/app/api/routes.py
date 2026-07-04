from __future__ import annotations

import asyncio
import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect

from app.models.schemas import (
    BacktestRequest,
    BacktestResult,
    DashboardSnapshot,
    LiveSettingsSnapshot,
    LiveSettingsUpdate,
    Order,
    Position,
    RuntimeReloadResult,
    Signal,
    StrategyConfig,
    StrategyParamsUpdate,
    StrategyToggleRequest,
    SymbolNameLookup,
    Trade,
    TradeLog,
    WatchSymbol,
)
from app.services.state import AppState
from quant.data.symbol_names import lookup_symbol_name
from quant.live.settings import load_live_settings, public_live_settings, save_live_settings

router = APIRouter()


def get_state(request: Request) -> AppState:
    return request.app.state.quant_state


def _market_time_basis(market: str) -> str:
    return "美东时间 America/New_York" if market == "US" else "香港时间 Asia/Hong_Kong"


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    manager = getattr(request.app.state, "runtime_manager", None)
    runtime = manager.runtime if manager else None
    return {
        "status": "ok",
        "service": request.app.title,
        "mode": "live-ready",
        "runtime_running": str(runtime is not None).lower(),
        "runtime_enabled": str(bool(runtime and runtime.config.enabled)).lower(),
        "runtime_dry_run": str(bool(runtime and runtime.config.dry_run)).lower(),
        "runtime_broker": runtime.config.broker if runtime else "futu",
        "runtime_error": (manager.last_error or "") if manager else "",
    }


@router.get("/dashboard", response_model=DashboardSnapshot)
def dashboard(request: Request) -> DashboardSnapshot:
    return get_state(request).dashboard()


@router.get("/live-settings", response_model=LiveSettingsSnapshot)
def live_settings() -> dict:
    return public_live_settings(load_live_settings())


@router.get("/symbols/name", response_model=SymbolNameLookup)
async def symbol_name(
    symbol: str = Query(min_length=1, max_length=24),
    market: str = Query(pattern="^(US|HK)$"),
) -> dict[str, str | None]:
    try:
        normalized, name = await asyncio.to_thread(lookup_symbol_name, symbol, market)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="股票名称查询服务暂不可用") from exc
    return {"symbol": normalized, "market": market, "name": name}


@router.put("/live-settings", response_model=LiveSettingsSnapshot)
def update_live_settings(payload: LiveSettingsUpdate) -> dict:
    update = payload.model_dump(exclude_unset=True, exclude_none=True)
    try:
        settings = save_live_settings(update)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return public_live_settings(settings)


@router.post("/runtime/reload", response_model=RuntimeReloadResult)
async def reload_runtime(request: Request) -> dict:
    manager = getattr(request.app.state, "runtime_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="runtime manager 未初始化")
    result = await manager.reload()
    runtime = manager.runtime
    return {
        "ok": result["ok"],
        "error": result["error"],
        "runtime_running": runtime is not None,
        "runtime_enabled": bool(runtime and runtime.config.enabled),
        "runtime_dry_run": bool(runtime and runtime.config.dry_run),
        "runtime_broker": runtime.config.broker if runtime else "futu",
    }


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
        strategy = get_state(request).update_strategy_params(strategy_id, payload.params)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if strategy_id == "intraday_macd":
        manager = getattr(request.app.state, "runtime_manager", None)
        runtime = manager.runtime if manager else None
        if runtime is not None:
            runtime.scheduler.open_after_minutes = runtime.params.intraday.open_after_minutes
            runtime.scheduler.close_before_minutes = runtime.params.intraday.close_before_minutes
    return strategy


@router.get("/positions", response_model=list[Position])
def positions(request: Request) -> list[Position]:
    return get_state(request).current_positions()


@router.get("/watchlist", response_model=list[WatchSymbol])
def watchlist(request: Request) -> list[WatchSymbol]:
    return get_state(request).watchlist


@router.get("/signals", response_model=list[Signal])
def signals(request: Request) -> list[Signal]:
    return get_state(request).signals


@router.get("/orders", response_model=list[Order])
def orders(request: Request) -> list[Order]:
    return get_state(request).current_orders()


@router.get("/trades", response_model=list[Trade])
def trades(request: Request) -> list[Trade]:
    return get_state(request).current_trades()


@router.get("/trades/history", response_model=list[Trade])
def trade_history(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[Trade]:
    return get_state(request).trade_history(limit)


@router.get("/logs", response_model=list[TradeLog])
def logs(request: Request) -> list[TradeLog]:
    return get_state(request).current_logs()


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


@router.get("/backtests/{backtest_id}/trades.csv")
def download_backtest_trades(backtest_id: str) -> Response:
    from quant.backtest.store import get_backtest_result

    result = get_backtest_result(backtest_id)
    if result is None:
        raise HTTPException(status_code=404, detail="backtest not found")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "股票代码",
        "市场",
        "方向",
        "开仓时间(市场当地)",
        "平仓时间(市场当地)",
        "时间口径",
        "开仓价",
        "平仓价",
        "仓位金额",
        "数量",
        "盈利亏损",
        "收益率%",
        "开仓原因",
        "平仓原因",
        "最高浮盈%",
        "最大浮亏%",
        "股票来源",
        "仓位来源",
    ])
    for trade in result.trade_rows:
        writer.writerow([
            trade.symbol,
            trade.market,
            "多头" if trade.side == "long" else "空头",
            trade.entry_time,
            trade.exit_time,
            _market_time_basis(trade.market),
            trade.entry_price,
            trade.exit_price,
            trade.position_size,
            trade.quantity,
            trade.pnl,
            trade.pnl_pct,
            trade.entry_reason,
            trade.exit_reason,
            trade.max_favorable_pct,
            trade.max_adverse_pct,
            trade.symbols_source,
            trade.position_source,
        ])

    filename = f"backtest_{result.strategy_id}_{result.market}_{result.start_date}_{result.end_date}_{result.id}.csv"
    return Response(
        content="﻿" + output.getvalue(),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

