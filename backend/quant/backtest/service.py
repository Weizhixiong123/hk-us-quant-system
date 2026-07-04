from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

import pandas as pd

from app.models.schemas import BacktestRequest, BacktestResult, BacktestTradeRow, EquityPoint
from quant.data.loaders import Fetcher, MinuteFetcher, load_daily, load_minutes
from quant.data.universe import get_universe
from quant.indicators.trend import max_drawdown_pct, sma
from quant.live.clock import SESSIONS, is_bar_close, is_market_open
from quant.live.intraday import (
    IntradayPosition,
    build_premarket_watchlist,
    evaluate_intraday_entry_signal,
    evaluate_intraday_exit_signal,
    three_period_macd_momentum,
)
from quant.live.market_data import Bar, BarAggregator
from quant.screening.intraday_screener import IntradayCandidate


def _log_backtest(message: str) -> None:
    print(f"[BACKTEST] {message}", flush=True)


@dataclass(frozen=True)
class SymbolBacktest:
    symbol: str
    returns: pd.Series
    trade_returns: tuple[float, ...]
    trade_rows: tuple[BacktestTradeRow, ...]


def run_backtest(
    request: BacktestRequest,
    fetcher: Fetcher | None = None,
    minute_fetcher: MinuteFetcher | None = None,
) -> BacktestResult:
    auto_symbols = request.symbols_mode == "auto"
    symbols_source = request.symbols_source
    notes: list[str] = []
    if auto_symbols:
        symbols = _auto_select_symbols(request, fetcher)
        symbols_source = "自动选股策略"
        if symbols:
            notes.append(f"已按{symbols_source}选出 {len(symbols)} 只标的。")
        else:
            symbols = [item.symbol for item in get_universe(request.market)]
            symbols_source = "fallback universe"
            notes.append("自动选股策略未选出标的，已使用静态 fallback universe。")
    else:
        symbols = request.symbols
        if not symbols:
            notes.append("自选候选池为空，未执行自动选股。")
    _log_backtest(
        "开始回测 "
        f"strategy={request.strategy_id} market={request.market} "
        f"range={request.start_date}~{request.end_date} symbols={len(symbols)} "
        f"initial_capital={request.initial_capital}"
    )
    runs: list[SymbolBacktest] = []
    allocation, position_source = _position_size(request, len(symbols))
    notes.append(f"股票来源：{symbols_source}。")
    notes.append(f"仓位来源：{position_source}。")

    for symbol in symbols:
        if request.strategy_id == "intraday_macd":
            try:
                _log_backtest(
                    f"加载1分钟线 symbol={symbol} market={request.market} "
                    f"range={request.start_date}~{request.end_date} source={'custom' if minute_fetcher else 'default'}"
                )
                minutes = load_minutes(symbol, request.market, request.start_date, request.end_date, "1m", minute_fetcher)
                _log_backtest(f"1分钟线加载完成 symbol={symbol} rows={len(minutes)}")
            except Exception as exc:
                _log_backtest(f"1分钟线加载失败 symbol={symbol} error={exc}")
                notes.append(f"{symbol} 1分钟线加载失败，已跳过：{exc}")
                continue
            slow_ema = _int_param(request.params_snapshot, "slow_ema", 26)
            minimum_minutes = (slow_ema + 1) * 15
            if minutes.empty or len(minutes) < minimum_minutes:
                _log_backtest(f"跳过标的 symbol={symbol} reason=1分钟线不足 required={minimum_minutes} actual={len(minutes)}")
                notes.append(
                    f"{symbol} 1分钟线不足（需要至少 {minimum_minutes} 根，实际 {len(minutes)} 根），"
                    "已跳过；日内策略不使用日线代理。"
                )
                continue
            symbol_run = _run_intraday_macd_minutes(
                symbol,
                minutes,
                request,
                allocation,
                position_source,
                symbols_source,
            )
            _log_backtest(f"标的回测完成 symbol={symbol} trades={len(symbol_run.trade_rows)} bars={len(minutes)}")
            runs.append(symbol_run)
            continue

        try:
            daily = load_daily(symbol, request.market, request.start_date, request.end_date, fetcher)
        except Exception as exc:  # 数据源失败不应让整次回测中断
            notes.append(f"{symbol} 数据加载失败：{exc}")
            continue

        if len(daily) < 30:
            notes.append(f"{symbol} 数据不足，已跳过。")
            continue

        if request.strategy_id == "trend_portfolio":
            runs.append(_run_trend_daily_proxy(symbol, daily, request.market, allocation, position_source, symbols_source))
        else:
            raise ValueError(f"unknown strategy: {request.strategy_id}")

    if not runs:
        result = _empty_result(request, notes or ["没有可用于回测的数据。"])
        _log_backtest(f"回测结束：没有可用标的生成结果 id={result.id} trades=0")
        return result

    portfolio_returns = _combine_returns(runs)
    equity = request.initial_capital * (1 + portfolio_returns).cumprod()
    trade_returns = [value for run in runs for value in run.trade_returns]
    trade_rows = [row for run in runs for row in run.trade_rows]

    notes.extend(_strategy_notes(request.strategy_id, len(runs), symbols))
    result = BacktestResult(
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
        trade_rows=trade_rows,
        notes=notes,
    )
    _log_backtest(
        "回测完成 "
        f"id={result.id} used_symbols={len(runs)}/{len(symbols)} trades={result.trades} "
        f"total_return_pct={result.total_return_pct} max_drawdown_pct={result.max_drawdown_pct}"
    )
    return result


def _auto_select_symbols(request: BacktestRequest, fetcher: Fetcher | None) -> list[str]:
    if request.strategy_id == "intraday_macd":
        return _auto_select_intraday_symbols(request, fetcher)
    return [item.symbol for item in get_universe(request.market)]


def _auto_select_intraday_symbols(request: BacktestRequest, fetcher: Fetcher | None) -> list[str]:
    candidates: list[IntradayCandidate] = []
    for item in get_universe(request.market):
        try:
            daily = load_daily(item.symbol, request.market, request.start_date, request.end_date, fetcher)
        except Exception as exc:
            _log_backtest(f"自动选股日线加载失败 symbol={item.symbol} error={exc}")
            continue
        if len(daily) < 21:
            continue
        prev = daily.iloc[-2]
        recent = daily.tail(20)
        prev_close = float(prev["close"])
        amplitude = (float(prev["high"]) - float(prev["low"])) / prev_close * 100 if prev_close > 0 else 0.0
        avg_turnover = float((recent["close"] * recent["volume"]).mean())
        price = float(daily.iloc[-1]["close"])
        candidates.append(
            IntradayCandidate(
                symbol=item.symbol,
                market=item.market,
                avg_turnover=avg_turnover,
                prev_amplitude_pct=round(amplitude, 4),
                price=price,
                halted=False,
                ex_dividend_soon=False,
                major_news=False,
                market_cap=0.0,
            )
        )
    symbols = build_premarket_watchlist(
        candidates,
        min_turnover=float(request.params_snapshot.get("min_turnover", 5_000_000.0)),
        min_amplitude_pct=float(request.params_snapshot.get("min_amplitude_pct", 2.0)),
        max_amplitude_pct=float(request.params_snapshot.get("max_amplitude_pct", 8.0)),
        min_price=float(request.params_snapshot.get("min_price", 2.0)),
        min_turnover_rate=float(request.params_snapshot.get("min_turnover_rate", 0.0)),
    )
    _log_backtest(f"自动选股完成 strategy={request.strategy_id} market={request.market} candidates={len(candidates)} selected={len(symbols)}")
    return symbols


def _run_intraday_macd_minutes(
    symbol: str,
    minutes: pd.DataFrame,
    request: BacktestRequest,
    allocation: float,
    position_source: str,
    symbols_source: str,
) -> SymbolBacktest:
    params = request.params_snapshot
    fast_ema = _int_param(params, "fast_ema", 12)
    slow_ema = _int_param(params, "slow_ema", 26)
    signal_ema = _int_param(params, "signal_ema", 9)
    open_after_minutes = _int_param(params, "open_after_minutes", 30)
    close_before_minutes = _int_param(params, "close_before_minutes", 90)

    bars = minutes.sort_index()
    aggregator = BarAggregator()
    returns: list[float] = []
    trade_returns: list[float] = []
    trade_rows: list[BacktestTradeRow] = []
    holding = False
    side = "long"
    entry_price = 0.0
    entry_time = ""
    entry_reason = ""
    quantity = 0.0
    highest_price = 0.0
    lowest_price = 0.0
    max_favorable_pct = 0.0
    max_adverse_pct = 0.0

    for bar_time, row in bars.iterrows():
        at = _as_datetime(bar_time)
        open_price = float(row["open"])
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        returns.append(0.0)
        exit_price: float | None = None
        exit_reason = ""

        if holding:
            highest_price = max(highest_price, high)
            lowest_price = min(lowest_price, low)
            max_favorable_pct, max_adverse_pct = _intraday_excursions(
                side,
                entry_price,
                highest_price,
                lowest_price,
            )
            if _is_intraday_force_close_time(at, request.market):
                exit_price = close
                exit_reason = "尾盘强制平仓"
            elif is_market_open(at, request.market) and is_bar_close(at, 3, request.market):
                closes_15m, closes_5m, closes_3m = _three_period_closes(aggregator, symbol)
                momentum = three_period_macd_momentum(
                    closes_15m,
                    closes_5m,
                    closes_3m,
                    fast_ema=fast_ema,
                    slow_ema=slow_ema,
                    signal_ema=signal_ema,
                )
                signal = evaluate_intraday_exit_signal(
                    IntradayPosition(
                        symbol=symbol,
                        side=side,  # type: ignore[arg-type]
                        quantity=max(1, int(quantity)),
                        avg_price=entry_price,
                    ),
                    momentum,
                )
                if signal.action == "exit_all":
                    exit_price = open_price
                    exit_reason = signal.reasons[0]

            if exit_price is not None:
                trade_return = _intraday_trade_return(side, entry_price, exit_price)
                returns[-1] = trade_return
                trade_returns.append(trade_return)
                trade_rows.append(
                    _build_trade_row(
                        symbol=symbol,
                        market=request.market,
                        side=side,
                        entry_time=entry_time,
                        exit_time=_format_time(bar_time),
                        entry_price=entry_price,
                        exit_price=exit_price,
                        position_size=allocation,
                        quantity=quantity,
                        position_source=position_source,
                        symbols_source=symbols_source,
                        entry_reason=entry_reason,
                        exit_reason=exit_reason,
                        max_favorable_pct=max_favorable_pct,
                        max_adverse_pct=max_adverse_pct,
                    )
                )
                holding = False
                side = "long"
                entry_price = 0.0
                entry_time = ""
                entry_reason = ""
                quantity = 0.0
                highest_price = 0.0
                lowest_price = 0.0

        elif is_market_open(at, request.market) and is_bar_close(at, 3, request.market):
            closes_15m, closes_5m, closes_3m = _three_period_closes(aggregator, symbol)
            if min(len(closes_15m), len(closes_5m), len(closes_3m)) >= slow_ema + 1:
                signal = evaluate_intraday_entry_signal(
                    symbol=symbol,
                    market=request.market,
                    at=at,
                    closes_15m=closes_15m,
                    closes_5m=closes_5m,
                    closes_3m=closes_3m,
                    fast_ema=fast_ema,
                    slow_ema=slow_ema,
                    signal_ema=signal_ema,
                    open_after_minutes=open_after_minutes,
                    close_before_minutes=close_before_minutes,
                )
                if signal.action in {"enter_long", "enter_short"} and open_price > 0:
                    side = "long" if signal.action == "enter_long" else "short"
                    entry_price = open_price
                    entry_time = _format_time(bar_time)
                    entry_reason = (
                        f"15/5/3分钟 MACD 柱同步{'抬高开多' if side == 'long' else '下降开空'}："
                        f"fast={fast_ema}, slow={slow_ema}, signal={signal_ema}"
                    )
                    quantity = _quantity_for(allocation, entry_price)
                    highest_price = max(entry_price, high)
                    lowest_price = min(entry_price, low)
                    max_favorable_pct, max_adverse_pct = _intraday_excursions(
                        side,
                        entry_price,
                        highest_price,
                        lowest_price,
                    )
                    holding = True

        aggregator.seed_minute_bars(
            symbol,
            [
                Bar(
                    symbol=symbol,
                    start=at,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=float(row["volume"]),
                )
            ],
        )

    if holding:
        row = bars.iloc[-1]
        exit_price = float(row["close"])
        trade_return = _intraday_trade_return(side, entry_price, exit_price)
        returns[-1] = trade_return
        trade_returns.append(trade_return)
        trade_rows.append(
            _build_trade_row(
                symbol=symbol,
                market=request.market,
                side=side,
                entry_time=entry_time,
                exit_time=_format_time(bars.index[-1]),
                entry_price=entry_price,
                exit_price=exit_price,
                position_size=allocation,
                quantity=quantity,
                position_source=position_source,
                symbols_source=symbols_source,
                entry_reason=entry_reason,
                exit_reason="回测结束强制平仓",
                max_favorable_pct=max_favorable_pct,
                max_adverse_pct=max_adverse_pct,
            )
        )

    return SymbolBacktest(
        symbol=symbol,
        returns=pd.Series(returns, index=bars.index, dtype=float),
        trade_returns=tuple(trade_returns),
        trade_rows=tuple(trade_rows),
    )


def _as_datetime(value: object) -> datetime:
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()  # type: ignore[no-any-return, attr-defined]
    if isinstance(value, datetime):
        return value
    return pd.Timestamp(value).to_pydatetime()


def _three_period_closes(
    aggregator: BarAggregator,
    symbol: str,
) -> tuple[list[float], list[float], list[float]]:
    closes_15m = [bar.close for bar in aggregator.interval_bars(symbol, 15, limit=80)]
    closes_5m = [bar.close for bar in aggregator.interval_bars(symbol, 5, limit=80)]
    closes_3m = [bar.close for bar in aggregator.interval_bars(symbol, 3, limit=80)]
    return closes_15m, closes_5m, closes_3m


def _intraday_excursions(
    side: str,
    entry_price: float,
    highest_price: float,
    lowest_price: float,
) -> tuple[float, float]:
    if entry_price <= 0:
        return 0.0, 0.0
    if side == "short":
        return (
            (entry_price - lowest_price) / entry_price * 100,
            (entry_price - highest_price) / entry_price * 100,
        )
    return (
        (highest_price - entry_price) / entry_price * 100,
        (lowest_price - entry_price) / entry_price * 100,
    )


def _intraday_trade_return(side: str, entry_price: float, exit_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    if side == "short":
        return (entry_price - exit_price) / entry_price
    return (exit_price - entry_price) / entry_price

def _run_trend_daily_proxy(
    symbol: str,
    daily: pd.DataFrame,
    market: str,
    allocation: float,
    position_source: str,
    symbols_source: str,
) -> SymbolBacktest:
    closes = daily["close"].astype(float).tolist()
    holding = False
    entry_price: float | None = None
    entry_time = ""
    quantity = 0.0
    daily_returns: list[float] = [0.0]
    trade_returns: list[float] = []
    trade_rows: list[BacktestTradeRow] = []

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
                trade_rows.append(
                    _build_trade_row(
                        symbol=symbol,
                        market=market,
                        entry_time=entry_time,
                        exit_time=_format_time(daily.index[index]),
                        entry_price=entry_price,
                        exit_price=current_close,
                        position_size=allocation,
                        quantity=quantity,
                        position_source=position_source,
                        symbols_source=symbols_source,
                    )
                )
            holding = False
            entry_price = None
            entry_time = ""
            quantity = 0.0
        elif not holding and trend_ok:
            holding = True
            entry_price = current_close
            entry_time = _format_time(daily.index[index])
            quantity = _quantity_for(allocation, current_close)

    if holding and entry_price:
        trade_returns.append(closes[-1] / entry_price - 1)
        trade_rows.append(
            _build_trade_row(
                symbol=symbol,
                market=market,
                entry_time=entry_time,
                exit_time=_format_time(daily.index[-1]),
                entry_price=entry_price,
                exit_price=closes[-1],
                position_size=allocation,
                quantity=quantity,
                position_source=position_source,
                symbols_source=symbols_source,
            )
        )

    return SymbolBacktest(
        symbol=symbol,
        returns=pd.Series(daily_returns, index=daily.index, dtype=float),
        trade_returns=tuple(trade_returns),
        trade_rows=tuple(trade_rows),
    )


def _is_intraday_force_close_time(value: object, market: str) -> bool:
    if not hasattr(value, "to_pydatetime") and not hasattr(value, "time"):
        value = pd.Timestamp(value)
    dt = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    session = SESSIONS[market]  # type: ignore[index]
    local_time = dt.time()
    force_close = (datetime.combine(dt.date(), session.close_time) - timedelta(minutes=10)).time()
    return force_close <= local_time < session.close_time


def _int_param(params: dict[str, object], key: str, default: int) -> int:
    value = params.get(key)
    if isinstance(value, (int, float)):
        return int(value)
    return default


def _position_size(request: BacktestRequest, symbol_count: int) -> tuple[float, str]:
    params = request.params_snapshot
    if request.strategy_id == "intraday_macd":
        fraction = params.get("position_fraction_pct")
        if isinstance(fraction, (int, float)) and fraction > 0:
            return request.initial_capital * float(fraction) / 100, f"策略参数 position_fraction_pct={fraction}%"
    if request.strategy_id == "trend_portfolio":
        cap = params.get("single_position_cap_pct")
        if isinstance(cap, (int, float)) and cap > 0:
            return request.initial_capital * float(cap) / 100, f"策略参数 single_position_cap_pct={cap}%"
    return request.initial_capital / max(symbol_count, 1), "fallback 等权分配"


def _quantity_for(position_size: float, entry_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    return round(position_size / entry_price, 4)


def _build_trade_row(
    *,
    symbol: str,
    market: str,
    entry_time: str,
    exit_time: str,
    entry_price: float,
    exit_price: float,
    position_size: float,
    quantity: float,
    position_source: str,
    symbols_source: str,
    side: str = "long",
    entry_reason: str = "",
    exit_reason: str = "",
    max_favorable_pct: float = 0.0,
    max_adverse_pct: float = 0.0,
) -> BacktestTradeRow:
    if side == "short":
        pnl = (entry_price - exit_price) * quantity
        pnl_pct = 0.0 if entry_price <= 0 else (entry_price - exit_price) / entry_price * 100
    else:
        pnl = (exit_price - entry_price) * quantity
        pnl_pct = 0.0 if entry_price <= 0 else (exit_price / entry_price - 1) * 100
    return BacktestTradeRow(
        symbol=symbol,
        market=market,  # type: ignore[arg-type]
        side=side,  # type: ignore[arg-type]
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=round(entry_price, 4),
        exit_price=round(exit_price, 4),
        position_size=round(position_size, 2),
        quantity=quantity,
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 2),
        position_source=position_source,
        symbols_source=symbols_source,
        entry_reason=entry_reason,
        exit_reason=exit_reason,
        max_favorable_pct=round(max_favorable_pct, 2),
        max_adverse_pct=round(max_adverse_pct, 2),
    )


def _combine_returns(runs: list[SymbolBacktest]) -> pd.Series:
    frame = pd.concat({run.symbol: run.returns for run in runs}, axis=1).sort_index()
    return frame.mean(axis=1).fillna(0.0)


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
    if hasattr(value, "hour") and hasattr(value, "minute") and hasattr(value, "second"):
        if value.hour == 0 and value.minute == 0 and value.second == 0:  # type: ignore[attr-defined]
            return value.strftime("%Y-%m-%d")  # type: ignore[attr-defined]
        return value.strftime("%Y-%m-%d %H:%M:%S")  # type: ignore[attr-defined]
    if hasattr(value, "isoformat"):
        return str(value.isoformat()).replace("T", " ")
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
        trade_rows=[],
        notes=notes,
    )


def _strategy_notes(strategy_id: str, used_symbols: int, requested_symbols: list[str]) -> list[str]:
    if strategy_id == "intraday_macd":
        mode = "日内 MACD 分钟回测；使用真实1分钟线重建15/5/3分钟柱体，并复用实盘多空与退出逻辑。"
    else:
        mode = "日线趋势代理回测；月/周线组合调仓 vnpy 回测仍待接入。"
    return [
        mode,
        f"本次使用 {used_symbols}/{len(requested_symbols)} 个标的生成组合收益。",
    ]
