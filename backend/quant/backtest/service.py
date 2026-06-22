from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import uuid4

import pandas as pd

from app.models.schemas import BacktestRequest, BacktestResult, EquityPoint
from quant.data.loaders import Fetcher, load_daily
from quant.data.universe import get_universe
from quant.indicators.macd import has_bearish_cross, has_bullish_cross, macd
from quant.indicators.trend import max_drawdown_pct, sma


@dataclass(frozen=True)
class SymbolBacktest:
    symbol: str
    returns: pd.Series
    trade_returns: tuple[float, ...]


def run_backtest(
    request: BacktestRequest,
    fetcher: Fetcher | None = None,
) -> BacktestResult:
    symbols = request.symbols or [item.symbol for item in get_universe(request.market)]
    runs: list[SymbolBacktest] = []
    notes: list[str] = []

    for symbol in symbols:
        try:
            daily = load_daily(symbol, request.market, request.start_date, request.end_date, fetcher)
        except Exception as exc:  # 数据源失败不应让整次回测中断
            notes.append(f"{symbol} 数据加载失败：{exc}")
            continue

        if len(daily) < 30:
            notes.append(f"{symbol} 数据不足，已跳过。")
            continue

        if request.strategy_id == "intraday_macd":
            runs.append(_run_macd_daily_proxy(symbol, daily))
        elif request.strategy_id == "trend_portfolio":
            runs.append(_run_trend_daily_proxy(symbol, daily))
        else:
            raise ValueError(f"unknown strategy: {request.strategy_id}")

    if not runs:
        return _empty_result(request, notes or ["没有可用于回测的数据。"])

    portfolio_returns = _combine_returns(runs)
    equity = request.initial_capital * (1 + portfolio_returns).cumprod()
    trade_returns = [value for run in runs for value in run.trade_returns]

    notes.extend(_strategy_notes(request.strategy_id, len(runs), symbols))
    return BacktestResult(
        id=f"BT-{uuid4().hex[:8].upper()}",
        strategy_id=request.strategy_id,
        market=request.market,
        start_date=request.start_date,
        end_date=request.end_date,
        total_return_pct=_total_return_pct(equity, request.initial_capital),
        max_drawdown_pct=max_drawdown_pct(equity.tolist()),
        sharpe=_sharpe(portfolio_returns),
        win_rate_pct=_win_rate_pct(trade_returns),
        trades=len(trade_returns),
        equity_curve=_build_equity_curve(equity),
        notes=notes,
    )


def _run_macd_daily_proxy(symbol: str, daily: pd.DataFrame) -> SymbolBacktest:
    closes = daily["close"].astype(float).tolist()
    points = macd(closes)
    if not points:
        return SymbolBacktest(symbol=symbol, returns=_zero_returns(daily), trade_returns=())

    holding = False
    entry_price: float | None = None
    daily_returns: list[float] = [0.0]
    trade_returns: list[float] = []

    for index in range(1, len(daily)):
        recent_points = points[: index + 1]
        previous_close = closes[index - 1]
        current_close = closes[index]

        daily_returns.append(
            (current_close / previous_close - 1) if holding and previous_close else 0.0
        )

        if holding and has_bearish_cross(recent_points):
            if entry_price:
                trade_returns.append(current_close / entry_price - 1)
            holding = False
            entry_price = None
        elif not holding and has_bullish_cross(recent_points):
            holding = True
            entry_price = current_close

    return SymbolBacktest(
        symbol=symbol,
        returns=pd.Series(daily_returns, index=daily.index, dtype=float),
        trade_returns=tuple(trade_returns),
    )


def _run_trend_daily_proxy(symbol: str, daily: pd.DataFrame) -> SymbolBacktest:
    closes = daily["close"].astype(float).tolist()
    holding = False
    entry_price: float | None = None
    daily_returns: list[float] = [0.0]
    trade_returns: list[float] = []

    for index in range(1, len(daily)):
        previous_close = closes[index - 1]
        current_close = closes[index]
        ma20 = sma(closes[: index + 1], 20)
        ma60 = sma(closes[: index + 1], 60)
        trend_ok = ma20 is not None and ma60 is not None and current_close > ma20 > ma60

        daily_returns.append(
            (current_close / previous_close - 1) if holding and previous_close else 0.0
        )

        if holding and not trend_ok:
            if entry_price:
                trade_returns.append(current_close / entry_price - 1)
            holding = False
            entry_price = None
        elif not holding and trend_ok:
            holding = True
            entry_price = current_close

    if holding and entry_price:
        trade_returns.append(closes[-1] / entry_price - 1)

    return SymbolBacktest(
        symbol=symbol,
        returns=pd.Series(daily_returns, index=daily.index, dtype=float),
        trade_returns=tuple(trade_returns),
    )


def _combine_returns(runs: list[SymbolBacktest]) -> pd.Series:
    frame = pd.concat({run.symbol: run.returns for run in runs}, axis=1).sort_index()
    return frame.mean(axis=1).fillna(0.0)


def _zero_returns(daily: pd.DataFrame) -> pd.Series:
    return pd.Series([0.0] * len(daily), index=daily.index, dtype=float)


def _build_equity_curve(equity: pd.Series) -> list[EquityPoint]:
    if equity.empty:
        return []

    running_max = equity.cummax()
    points: list[EquityPoint] = []
    for time_index, equity_value, peak_value in zip(
        equity.index,
        equity.to_numpy(),
        running_max.to_numpy(),
    ):
        value = float(equity_value)
        peak = float(peak_value)
        drawdown = 0.0 if peak <= 0 else (peak - value) / peak * 100
        points.append(
            EquityPoint(
                time=_format_time(time_index),
                equity=round(value, 2),
                drawdown_pct=round(drawdown, 2),
            )
        )
    return points


def _format_time(value: object) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _total_return_pct(equity: pd.Series, initial_capital: float) -> float:
    if equity.empty or initial_capital <= 0:
        return 0.0
    return round((float(equity.iloc[-1]) / initial_capital - 1) * 100, 2)


def _sharpe(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    std = float(returns.std(ddof=0))
    if std == 0:
        return 0.0
    return round(float(returns.mean()) / std * math.sqrt(252), 2)


def _win_rate_pct(trade_returns: list[float]) -> float:
    if not trade_returns:
        return 0.0
    wins = sum(1 for value in trade_returns if value > 0)
    return round(wins / len(trade_returns) * 100, 2)


def _empty_result(request: BacktestRequest, notes: list[str]) -> BacktestResult:
    return BacktestResult(
        id=f"BT-{uuid4().hex[:8].upper()}",
        strategy_id=request.strategy_id,
        market=request.market,
        start_date=request.start_date,
        end_date=request.end_date,
        total_return_pct=0.0,
        max_drawdown_pct=0.0,
        sharpe=0.0,
        win_rate_pct=0.0,
        trades=0,
        equity_curve=[],
        notes=notes,
    )


def _strategy_notes(strategy_id: str, used_symbols: int, requested_symbols: list[str]) -> list[str]:
    if strategy_id == "intraday_macd":
        mode = "日线 MACD 代理回测；15min/5min vnpy 分钟级回测仍待接入。"
    else:
        mode = "日线趋势代理回测；月/周线组合调仓 vnpy 回测仍待接入。"
    return [
        mode,
        f"本次使用 {used_symbols}/{len(requested_symbols)} 个标的生成组合收益。",
    ]

