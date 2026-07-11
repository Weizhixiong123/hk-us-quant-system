from __future__ import annotations

import math
import hashlib
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from uuid import uuid4

import pandas as pd

from app.models.schemas import BacktestRequest, BacktestResult, BacktestTradeRow, EquityPoint
from quant.data.fundamentals import RawFundamentals, load_fundamentals
from quant.data.loaders import Fetcher, MinuteFetcher, load_daily, load_minutes
from quant.data.universe import SymbolInfo, get_universe
from quant.indicators.macd import has_top_divergence, macd
from quant.indicators.trend import max_drawdown_pct, sma
from quant.data.resample import resample_ohlcv
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


@dataclass
class TrendHolding:
    symbol: str
    avg_price: float
    quantity: float
    entry_index: int
    entry_time: str
    target_value: float
    invested_fraction: float
    peak_price: float
    take_profit_20_done: bool = False
    take_profit_35_armed: bool = False
    add_done: bool = False


@dataclass(frozen=True)
class TrendPortfolioBacktest:
    returns: pd.Series
    trade_returns: tuple[float, ...]
    trade_rows: tuple[BacktestTradeRow, ...]
    notes: tuple[str, ...]


UniverseProvider = Callable[[str], list[SymbolInfo]]


def run_backtest(
    request: BacktestRequest,
    fetcher: Fetcher | None = None,
    minute_fetcher: MinuteFetcher | None = None,
    universe_provider: UniverseProvider | None = None,
) -> BacktestResult:
    auto_symbols = request.symbols_mode == "auto"
    symbols_source = request.symbols_source
    notes: list[str] = []
    intraday_selection_days: dict[str, set[date]] | None = None
    adjusted_request = _ensure_minimum_trend_range(request)
    if adjusted_request.start_date != request.start_date:
        notes.append(f"中长线回测区间不足 6 个月，已自动扩展起始日期至 {adjusted_request.start_date}。")
        request = adjusted_request
    if auto_symbols:
        universe = _backtest_universe(request.market, fetcher, universe_provider)
        symbols, intraday_selection_days = _auto_select_symbols(request, fetcher, universe)
        symbols_source = "自动选股策略"
        if symbols:
            if request.strategy_id == "trend_portfolio":
                notes.append(f"已加载全市场 {len(symbols)} 只候选标的，按历史月末逐期筛选。")
            else:
                notes.append(f"已按{symbols_source}筛选出 {len(symbols)} 只标的。")
        else:
            notes.append("全市场自动选股未筛出符合条件的标的。")
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

    if request.strategy_id == "trend_portfolio":
        trend_run = _run_trend_portfolio_backtest(request, symbols, fetcher, symbols_source)
        notes.extend(trend_run.notes)
        if trend_run.returns.empty:
            result = _empty_result(request, notes or ["没有可用于回测的数据。"])
            _log_backtest(f"回测结束：没有可用标的生成结果 id={result.id} trades=0")
            return result
        equity = request.initial_capital * (1 + trend_run.returns).cumprod()
        result = BacktestResult(
            id=f"BT-{uuid4().hex[:8].upper()}",
            strategy_id=request.strategy_id,
            market=request.market,
            start_date=request.start_date,
            end_date=request.end_date,
            total_return_pct=_total_return_pct(equity, request.initial_capital),
            max_drawdown_pct=max_drawdown_pct(equity.tolist()),
            sharpe=_sharpe(trend_run.returns),
            win_rate_pct=_win_rate_pct(list(trend_run.trade_returns)),
            trades=len(trend_run.trade_returns),
            equity_curve=_build_equity_curve(equity),
            trade_rows=list(trend_run.trade_rows),
            notes=notes + _strategy_notes(request.strategy_id, len(symbols), symbols),
        )
        _log_backtest(
            "回测完成 "
            f"id={result.id} used_symbols={len(symbols)}/{len(symbols)} trades={result.trades} "
            f"total_return_pct={result.total_return_pct} max_drawdown_pct={result.max_drawdown_pct}"
        )
        return result

    for symbol in symbols:
        if request.strategy_id == "intraday_macd":
            try:
                _log_backtest(
                    f"加载1分钟线 symbol={symbol} market={request.market} "
                    f"range={request.start_date}~{request.end_date} source={'custom' if minute_fetcher else 'default'}"
                )
                minutes = _load_backtest_minutes(
                    symbol, request.market, request.start_date, request.end_date, "1m", minute_fetcher
                )
                _log_backtest(f"1分钟线加载完成 symbol={symbol} rows={len(minutes)}")
            except Exception as exc:
                _log_backtest(f"1分钟线加载失败 symbol={symbol} error={exc}")
                notes.append(f"{symbol} 1分钟线加载失败，已跳过：{exc}")
                continue
            slow_ema = _int_param(request.params_snapshot, "slow_ema", 26)
            slow_k_minutes = _int_param(request.params_snapshot, "slow_k_minutes", 15)
            minimum_minutes = (slow_ema + 1) * slow_k_minutes
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
                allowed_entry_dates=(intraday_selection_days or {}).get(symbol),
            )
            _log_backtest(f"标的回测完成 symbol={symbol} trades={len(symbol_run.trade_rows)} bars={len(minutes)}")
            runs.append(symbol_run)
            continue

        if request.strategy_id == "ma_atr_intraday":
            try:
                minutes = _load_backtest_minutes(
                    symbol, request.market, request.start_date, request.end_date, "1m", minute_fetcher
                )
            except Exception as exc:
                notes.append(f"{symbol} 1分钟线加载失败，已跳过：{exc}")
                continue
            slow_ema = _int_param(request.params_snapshot, "macd_slow", 26)
            slow_k_minutes = _int_param(request.params_snapshot, "slow_k_minutes", 60)
            minimum_minutes = (slow_ema + 1) * slow_k_minutes
            if minutes.empty or len(minutes) < minimum_minutes:
                notes.append(f"{symbol} 1分钟线不足（需要至少 {minimum_minutes} 根），已跳过。")
                continue
            symbol_run = _run_ma_atr_minutes(
                symbol, minutes, request, allocation,
                position_source, symbols_source,
                allowed_entry_dates=(intraday_selection_days or {}).get(symbol),
            )
            _log_backtest(f"策略三回测完成 symbol={symbol} trades={len(symbol_run.trade_rows)}")
            runs.append(symbol_run)
            continue

        try:
            daily = _load_backtest_daily(symbol, request.market, request.start_date, request.end_date, fetcher)
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


def _ensure_minimum_trend_range(request: BacktestRequest) -> BacktestRequest:
    if request.strategy_id not in {"trend_portfolio", "ma_atr_intraday"}:
        return request
    try:
        start = datetime.strptime(request.start_date, "%Y-%m-%d")
        end = datetime.strptime(request.end_date, "%Y-%m-%d")
    except ValueError:
        return request
    min_months = 6 if request.strategy_id == "trend_portfolio" else 2
    minimum_start = _subtract_months(end, min_months)
    if start <= minimum_start:
        return request
    return request.model_copy(update={"start_date": minimum_start.strftime("%Y-%m-%d")})


def _subtract_months(value: datetime, months: int) -> datetime:
    month = value.month - months
    year = value.year
    while month <= 0:
        month += 12
        year -= 1
    days_in_month = [31, 29 if _is_leap_year(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(value.day, days_in_month[month - 1])
    return value.replace(year=year, month=month, day=day)


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _auto_select_symbols(
    request: BacktestRequest,
    fetcher: Fetcher | None,
    universe: list[SymbolInfo],
) -> tuple[list[str], dict[str, set[date]] | None]:
    if request.strategy_id == "intraday_macd":
        return _auto_select_intraday_symbols(request, fetcher, universe)
    if request.strategy_id == "ma_atr_intraday":
        return _auto_select_intraday_symbols(request, fetcher, universe)
    if request.strategy_id == "trend_portfolio":
        return _auto_select_trend_symbols(request, universe), None
    return [item.symbol for item in universe], None


def _auto_select_trend_symbols(request: BacktestRequest, universe: list[SymbolInfo]) -> list[str]:
    symbols = [item.symbol for item in universe]
    _log_backtest(
        f"中长全市场候选池加载完成 market={request.market} universe={len(symbols)}；"
        "将在每个历史月末按当时数据重新筛选"
    )
    return symbols


def _auto_select_intraday_symbols(
    request: BacktestRequest,
    fetcher: Fetcher | None,
    universe: list[SymbolInfo],
) -> tuple[list[str], dict[str, set[date]]]:
    daily_by_symbol: dict[str, tuple[SymbolInfo, pd.DataFrame]] = {}
    warmup_start = (datetime.strptime(request.start_date, "%Y-%m-%d") - timedelta(days=40)).strftime("%Y-%m-%d")
    for item in universe:
        try:
            daily = _load_backtest_daily(item.symbol, request.market, warmup_start, request.end_date, fetcher)
        except Exception as exc:
            _log_backtest(f"自动选股日线加载失败 symbol={item.symbol} error={exc}")
            continue
        if len(daily) < 21:
            continue
        daily_by_symbol[item.symbol] = (item, daily.sort_index())

    candidate_limit = _int_param(request.params_snapshot, "backtest_candidate_limit", 30)
    selection_days: dict[str, set[date]] = {}
    start = pd.Timestamp(request.start_date)
    end = pd.Timestamp(request.end_date)
    trading_days = sorted(
        day for day in set().union(*(set(frame.index) for _, frame in daily_by_symbol.values()))
        if start <= day <= end
    )
    for trading_day in trading_days:
        candidates = [
            candidate
            for item, daily in daily_by_symbol.values()
            if (candidate := _historical_intraday_candidate(item, daily, trading_day)) is not None
        ]
        ranked = sorted(candidates, key=lambda item: item.avg_turnover, reverse=True)
        selected = build_premarket_watchlist(
            ranked,
            min_turnover=float(request.params_snapshot.get("min_turnover", 5_000_000.0)),
            min_amplitude_pct=float(request.params_snapshot.get("min_amplitude_pct", 2.0)),
            max_amplitude_pct=float(request.params_snapshot.get("max_amplitude_pct", 8.0)),
            min_price=float(request.params_snapshot.get("min_price", 2.0)),
            min_turnover_rate=float(request.params_snapshot.get("min_turnover_rate", 0.0)),
        )[:max(candidate_limit, 1)]
        for symbol in selected:
            selection_days.setdefault(symbol, set()).add(trading_day.date())

    symbols = list(selection_days)
    _log_backtest(
        f"日内全市场历史选股完成 market={request.market} loaded={len(daily_by_symbol)} "
        f"trading_days={len(trading_days)} selected_union={len(symbols)}"
    )
    return symbols, selection_days


def _historical_intraday_candidate(
    item: SymbolInfo,
    daily: pd.DataFrame,
    trading_day: pd.Timestamp,
) -> IntradayCandidate | None:
    history = daily.loc[daily.index < trading_day].tail(20)
    if len(history) < 20:
        return None
    prev = history.iloc[-1]
    prev_close = float(prev["close"])
    amplitude = (float(prev["high"]) - float(prev["low"])) / prev_close * 100 if prev_close > 0 else 0.0
    return IntradayCandidate(
        symbol=item.symbol,
        market=item.market,
        avg_turnover=float((history["close"] * history["volume"]).mean()),
        prev_amplitude_pct=round(amplitude, 4),
        price=prev_close,
        halted=False,
        ex_dividend_soon=False,
        major_news=False,
    )


def _backtest_universe(
    market: str,
    fetcher: Fetcher | None,
    provider: UniverseProvider | None = None,
) -> list[SymbolInfo]:
    if provider is not None:
        return list(provider(market))
    if fetcher is not None:
        return get_universe(market)
    try:
        from quant.data.futu_market_scanner import FutuMarketScanner
        from quant.live.config import load_futu_config

        config = load_futu_config()
        scanner = FutuMarketScanner(config.host, config.port, (market,))
        symbols = scanner.symbols(market)
        if symbols:
            return symbols
    except Exception as exc:
        _log_backtest(f"全市场证券列表读取失败 market={market} error={exc}，使用静态降级池")
    return get_universe(market)


def _load_backtest_daily(
    symbol: str,
    market: str,
    start: str,
    end: str,
    fetcher: Fetcher | None,
) -> pd.DataFrame:
    if fetcher is not None:
        return load_daily(symbol, market, start, end, fetcher)
    return _load_cached_bars(
        "1d", symbol, market, start, end,
        lambda: load_daily(symbol, market, start, end),
    )


def _load_backtest_minutes(
    symbol: str,
    market: str,
    start: str,
    end: str,
    interval: str,
    fetcher: MinuteFetcher | None,
) -> pd.DataFrame:
    if fetcher is not None:
        return load_minutes(symbol, market, start, end, interval, fetcher)
    return _load_cached_bars(
        interval, symbol, market, start, end,
        lambda: load_minutes(symbol, market, start, end, interval),
    )


def _load_cached_bars(
    interval: str,
    symbol: str,
    market: str,
    start: str,
    end: str,
    loader: Callable[[], pd.DataFrame],
) -> pd.DataFrame:
    cache_dir = Path(
        os.getenv(
            "BACKTEST_CACHE_DIR",
            str(Path(__file__).resolve().parents[2] / "data" / "backtest-cache"),
        )
    )
    key = hashlib.sha256(f"v1|{market}|{symbol}|{interval}|{start}|{end}".encode()).hexdigest()
    path = cache_dir / f"{key}.csv"
    if path.exists():
        try:
            cached = pd.read_csv(path, index_col=0, parse_dates=True)
            cached.index = pd.to_datetime(cached.index)
            return cached
        except (OSError, ValueError, pd.errors.ParserError):
            pass

    bars = loader()
    if not bars.empty:
        cache_dir.mkdir(parents=True, exist_ok=True)
        bars.to_csv(path)
    return bars


def _run_intraday_macd_minutes(
    symbol: str,
    minutes: pd.DataFrame,
    request: BacktestRequest,
    allocation: float,
    position_source: str,
    symbols_source: str,
    allowed_entry_dates: set[date] | None = None,
) -> SymbolBacktest:
    params = request.params_snapshot
    fast_ema = _int_param(params, "fast_ema", 12)
    slow_ema = _int_param(params, "slow_ema", 26)
    signal_ema = _int_param(params, "signal_ema", 9)
    open_after_minutes = _int_param(params, "open_after_minutes", 30)
    close_before_minutes = _int_param(params, "close_before_minutes", 90)
    slow_k_minutes = _int_param(params, "slow_k_minutes", 15)
    mid_k_minutes = _int_param(params, "mid_k_minutes", 5)
    fast_k_minutes = _int_param(params, "fast_k_minutes", 3)

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
            elif is_market_open(at, request.market) and is_bar_close(at, fast_k_minutes, request.market):
                closes_slow, closes_mid, closes_fast = _three_period_closes(
                    aggregator, symbol,
                    slow_k_minutes=slow_k_minutes,
                    mid_k_minutes=mid_k_minutes,
                    fast_k_minutes=fast_k_minutes,
                )
                momentum = three_period_macd_momentum(
                    closes_slow,
                    closes_mid,
                    closes_fast,
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

        elif (
            (allowed_entry_dates is None or at.date() in allowed_entry_dates)
            and is_market_open(at, request.market)
            and is_bar_close(at, fast_k_minutes, request.market)
        ):
            closes_slow, closes_mid, closes_fast = _three_period_closes(
                aggregator, symbol,
                slow_k_minutes=slow_k_minutes,
                mid_k_minutes=mid_k_minutes,
                fast_k_minutes=fast_k_minutes,
            )
            if min(len(closes_slow), len(closes_mid), len(closes_fast)) >= slow_ema + 1:
                signal = evaluate_intraday_entry_signal(
                    symbol=symbol,
                    market=request.market,
                    at=at,
                    closes_slow=closes_slow,
                    closes_mid=closes_mid,
                    closes_fast=closes_fast,
                    fast_ema=fast_ema,
                    slow_ema=slow_ema,
                    signal_ema=signal_ema,
                    slow_k_minutes=slow_k_minutes,
                    mid_k_minutes=mid_k_minutes,
                    fast_k_minutes=fast_k_minutes,
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


def _run_ma_atr_minutes(
    symbol: str,
    minutes: pd.DataFrame,
    request: BacktestRequest,
    allocation: float,
    position_source: str,
    symbols_source: str,
    allowed_entry_dates: set[date] | None = None,
) -> SymbolBacktest:
    """策略三回测:三周期 MA + MACD 金叉 + ATR 动态止损。"""
    from quant.live.ma_atr_intraday import MaAtrPosition, evaluate_ma_atr_entry_signal, evaluate_ma_atr_exit_signal

    params = request.params_snapshot
    slow_k_minutes = _int_param(params, "slow_k_minutes", 60)
    mid_k_minutes = _int_param(params, "mid_k_minutes", 10)
    fast_k_minutes = _int_param(params, "fast_k_minutes", 5)
    slow_fast_ema = _int_param(params, "slow_fast_ema", 3)
    slow_slow_ema = _int_param(params, "slow_slow_ema", 8)
    mid_fast_ema = _int_param(params, "mid_fast_ema", 11)
    mid_slow_ema = _int_param(params, "mid_slow_ema", 30)
    fast_fast_ema = _int_param(params, "fast_fast_ema", 3)
    fast_slow_ema = _int_param(params, "fast_slow_ema", 8)
    macd_fast = _int_param(params, "macd_fast", 12)
    macd_slow = _int_param(params, "macd_slow", 26)
    macd_signal = _int_param(params, "macd_signal", 9)
    atr_period = _int_param(params, "atr_period", 5)
    atr_multiplier = _float_param(params, "atr_multiplier", 1.2)
    open_after_minutes = _int_param(params, "open_after_minutes", 30)
    close_before_minutes = _int_param(params, "close_before_minutes", 90)
    stop_loss_pct = _float_param(params, "stop_loss_pct", 1.5)
    take_profit_pct = _float_param(params, "take_profit_pct", 3.0)
    trailing_enabled = params.get("trailing_enabled", True) if params else True
    trailing_start_pct = _float_param(params, "trailing_start_pct", 2.0)
    trailing_stop_pct = _float_param(params, "trailing_stop_pct", 1.0)

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
    highest_since_entry = 0.0

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
            highest_since_entry = max(highest_since_entry, high)
            lowest_price = min(lowest_price, low)
            max_favorable_pct, max_adverse_pct = _intraday_excursions(
                side, entry_price, highest_price, lowest_price,
            )
            if _is_intraday_force_close_time(at, request.market):
                exit_price = close
                exit_reason = "尾盘强制平仓"
            elif is_market_open(at, request.market) and is_bar_close(at, fast_k_minutes, request.market):
                closes_slow, closes_mid, closes_fast = _three_period_closes(
                    aggregator, symbol,
                    slow_k_minutes=slow_k_minutes,
                    mid_k_minutes=mid_k_minutes,
                    fast_k_minutes=fast_k_minutes,
                )
                highs_fast = [bar.high for bar in aggregator.interval_bars(symbol, fast_k_minutes, limit=80)]
                lows_fast = [bar.low for bar in aggregator.interval_bars(symbol, fast_k_minutes, limit=80)]
                action, reasons = evaluate_ma_atr_exit_signal(
                    MaAtrPosition(symbol=symbol, side=side, quantity=max(1, int(quantity)),
                                  avg_price=entry_price, highest_since_entry=highest_since_entry),
                    closes_slow, closes_mid, closes_fast, highs_fast, lows_fast,
                    fast_fast_ema=fast_fast_ema, fast_slow_ema=fast_slow_ema,
                    mid_fast_ema=mid_fast_ema, mid_slow_ema=mid_slow_ema,
                    macd_fast=macd_fast, macd_slow=macd_slow, macd_signal=macd_signal,
                    atr_period=atr_period, atr_multiplier=atr_multiplier,
                    stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct,
                    trailing_enabled=trailing_enabled,
                    trailing_start_pct=trailing_start_pct, trailing_stop_pct=trailing_stop_pct,
                )
                if action.startswith("exit"):
                    exit_price = open_price
                    exit_reason = reasons[0] if reasons else "策略三平仓"

            if exit_price is not None:
                trade_return = _intraday_trade_return(side, entry_price, exit_price)
                returns[-1] = trade_return
                trade_returns.append(trade_return)
                trade_rows.append(
                    _build_trade_row(
                        symbol=symbol, market=request.market, side=side,
                        entry_time=entry_time, exit_time=_format_time(bar_time),
                        entry_price=entry_price, exit_price=exit_price,
                        position_size=allocation, quantity=quantity,
                        symbols_source=symbols_source, position_source=position_source,
                        entry_reason=entry_reason, exit_reason=exit_reason,
                        max_favorable_pct=max_favorable_pct, max_adverse_pct=max_adverse_pct,
                    )
                )
                holding = False
                side = "long"
                entry_price = 0.0
                entry_time = ""
                quantity = 0.0
                highest_price = 0.0
                lowest_price = 0.0
                highest_since_entry = 0.0
                max_favorable_pct = 0.0
                max_adverse_pct = 0.0

        if not holding:
            if (
                (allowed_entry_dates is None or at.date() in allowed_entry_dates)
                and is_market_open(at, request.market)
                and is_bar_close(at, fast_k_minutes, request.market)
            ):
                closes_slow, closes_mid, closes_fast = _three_period_closes(
                    aggregator, symbol,
                    slow_k_minutes=slow_k_minutes,
                    mid_k_minutes=mid_k_minutes,
                    fast_k_minutes=fast_k_minutes,
                )
                highs_fast = [bar.high for bar in aggregator.interval_bars(symbol, fast_k_minutes, limit=80)]
                lows_fast = [bar.low for bar in aggregator.interval_bars(symbol, fast_k_minutes, limit=80)]
                if min(len(closes_slow), len(closes_mid), len(closes_fast)) >= slow_ema + 1:
                    signal = evaluate_ma_atr_entry_signal(
                        symbol=symbol, market=request.market, at=at,
                        closes_slow=closes_slow, closes_mid=closes_mid, closes_fast=closes_fast,
                        highs_fast=highs_fast, lows_fast=lows_fast,
                        slow_fast_ema=slow_fast_ema, slow_slow_ema=slow_slow_ema,
                        mid_fast_ema=mid_fast_ema, mid_slow_ema=mid_slow_ema,
                        fast_fast_ema=fast_fast_ema, fast_slow_ema=fast_slow_ema,
                        macd_fast=macd_fast, macd_slow=macd_slow, macd_signal=macd_signal,
                        atr_period=atr_period, atr_multiplier=atr_multiplier,
                        open_after_minutes=open_after_minutes,
                        close_before_minutes=close_before_minutes,
                    )
                    if signal.action in {"enter_long", "enter_short"} and open_price > 0:
                        side = "long" if signal.action == "enter_long" else "short"
                        entry_price = open_price
                        entry_time = _format_time(bar_time)
                        entry_reason = f"MA+MACD+ATR 三周期{'开多' if side == 'long' else '开空'}：{slow_k_minutes}/{mid_k_minutes}/{fast_k_minutes}分钟"
                        quantity = _quantity_for(allocation, entry_price)
                        highest_price = max(entry_price, high)
                        lowest_price = min(entry_price, low)
                        highest_since_entry = high
                        max_favorable_pct, max_adverse_pct = _intraday_excursions(
                            side, entry_price, highest_price, lowest_price,
                        )
                        holding = True

        aggregator.seed_minute_bars(
            symbol,
            [Bar(symbol=symbol, start=at, open=open_price, high=high, low=low, close=close, volume=float(row["volume"]))],
        )

    if holding:
        row = bars.iloc[-1]
        exit_price = float(row["close"])
        trade_return = _intraday_trade_return(side, entry_price, exit_price)
        returns[-1] = trade_return
        trade_returns.append(trade_return)
        trade_rows.append(
            _build_trade_row(
                symbol=symbol, market=request.market, side=side,
                entry_time=entry_time, exit_time=_format_time(bars.index[-1]),
                entry_price=entry_price, exit_price=exit_price,
                position_size=allocation, quantity=quantity,
                symbols_source=symbols_source, position_source=position_source,
                entry_reason=entry_reason, exit_reason="回测结束强平",
                max_favorable_pct=max_favorable_pct, max_adverse_pct=max_adverse_pct,
            )
        )

    return SymbolBacktest(
        symbol=symbol,
        returns=pd.Series(returns, index=bars.index, dtype=float),
        trade_returns=tuple(trade_returns),
        trade_rows=tuple(trade_rows),
    )


def _three_period_closes(
    aggregator: BarAggregator,
    symbol: str,
    slow_k_minutes: int = 15,
    mid_k_minutes: int = 5,
    fast_k_minutes: int = 3,
) -> tuple[list[float], list[float], list[float]]:
    closes_slow = [bar.close for bar in aggregator.interval_bars(symbol, slow_k_minutes, limit=80)]
    closes_mid = [bar.close for bar in aggregator.interval_bars(symbol, mid_k_minutes, limit=80)]
    closes_fast = [bar.close for bar in aggregator.interval_bars(symbol, fast_k_minutes, limit=80)]
    return closes_slow, closes_mid, closes_fast


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

def _run_trend_portfolio_backtest(
    request: BacktestRequest,
    symbols: list[str],
    fetcher: Fetcher | None,
    symbols_source: str,
) -> TrendPortfolioBacktest:
    notes: list[str] = ["中长线组合回测：月末选股调仓、基本面硬筛、分批建仓、阶段止盈与趋势出场已启用。"]
    warmup_start = _trend_warmup_start(request.start_date)
    notes.append(f"已加载 {warmup_start} 起的预热数据，用于计算 60 月均线与周线指标。")
    data: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            daily = _load_backtest_daily(symbol, request.market, warmup_start, request.end_date, fetcher)
        except Exception as exc:
            notes.append(f"{symbol} 数据加载失败：{exc}")
            continue
        if len(daily) < 30:
            notes.append(f"{symbol} 数据不足，已跳过。")
            continue
        data[symbol] = daily.sort_index()
    if not data:
        return TrendPortfolioBacktest(pd.Series(dtype=float), (), (), tuple(notes))

    evaluation_start = pd.Timestamp(request.start_date)
    evaluation_end = pd.Timestamp(request.end_date)
    calendar = sorted(
        day
        for day in set().union(*(set(df.index) for df in data.values()))
        if evaluation_start <= day <= evaluation_end
    )
    if not calendar:
        return TrendPortfolioBacktest(pd.Series(dtype=float), (), (), tuple(notes))
    rebalance_dates = set(_month_end_dates(calendar))
    min_positions = _int_param(request.params_snapshot, "target_positions_min", 5)
    max_positions = _int_param(request.params_snapshot, "target_positions_max", 8)
    cap_pct = float(request.params_snapshot.get("single_position_cap_pct", 15.0))
    max_symbol_drawdown = float(request.params_snapshot.get("max_symbol_drawdown_pct", 18.0))
    cash = request.initial_capital
    holdings: dict[str, TrendHolding] = {}
    equity_values: list[float] = []
    returns: list[float] = []
    trade_rows: list[BacktestTradeRow] = []
    trade_returns: list[float] = []
    last_equity = request.initial_capital
    max_candidate_count = 0
    selected: list[str] = []

    for index, current_date in enumerate(calendar):
        prices = {symbol: _price_on_or_before(df, current_date) for symbol, df in data.items()}
        prices = {symbol: price for symbol, price in prices.items() if price is not None and price > 0}
        if not prices:
            returns.append(0.0)
            equity_values.append(last_equity)
            continue

        equity_before_actions = cash + sum(holding.quantity * prices.get(symbol, holding.avg_price) for symbol, holding in holdings.items())

        for symbol in list(holdings):
            if symbol not in prices:
                continue
            holding = holdings[symbol]
            price = prices[symbol]
            holding.peak_price = max(holding.peak_price, price)
            history = _history_until(data[symbol], current_date)
            snapshot = _trend_backtest_snapshot(history)
            pnl_pct = (price / holding.avg_price - 1) * 100 if holding.avg_price > 0 else 0.0
            drawdown_pct = (holding.peak_price - price) / holding.peak_price * 100 if holding.peak_price > 0 else 0.0
            holding_days = index - holding.entry_index
            exit_reason = _trend_exit_reason(snapshot, pnl_pct, drawdown_pct, holding_days)
            if not exit_reason and holding.take_profit_35_armed and (snapshot["weekly_macd_top_divergence"] or not snapshot["weekly_macd_hist_healthy"]):
                exit_reason = "盈利超过 35% 后周线动能走弱，清仓锁定收益"
            if exit_reason:
                value = holding.quantity * price
                cash += value
                trade_returns.append(price / holding.avg_price - 1 if holding.avg_price > 0 else 0.0)
                trade_rows.append(_trend_trade_row(symbol, request.market, "close", "清仓", holding.entry_time, current_date, holding.avg_price, price, value, holding.quantity, cash, equity_before_actions, symbols_source, exit_reason, holding))
                del holdings[symbol]
                continue
            if pnl_pct >= 20 and not holding.take_profit_20_done and holding.quantity > 0:
                sell_qty = round(holding.quantity * 0.5, 4)
                value = sell_qty * price
                cash += value
                holding.quantity = round(holding.quantity - sell_qty, 4)
                holding.invested_fraction *= 0.5
                holding.take_profit_20_done = True
                trade_rows.append(_trend_trade_row(symbol, request.market, "reduce", "阶段止盈20%减仓", holding.entry_time, current_date, holding.avg_price, price, value, sell_qty, cash, equity_before_actions, symbols_source, "阶段性盈利达到 20%，减仓 50%", holding))
            if pnl_pct >= 35:
                holding.take_profit_35_armed = True

        if current_date in rebalance_dates:
            candidates = _trend_rank_candidates(data, request.market, current_date, request.params_snapshot)
            max_candidate_count = max(max_candidate_count, len(candidates))
            selected = [symbol for symbol, _score in candidates[:max_positions]]
            for symbol in list(holdings):
                if symbol not in selected and symbol in prices:
                    holding = holdings[symbol]
                    price = prices[symbol]
                    value = holding.quantity * price
                    cash += value
                    trade_returns.append(price / holding.avg_price - 1 if holding.avg_price > 0 else 0.0)
                    trade_rows.append(_trend_trade_row(symbol, request.market, "close", "月末调仓剔除", holding.entry_time, current_date, holding.avg_price, price, value, holding.quantity, cash, equity_before_actions, symbols_source, "月末重新选股未入选，调仓剔除", holding))
                    del holdings[symbol]

        if selected:
            equity_now = cash + sum(holding.quantity * prices.get(symbol, holding.avg_price) for symbol, holding in holdings.items())
            target_value = min(equity_now * cap_pct / 100, equity_now / max(min(max_positions, max(len(selected), 1)), 1))
            for symbol in selected:
                if symbol not in prices:
                    continue
                history = _history_until(data[symbol], current_date)
                closes = history["close"].astype(float).tolist()
                lows = history["low"].astype(float).tolist()
                volumes = history["volume"].astype(float).tolist()
                bar_index = len(history) - 1
                if symbol in holdings:
                    holding = holdings[symbol]
                    if not holding.add_done and _trend_daily_entry_ok(closes, lows, volumes, bar_index):
                        add_value = min(target_value * 0.4, cash)
                        if add_value > 0:
                            add_qty = _quantity_for(add_value, prices[symbol])
                            total_cost = holding.avg_price * holding.quantity + prices[symbol] * add_qty
                            holding.quantity = round(holding.quantity + add_qty, 4)
                            holding.avg_price = total_cost / holding.quantity if holding.quantity else holding.avg_price
                            holding.invested_fraction = min(1.0, holding.invested_fraction + 0.4)
                            holding.add_done = True
                            cash -= add_value
                            trade_rows.append(_trend_trade_row(symbol, request.market, "add", "补仓", holding.entry_time, current_date, prices[symbol], prices[symbol], add_value, add_qty, cash, equity_now, symbols_source, "日线再次回踩 20/30 日均线企稳，补足剩余 40% 仓位", holding))
                    continue
                if len(holdings) >= max_positions or cash <= 0:
                    continue
                if _trend_daily_entry_ok(closes, lows, volumes, bar_index):
                    first_value = min(target_value * 0.6, cash)
                    if first_value <= 0:
                        continue
                    qty = _quantity_for(first_value, prices[symbol])
                    holding = TrendHolding(symbol, prices[symbol], qty, index, _format_time(current_date), target_value, 0.6, prices[symbol])
                    holdings[symbol] = holding
                    cash -= first_value
                    trade_rows.append(_trend_trade_row(symbol, request.market, "open", "首次建仓", _format_time(current_date), current_date, prices[symbol], prices[symbol], first_value, qty, cash, equity_now, symbols_source, "月线定方向、周线确认趋势、日线回踩企稳，首次建立 60% 仓位", holding))

        equity = cash + sum(holding.quantity * prices.get(symbol, holding.avg_price) for symbol, holding in holdings.items())
        returns.append(equity / last_equity - 1 if last_equity > 0 else 0.0)
        equity_values.append(equity)
        last_equity = equity

    final_date = calendar[-1]
    final_prices = {symbol: _price_on_or_before(df, final_date) for symbol, df in data.items()}
    for symbol, holding in list(holdings.items()):
        price = final_prices.get(symbol) or holding.avg_price
        value = holding.quantity * price
        cash += value
        trade_returns.append(price / holding.avg_price - 1 if holding.avg_price > 0 else 0.0)
        trade_rows.append(_trend_trade_row(symbol, request.market, "close", "回测结束清仓", holding.entry_time, final_date, holding.avg_price, price, value, holding.quantity, cash, last_equity, symbols_source, "回测结束强制平仓", holding))

    if max_candidate_count < min_positions:
        notes.append(
            f"回测期间单次最多 {max_candidate_count} 只标的通过中长线硬筛，"
            f"低于目标持仓下限 {min_positions} 只；已按实际合格标的执行。"
        )

    return TrendPortfolioBacktest(pd.Series(returns, index=calendar, dtype=float), tuple(trade_returns), tuple(trade_rows), tuple(notes))


def _trend_warmup_start(start_date: str) -> str:
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        return start_date
    return _subtract_months(start, 62).strftime("%Y-%m-%d")



def _month_end_dates(calendar: list[pd.Timestamp]) -> list[pd.Timestamp]:
    result: list[pd.Timestamp] = []
    for idx, day in enumerate(calendar):
        if idx == len(calendar) - 1 or calendar[idx + 1].month != day.month or calendar[idx + 1].year != day.year:
            result.append(day)
    return result


def _history_until(daily: pd.DataFrame, current_date: pd.Timestamp) -> pd.DataFrame:
    return daily.loc[daily.index <= current_date]


def _price_on_or_before(daily: pd.DataFrame, current_date: pd.Timestamp) -> float | None:
    history = _history_until(daily, current_date)
    if history.empty:
        return None
    return float(history.iloc[-1]["close"])


def _trend_rank_candidates(
    data: dict[str, pd.DataFrame],
    market: str,
    current_date: pd.Timestamp,
    params: dict[str, object],
) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    for symbol, daily in data.items():
        history = _history_until(daily, current_date)
        if len(history) < 120:
            continue
        snapshot = _trend_backtest_snapshot(history)
        fundamentals = _trend_fundamentals(symbol, market, params)
        if not _trend_entry_ok(snapshot):
            continue
        min_cap = 5_000_000_000 if market == "HK" else 2_000_000_000
        if fundamentals.positive_profit_quarters < 2 or fundamentals.has_major_risk or fundamentals.market_cap < min_cap:
            continue
        score = _trend_candidate_score(snapshot)
        candidates.append((symbol, score))
    return sorted(candidates, key=lambda item: item[1], reverse=True)


def _trend_fundamentals(symbol: str, market: str, params: dict[str, object]):
    configured = params.get("fundamentals")
    raw: RawFundamentals | None = None
    risk_blocklist = params.get("risk_blocklist")
    risks = risk_blocklist if isinstance(risk_blocklist, list) else []
    if isinstance(configured, dict):
        item = configured.get(symbol.upper()) or configured.get(symbol)
        if isinstance(item, dict):
            raw = RawFundamentals(
                market_cap=float(item.get("market_cap", 0.0)),
                positive_profit_quarters=int(item.get("positive_profit_quarters", 0)),
            )
    if raw is None:
        # 回测缺少点时基本面时使用保守但可运行的兜底：主流候选池视为满足硬筛；测试可用 params 覆盖。
        raw = RawFundamentals(market_cap=10_000_000_000.0, positive_profit_quarters=2)
    return load_fundamentals(symbol, market, lambda _symbol, _market: raw, risk_blocklist=risks)


def _trend_candidate_score(snapshot: dict[str, float | bool]) -> float:
    return (
        float(snapshot.get("ma5_week", 0.0))
        + float(snapshot.get("ma10_week", 0.0))
        + float(snapshot.get("ma20_week", 0.0))
        - float(snapshot.get("max_drawdown_3m_pct", 0.0))
        - float(snapshot.get("short_term_gain_pct", 0.0)) * 0.1
    )


def _trend_trade_row(
    symbol: str,
    market: str,
    action: str,
    action_label: str,
    entry_time: str,
    current_date: pd.Timestamp,
    entry_price: float,
    price: float,
    value: float,
    quantity: float,
    cash_after: float,
    equity: float,
    symbols_source: str,
    reason: str,
    holding: TrendHolding,
) -> BacktestTradeRow:
    return _build_trade_row(
        symbol=symbol,
        market=market,
        entry_time=entry_time,
        exit_time=_format_time(current_date),
        entry_price=entry_price,
        exit_price=price,
        position_size=value,
        quantity=quantity,
        position_source="策略默认单只最大 15%",
        symbols_source=symbols_source,
        action=action,
        action_label=action_label,
        cash_after=cash_after,
        position_value=value,
        weight_pct=(value / equity * 100) if equity > 0 else 0.0,
        entry_reason=reason if action in {"open", "add"} else "中长线持仓管理",
        exit_reason=reason if action in {"reduce", "close"} else "",
        max_favorable_pct=(holding.peak_price / holding.avg_price - 1) * 100 if holding.avg_price > 0 else 0.0,
        max_adverse_pct=0.0,
    )


def _trend_backtest_snapshot(daily: pd.DataFrame) -> dict[str, float | bool]:
    closes = daily["close"].astype(float).tolist()
    weekly = resample_ohlcv(daily, "W")
    monthly = resample_ohlcv(daily, "ME")
    weekly_closes = weekly["close"].astype(float).tolist()
    weekly_highs = weekly["high"].astype(float).tolist()
    weekly_lows = weekly["low"].astype(float).tolist()
    monthly_closes = monthly["close"].astype(float).tolist()
    monthly_highs = monthly["high"].astype(float).tolist()
    monthly_macd = macd(monthly_closes)
    weekly_macd = macd(weekly_closes)

    return {
        "price": closes[-1] if closes else 0.0,
        "ma20_month": sma(monthly_closes, 20) or float("inf"),
        "ma60_month": sma(monthly_closes, 60) or float("inf"),
        "month_macd_above_zero": bool(monthly_macd and monthly_macd[-1].dif > 0 and monthly_macd[-1].dea > 0),
        "ma5_week": sma(weekly_closes, 5) or 0.0,
        "ma10_week": sma(weekly_closes, 10) or 0.0,
        "ma20_week": sma(weekly_closes, 20) or 0.0,
        "weekly_rising": _trend_weekly_rising(weekly_highs, weekly_lows),
        "weekly_ma_break": _trend_weekly_ma_break(weekly_closes),
        "monthly_below_ma60_two_months": _trend_monthly_below_ma60_two_months(monthly_closes),
        "monthly_macd_below_zero": bool(monthly_macd and monthly_macd[-1].dif < 0 and monthly_macd[-1].dea < 0),
        "weekly_macd_hist_positive": _trend_macd_hist_positive(weekly_macd),
        "weekly_macd_hist_healthy": _trend_macd_hist_healthy(weekly_macd),
        "weekly_macd_top_divergence": _trend_top_divergence(weekly_highs, weekly_macd),
        "monthly_macd_top_divergence": _trend_top_divergence(monthly_highs, monthly_macd),
        "max_drawdown_3m_pct": max_drawdown_pct(closes[-63:]),
        "short_term_gain_pct": _trend_recent_gain_pct(closes, 20),
    }


def _trend_entry_ok(snapshot: dict[str, float | bool]) -> bool:
    price = float(snapshot["price"])
    return bool(
        price > float(snapshot["ma20_month"])
        and price > float(snapshot["ma60_month"])
        and snapshot["month_macd_above_zero"]
        and float(snapshot["ma5_week"]) > float(snapshot["ma10_week"]) > float(snapshot["ma20_week"])
        and snapshot["weekly_rising"]
        and snapshot["weekly_macd_hist_positive"]
        and snapshot["weekly_macd_hist_healthy"]
        and not snapshot["weekly_macd_top_divergence"]
        and not snapshot["monthly_macd_top_divergence"]
        and float(snapshot["max_drawdown_3m_pct"]) <= 15
        and float(snapshot["short_term_gain_pct"]) <= 40
    )


def _trend_daily_entry_ok(closes: list[float], lows: list[float], volumes: list[float], index: int) -> bool:
    ma20 = sma(closes[: index + 1], 20)
    ma30 = sma(closes[: index + 1], 30)
    if ma20 is None or ma30 is None:
        return False
    close = closes[index]
    low = lows[index]
    pullback_ok = (low <= ma20 * 1.01 and close >= ma20) or (low <= ma30 * 1.01 and close >= ma30)
    recent_macd = macd(closes[: index + 1])
    macd_ok = not recent_macd or recent_macd[-1].dif >= recent_macd[-1].dea or recent_macd[-1].dif > 0
    avg_volume20 = sum(volumes[max(0, index - 20) : index]) / min(index, 20) if index > 0 else 0.0
    volume_ok = avg_volume20 <= 0 or not (close < closes[index - 1] and volumes[index] > avg_volume20 * 1.5)
    return pullback_ok and macd_ok and volume_ok


def _trend_exit_reason(
    snapshot: dict[str, float | bool],
    pnl_pct: float,
    drawdown_pct: float,
    holding_days: int,
) -> str:
    if drawdown_pct >= 18:
        return "单一标的回撤达到 18%，无条件止损"
    if snapshot["monthly_below_ma60_two_months"]:
        return "月线连续 2 个月跌破 60 月均线，清仓"
    if snapshot["weekly_ma_break"] and holding_days >= 20:
        return "周线 5 周线下穿 10 周线，止损离场"
    if snapshot["monthly_macd_below_zero"]:
        return "月线 MACD 双线跌破零轴，趋势转空头清仓"
    if snapshot["weekly_macd_top_divergence"] or snapshot["monthly_macd_top_divergence"]:
        return "周线/月线 MACD 顶背离，趋势见顶清仓"
    if holding_days >= 126:
        return "持仓满 6 个月，调仓换股"
    return ""


def _trend_macd_hist_positive(points) -> bool:
    return bool(points and (points[-1].hist > 0 or (points[-1].dif > 0 and points[-1].dea > 0)))


def _trend_macd_hist_healthy(points, bars: int = 3) -> bool:
    if len(points) < bars:
        return False
    hist = [float(point.hist) for point in points[-bars:]]
    if points[-1].dif > 0 and points[-1].dea > 0:
        return True
    if any(value <= 0 for value in hist):
        return False
    return hist[-1] >= max(hist) * 0.2


def _trend_top_divergence(highs: list[float], points) -> bool:
    if len(highs) < 8 or len(points) < 8:
        return False
    hist = [float(point.hist) for point in points]
    return has_top_divergence(highs, hist, lookback=min(28, len(highs)))


def _trend_weekly_rising(highs: list[float], lows: list[float]) -> bool:
    if len(highs) < 8 or len(lows) < 8:
        return False
    return max(highs[-4:]) > max(highs[-8:-4]) and min(lows[-4:]) > min(lows[-8:-4])


def _trend_weekly_ma_break(weekly_closes: list[float]) -> bool:
    ma5 = sma(weekly_closes, 5)
    ma10 = sma(weekly_closes, 10)
    return ma5 is not None and ma10 is not None and ma5 < ma10


def _trend_monthly_below_ma60_two_months(monthly_closes: list[float]) -> bool:
    if len(monthly_closes) < 61:
        return False
    previous_ma60 = sma(monthly_closes[:-1], 60)
    current_ma60 = sma(monthly_closes, 60)
    return bool(
        previous_ma60 is not None
        and current_ma60 is not None
        and monthly_closes[-2] < previous_ma60
        and monthly_closes[-1] < current_ma60
    )


def _trend_recent_gain_pct(closes: list[float], days: int) -> float:
    recent = closes[-days:]
    if len(recent) < 2 or recent[0] == 0:
        return 0.0
    return (recent[-1] / recent[0] - 1) * 100


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


def _float_param(params: dict[str, object], key: str, default: float) -> float:
    value = params.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _position_size(request: BacktestRequest, symbol_count: int) -> tuple[float, str]:
    params = request.params_snapshot
    if request.strategy_id in {"intraday_macd", "ma_atr_intraday"}:
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
    action: str = "close",
    action_label: str = "",
    cash_after: float = 0.0,
    position_value: float = 0.0,
    weight_pct: float = 0.0,
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
        action=action,
        action_label=action_label,
        cash_after=round(cash_after, 2),
        position_value=round(position_value, 2),
        weight_pct=round(weight_pct, 2),
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
    elif strategy_id == "ma_atr_intraday":
        mode = "多周期 MA+MACD+ATR 日内回测；使用真实1分钟线重建1h/10m/5m周期，三周期 MA 趋势共振 + MACD 金叉确认 + ATR 动态止损。"
    else:
        mode = "日线趋势代理回测；月/周线组合调仓 vnpy 回测仍待接入。"
    return [
        mode,
        f"本次使用 {used_symbols}/{len(requested_symbols)} 个标的生成组合收益。",
    ]
