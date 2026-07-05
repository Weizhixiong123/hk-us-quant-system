from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol, Sequence
from uuid import uuid4

from quant.live.clock import Market, is_trading_day, market_time, premarket_scan_time
from quant.live.data_provider import DefaultLiveDataProvider, LiveDataProvider
from quant.live.params import LiveParams
from quant.live.executor import execute_exit_order, execute_intraday_entry, execute_portfolio_entry
from quant.live.gateway import FutuLiveGateway, TigerLiveGateway
from quant.live.intraday import (
    IntradayPosition,
    build_premarket_watchlist,
    evaluate_intraday_entry_signal,
    evaluate_intraday_exit_signal,
    three_period_macd_momentum,
)
from quant.live.market_data import BarAggregator
from quant.live.risk import evaluate_live_order_risk
from quant.live.runtime_state import StrategyRuntimeState
from quant.live.scheduler import LiveScheduler, SchedulerAction
from quant.live.settings import load_live_settings
from quant.live.state import LiveGatewayState
from quant.live.store import DbPath, list_live_events, live_db_path_for_mode, record_live_event
from quant.live.translate import GatewayAccount, GatewayOrder, GatewayPosition, GatewayTick, GatewayTrade
from quant.live.trend import (
    TrendPosition,
    build_month_end_watchlist,
    evaluate_trend_entry_signal,
    evaluate_trend_exit_signal,
)
from quant.data.universe import SymbolInfo, all_symbols
from quant.screening.intraday_screener import IntradayCandidate


def _candidate_components_for(
    selected: list[str],
    candidates: Sequence[IntradayCandidate],
) -> dict[str, dict[str, float | None]]:
    """把被选标的的盘前 IntradyCandidate 字段映射成 score_components 子集。

    只取 runtime 这一刻**已知**的字段(prev_amplitude_pct / avg_turnover);
    需要日线 / 分钟线的维度留给 state.py 读时填 None。
    """
    by_sym = {c.symbol: c for c in candidates}
    out: dict[str, dict[str, float | None]] = {}
    for sym in selected:
        cand = by_sym.get(sym)
        out[sym] = {
            "prev_amplitude_pct": getattr(cand, "prev_amplitude_pct", None),
            "avg_turnover": getattr(cand, "avg_turnover", None),
        }
    return out


class RuntimeGateway(Protocol):
    def connect(self) -> None:
        ...

    def subscribe(self, symbols: list[str], exchange: str | None = None) -> None:
        ...

    def send_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        price: float,
        volume: float,
        exchange: str | None = None,
    ) -> str:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class RuntimeConfig:
    enabled: bool = False
    dry_run: bool = True
    broker: str = "futu"
    poll_interval_seconds: float = 2.0
    default_equity: float = 1_000_000.0
    max_daily_loss_pct: float = 3.0


class LiveRuntime:
    def __init__(
        self,
        live_state: LiveGatewayState,
        gateway: RuntimeGateway,
        scheduler: LiveScheduler,
        data_provider: LiveDataProvider,
        market_data: BarAggregator,
        runtime_state: StrategyRuntimeState | None = None,
        config: RuntimeConfig | None = None,
        db_path: DbPath | None = None,
        params: LiveParams | None = None,
        manual_intraday_symbols: Sequence[SymbolInfo] | None = None,
    ) -> None:
        self.live_state = live_state
        self.gateway = gateway
        self.scheduler = scheduler
        self.data_provider = data_provider
        self.market_data = market_data
        self.runtime_state = runtime_state or StrategyRuntimeState()
        self.config = config or RuntimeConfig()
        self.db_path = db_path
        self.params = params or LiveParams()
        self._task: asyncio.Task | None = None
        self._running = False
        self._seeded_day = None
        self._seeded_symbols: set[str] = set()
        self._premarket_catchups: set[tuple[Market, date]] = set()
        self._manual_intraday_symbols = (
            tuple(manual_intraday_symbols) if manual_intraday_symbols is not None else None
        )
        if self._manual_intraday_symbols is not None:
            self.runtime_state.intraday_watchlist = [item.symbol for item in self._manual_intraday_symbols]
        configured_symbols = [
            *getattr(self.data_provider, "symbols", ()),
            *getattr(self.data_provider, "intraday_symbols", ()),
            *(self._manual_intraday_symbols or ()),
        ]
        self._shortable_symbols = {
            item.symbol.upper() for item in (configured_symbols or all_symbols()) if item.shortable
        }

    async def start(self) -> None:
        if not self.config.enabled or self._running:
            return
        self.gateway.connect()
        subscription_symbols = self._subscription_symbols()
        self.gateway.subscribe(subscription_symbols)
        if self._manual_intraday_symbols is not None:
            self._seed_history(subscription_symbols)
            now = datetime.now(timezone.utc)
            for market in self.scheduler.markets:
                manual_infos = [item for item in self._manual_intraday_symbols if item.market == market]
                manual_symbols = [item.symbol for item in manual_infos]
                if manual_symbols:
                    self._record_intraday_selection(
                        market=market,
                        symbols=manual_symbols,
                        manual_symbols=manual_symbols,
                        auto_symbols=[],
                        candidates=[],
                        manual_infos=manual_infos,
                        at=now,
                    )
        self.runtime_state.load_entry_dates_from_events(
            list_live_events(kind="trade", db_path=self.db_path)
        )
        self._running = True
        self._record_log("runtime", "实盘运行时已启动")
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.gateway.close()

    async def _loop(self) -> None:
        while self._running:
            try:
                # run_once 是同步阻塞(含 data_provider 网络拉取/磁盘 IO),放线程池执行,
                # 避免阻塞 asyncio event loop 导致所有 HTTP 请求 pending。
                await asyncio.to_thread(self.run_once, datetime.now(timezone.utc))
            except Exception as exc:
                self._record_log("runtime", f"运行时循环异常：{exc}")
            await asyncio.sleep(self.config.poll_interval_seconds)

    def run_once(self, at: datetime) -> None:
        snapshot = self.live_state.snapshot()
        self.runtime_state.reset_for_day(at.date())
        if self._seeded_day != at.date():
            self._seeded_day = at.date()
            self._seeded_symbols.clear()
        self.market_data.ingest_ticks(snapshot.get("ticks", []))
        self._observe_account(snapshot, at)
        self.runtime_state.persist_gateway_snapshot(snapshot, at, self.db_path)
        self._catch_up_premarket_scan(at)
        for action in self.scheduler.due_actions(at):
            self.handle_action(action, at)

    def _observe_account(self, snapshot: dict[str, Any], at: datetime) -> None:
        account = snapshot.get("account")
        if account is None:
            return
        balance = float(account.balance)
        self.runtime_state.observe_account_equity(balance, at.date())
        self.runtime_state.trip_halt_if_breached(balance, self.params.intraday.max_daily_loss_pct)
        baseline = self.runtime_state.day_start_equity or balance
        self.live_state.update_account(replace(account, day_pnl=round(balance - baseline, 2)))

    def handle_action(self, action: SchedulerAction, at: datetime) -> None:
        if action.hook == "intraday_premarket_scan":
            self._run_intraday_premarket_scan(action.market, at)
        elif action.hook == "intraday_3m_signal":
            if self._manual_intraday_symbols is None:
                self._run_intraday_premarket_scan(action.market, at)
            self._run_intraday_entries(action.market, at)
        elif action.hook == "intraday_3m_exit":
            self._run_intraday_exits(action.market, at)
        elif action.hook == "intraday_force_close":
            self._force_close_intraday_positions(action.market, at)
        elif action.hook == "portfolio_month_end_scan":
            self._run_portfolio_month_end_scan(at)
        elif action.hook == "portfolio_daily_review":
            self._run_portfolio_daily_review(action.market, at)

    def _run_intraday_premarket_scan(self, market: Market, at: datetime) -> None:
        manual_infos = [
            item
            for item in (self._manual_intraday_symbols or ())
            if item.market == market
        ]
        manual_symbols = [item.symbol for item in manual_infos]

        market_loader = getattr(self.data_provider, "intraday_candidates_for_market", None)
        all_candidates = market_loader(market) if market_loader else self.data_provider.intraday_candidates()
        candidates = [item for item in all_candidates if _market_from_symbol(item.symbol) == market]
        auto_symbols = build_premarket_watchlist(
            candidates,
            min_turnover=self.params.intraday.min_turnover,
            min_amplitude_pct=self.params.intraday.min_amplitude_pct,
            max_amplitude_pct=self.params.intraday.max_amplitude_pct,
            min_price=self.params.intraday.min_price,
            min_turnover_rate=self.params.intraday.min_turnover_rate,
        )
        symbols = _merge_unique([*manual_symbols, *auto_symbols])
        self.runtime_state.intraday_watchlist = _replace_market_symbols(
            self.runtime_state.intraday_watchlist,
            market,
            symbols,
        )
        if symbols:
            self.gateway.subscribe(symbols)
            self._seed_history(symbols)
        self._record_intraday_selection(
            market=market,
            symbols=symbols,
            manual_symbols=manual_symbols,
            auto_symbols=auto_symbols,
            candidates=candidates,
            manual_infos=manual_infos,
            at=at,
        )

    def _record_intraday_selection(
        self,
        *,
        market: Market,
        symbols: list[str],
        manual_symbols: list[str],
        auto_symbols: list[str],
        candidates: list[IntradayCandidate],
        manual_infos: list[SymbolInfo],
        at: datetime,
    ) -> None:
        names = {item.symbol: item.name for item in manual_infos}
        mode = _combined_selection_mode(manual_symbols, auto_symbols)
        payload: dict[str, Any] = {
            "market": market,
            "symbols": symbols,
            "candidate_count": len(candidates),
            "selection_mode": mode,
            "manual_symbols": manual_symbols,
            "auto_symbols": auto_symbols,
            "names": names,
        }
        if auto_symbols:
            payload["score_components"] = _candidate_components_for(auto_symbols, candidates)
        record_live_event(
            kind="selection",
            strategy_id="intraday_macd",
            created_at=at,
            payload=payload,
            db_path=self.db_path,
        )

    def _catch_up_premarket_scan(self, at: datetime) -> None:
        for market in self.scheduler.markets:
            if _has_market_symbols(self.runtime_state.intraday_watchlist, market):
                continue
            local = market_time(at, market)
            day = local.date()
            key = (market, day)
            if key in self._premarket_catchups or not is_trading_day(day, market):
                continue
            scan_at = premarket_scan_time(day, market)
            catchup_until = scan_at + timedelta(minutes=60)
            if scan_at < local < catchup_until:
                self._premarket_catchups.add(key)
                self._run_intraday_premarket_scan(market, at)
                return

    def _run_intraday_entries(self, market: Market, at: datetime) -> None:
        snapshot = self.live_state.snapshot()
        for symbol in self.runtime_state.intraday_watchlist:
            if _market_from_symbol(symbol) != market or _has_position(snapshot, symbol):
                continue
            bars3 = self.market_data.interval_bars(symbol, 3, limit=80)
            bars5 = self.market_data.interval_bars(symbol, 5, limit=80)
            bars15 = self.market_data.interval_bars(symbol, 15, limit=80)
            minimum_bars = self.params.intraday.slow_ema + 1
            if len(bars3) < minimum_bars or len(bars5) < minimum_bars or len(bars15) < minimum_bars:
                continue
            price = self.market_data.latest_price(symbol) or bars5[-1].close
            signal = evaluate_intraday_entry_signal(
                symbol=symbol,
                market=market,
                at=at,
                closes_15m=[bar.close for bar in bars15],
                closes_5m=[bar.close for bar in bars5],
                closes_3m=[bar.close for bar in bars3],
                fast_ema=self.params.intraday.fast_ema,
                slow_ema=self.params.intraday.slow_ema,
                signal_ema=self.params.intraday.signal_ema,
                open_after_minutes=self.params.intraday.open_after_minutes,
                close_before_minutes=self.params.intraday.close_before_minutes,
            )
            if signal.action not in ("enter_long", "enter_short"):
                continue
            is_short = signal.action == "enter_short"
            risk = self._live_risk(symbol, market, "open", at, is_short=is_short)
            if not risk.allowed:
                self._record_signal("intraday_macd", symbol, risk.reasons, at)
                continue
            equity = _account_equity(snapshot, self.config.default_equity)
            result = execute_intraday_entry(
                gateway=self.gateway, symbol=symbol, price=price,
                total_equity=equity,
                current_symbols=_current_symbols(snapshot),
                intraday_symbols=tuple(self.runtime_state.intraday_open_symbols),
                stopped_symbols_today=tuple(self.runtime_state.stopped_symbols_today),
                daily_loss_pct=self.runtime_state.daily_loss_pct(equity),
                pdt_trades_remaining=self.runtime_state.pdt_remaining(at.date()) if market == "US" else None,
                is_short=is_short,
                shortable=self._is_shortable(symbol),
                position_fraction_pct=self.params.intraday.position_fraction_pct,
                max_positions=self.params.intraday.max_positions,
                max_daily_loss_pct=self.params.intraday.max_daily_loss_pct,
            )
            self.runtime_state.record_order_result(result.submitted, result.reasons)
            if result.submitted:
                self.runtime_state.mark_intraday_open(symbol)
            self._record_signal("intraday_macd", symbol, result.reasons, at, submitted=result.submitted)

    def _run_intraday_exits(self, market: Market, at: datetime) -> None:
        snapshot = self.live_state.snapshot()
        for position in snapshot.get("positions", []):
            if _market_from_symbol(position.symbol) != market:
                continue
            if not self.runtime_state.owns_intraday_symbol(position.symbol):
                continue
            price = self.market_data.latest_price(position.symbol) or float(position.price)
            signal = evaluate_intraday_exit_signal(
                position=IntradayPosition(
                    symbol=position.symbol,
                    side=_position_side(position.direction),
                    quantity=int(position.volume),
                    avg_price=float(position.price),
                ),
                momentum=self._three_period_momentum(position.symbol),
            )
            if signal.action == "wait":
                continue
            risk = self._live_risk(position.symbol, market, "close", at)
            if not risk.allowed:
                self._record_signal("intraday_macd", position.symbol, risk.reasons, at)
                continue
            result = execute_exit_order(
                gateway=self.gateway,
                symbol=position.symbol,
                price=price,
                quantity=signal.quantity,
                side=_position_side(position.direction),
                reason=signal.reasons[0],
            )
            self.runtime_state.record_order_result(result.submitted, result.reasons)
            if result.submitted and signal.action == "exit_all":
                self.runtime_state.mark_intraday_closed(position.symbol)
            self._record_signal("intraday_macd", position.symbol, result.reasons, at, submitted=result.submitted)

    def _force_close_intraday_positions(self, market: Market, at: datetime) -> None:
        snapshot = self.live_state.snapshot()
        for position in snapshot.get("positions", []):
            if _market_from_symbol(position.symbol) != market:
                continue
            if not self.runtime_state.owns_intraday_symbol(position.symbol):
                continue
            price = self.market_data.latest_price(position.symbol) or float(position.price)
            result = execute_exit_order(
                gateway=self.gateway,
                symbol=position.symbol,
                price=price,
                quantity=int(position.volume),
                side=_position_side(position.direction),
                reason="尾盘强制清仓",
            )
            self.runtime_state.record_order_result(result.submitted, result.reasons)
            if result.submitted:
                self.runtime_state.mark_intraday_closed(position.symbol)
            self._record_signal(
                "intraday_macd",
                position.symbol,
                result.reasons,
                at,
                submitted=result.submitted,
            )

    def _three_period_momentum(self, symbol: str) -> str:
        """三周期(15m/5m/3m)MACD 柱方向:全升 rising / 全降 falling / 否则 mixed。"""
        return three_period_macd_momentum(
            closes_15m=[bar.close for bar in self.market_data.interval_bars(symbol, 15, limit=80)],
            closes_5m=[bar.close for bar in self.market_data.interval_bars(symbol, 5, limit=80)],
            closes_3m=[bar.close for bar in self.market_data.interval_bars(symbol, 3, limit=80)],
            fast_ema=self.params.intraday.fast_ema,
            slow_ema=self.params.intraday.slow_ema,
            signal_ema=self.params.intraday.signal_ema,
        )

    def _run_portfolio_month_end_scan(self, at: datetime) -> None:
        rows = self.data_provider.portfolio_rows()
        symbols = build_month_end_watchlist(rows)
        self.runtime_state.portfolio_watchlist = symbols
        if symbols:
            self.gateway.subscribe(symbols)
            self._seed_history(symbols)
        record_live_event(
            kind="selection",
            strategy_id="trend_portfolio",
            created_at=at,
            payload={"symbols": symbols, "candidate_count": len(rows)},
            db_path=self.db_path,
        )

    def _run_portfolio_daily_review(self, market: Market, at: datetime) -> None:
        self._run_portfolio_exits(market, at)
        self._run_portfolio_entries(market, at)

    def _run_portfolio_entries(self, market: Market, at: datetime) -> None:
        snapshot = self.live_state.snapshot()
        position_values = _position_values(snapshot)
        for symbol in self.runtime_state.portfolio_watchlist:
            if _market_from_symbol(symbol) != market:
                continue
            timing = self.data_provider.daily_timing(symbol, market)
            if timing is None:
                continue
            stage = self.runtime_state.next_portfolio_stage(symbol)
            signal = evaluate_trend_entry_signal(symbol, timing, stage=stage, hot_gain_block_pct=self.params.portfolio.hot_gain_block_pct)
            if signal.action == "wait" or signal.stage is None:
                continue
            risk = self._live_risk(symbol, market, "open", at)
            if not risk.allowed:
                self._record_signal("trend_portfolio", symbol, risk.reasons, at)
                continue
            result = execute_portfolio_entry(
                gateway=self.gateway,
                symbol=symbol,
                price=timing.close,
                total_equity=_account_equity(snapshot, self.config.default_equity),
                current_position_values=position_values,
                stage=signal.stage,
                pullback_confirmed=signal.pullback_confirmed,
                single_position_cap_pct=self.params.portfolio.single_position_cap_pct,
                target_positions_max=self.params.portfolio.target_positions_max,
                first_entry_fraction_pct=self.params.portfolio.first_entry_fraction_pct,
            )
            self.runtime_state.record_order_result(result.submitted, result.reasons)
            if result.submitted:
                self.runtime_state.mark_portfolio_entry_submitted(symbol, signal.stage)
                if signal.stage == "first":
                    self.runtime_state.record_portfolio_entry_date(symbol, at.date())
            self._record_signal("trend_portfolio", symbol, result.reasons, at, submitted=result.submitted)

    def _run_portfolio_exits(self, market: Market, at: datetime) -> None:
        snapshot = self.live_state.snapshot()
        for position in snapshot.get("positions", []):
            if _market_from_symbol(position.symbol) != market or self.runtime_state.owns_intraday_symbol(position.symbol):
                continue
            context = self.data_provider.trend_exit_context(position.symbol, market)
            price = self.market_data.latest_price(position.symbol) or float(position.price)
            signal = evaluate_trend_exit_signal(
                TrendPosition(
                    symbol=position.symbol,
                    quantity=int(position.volume),
                    avg_price=float(position.price),
                    holding_days=self.runtime_state.holding_days(position.symbol, at.date()),
                    take_profit_done=self.runtime_state.trend_half_done(position.symbol),
                ),
                current_price=price,
                **asdict(context),
                max_symbol_drawdown_pct=self.params.portfolio.max_symbol_drawdown_pct,
                take_profit_pct=self.params.portfolio.take_profit_pct,
                rebalance_months=self.params.portfolio.rebalance_months,
            )
            if signal.action == "wait":
                continue
            risk = self._live_risk(position.symbol, market, "close", at)
            if not risk.allowed:
                self._record_signal("trend_portfolio", position.symbol, risk.reasons, at)
                continue
            result = execute_exit_order(
                gateway=self.gateway,
                symbol=position.symbol,
                price=price,
                quantity=signal.quantity,
                side=_position_side(position.direction),
                reason=signal.reasons[0],
            )
            self.runtime_state.record_order_result(result.submitted, result.reasons)
            if result.submitted and signal.action == "exit_half":
                self.runtime_state.mark_trend_half_taken(position.symbol)
            self._record_signal("trend_portfolio", position.symbol, result.reasons, at, submitted=result.submitted)

    def _live_risk(self, symbol: str, market: Market, purpose: str, at: datetime, is_short: bool = False):
        snapshot = self.live_state.snapshot()
        balance = _account_equity(snapshot, self.config.default_equity)
        return evaluate_live_order_risk(
            symbol=symbol,
            market=market,
            purpose=purpose,
            gateway_connected=bool(snapshot.get("connected")),
            daily_loss_pct=self.runtime_state.daily_loss_pct(balance),
            stopped_symbols_today=tuple(self.runtime_state.stopped_symbols_today),
            pdt_trades_remaining=self.runtime_state.pdt_remaining(at.date()) if market == "US" else None,
            consecutive_order_failures=self.runtime_state.consecutive_order_failures,
            account_halted=self.runtime_state.is_halted(),
            is_short=is_short,
            shortable=self._is_shortable(symbol),
        )

    def _is_shortable(self, symbol: str) -> bool:
        return symbol.upper() in self._shortable_symbols

    def _subscription_symbols(self) -> list[str]:
        if self._manual_intraday_symbols is not None:
            return [item.symbol for item in self._manual_intraday_symbols]
        symbols = list({
            *(self.runtime_state.intraday_watchlist or []),
            *(self.runtime_state.portfolio_watchlist or []),
        })
        if symbols:
            return symbols
        provider_symbols = getattr(self.data_provider, "symbols", [])
        return [item.symbol for item in provider_symbols]

    def _seed_history(self, symbols: list[str]) -> None:
        query = getattr(self.gateway, "query_history_minute", None)
        if query is None:
            return
        for symbol in symbols:
            if symbol in self._seeded_symbols:
                continue
            try:
                bars = query(symbol)
                self.market_data.seed_minute_bars(symbol, bars)
            except Exception as exc:
                self._record_log("runtime", f"{symbol} 历史补种失败：{exc}")
                continue
            self._seeded_symbols.add(symbol)

    def _record_signal(
        self,
        strategy_id: str,
        symbol: str,
        reasons: tuple[str, ...],
        at: datetime,
        submitted: bool = False,
    ) -> None:
        components = self._build_signal_score_components(strategy_id, symbol)
        payload: dict[str, Any] = {
            "submitted": submitted,
            "reasons": list(reasons),
        }
        if components:
            payload["score_components"] = components
        record_live_event(
            kind="signal",
            strategy_id=strategy_id,
            symbol=symbol,
            created_at=at,
            payload=payload,
            db_path=self.db_path,
        )

    def _build_signal_score_components(
        self, strategy_id: str, symbol: str
    ) -> dict[str, float | None]:
        """signal 路径下计算 consistency(3 周期 MACD 一致度)。

        仅在 BarAggregator 累积了 ≥27 根 close 的情况下重算;否则留空,
        让 state.py 用 1.0 默认值(信号触发即视为当时满足一致性)。
        """
        if strategy_id != "intraday_macd":
            return {}
        try:
            from app.strategies.macd_intraday import build_intraday_decision

            bars15 = self.market_data.interval_bars(symbol, 15, limit=80)
            bars5 = self.market_data.interval_bars(symbol, 5, limit=80)
            bars3 = self.market_data.interval_bars(symbol, 3, limit=80)
            minimum_bars = self.params.intraday.slow_ema + 1
            if len(bars15) >= minimum_bars and len(bars5) >= minimum_bars and len(bars3) >= minimum_bars:
                decision = build_intraday_decision(
                    closes_15m=[b.close for b in bars15],
                    closes_5m=[b.close for b in bars5],
                    closes_3m=[b.close for b in bars3],
                    side="long",
                    within_trade_window=True,
                    fast_period=self.params.intraday.fast_ema,
                    slow_period=self.params.intraday.slow_ema,
                    signal_period=self.params.intraday.signal_ema,
                )
                return {"consistency": float(decision.confidence)}
        except Exception:
            return {}
        return {}

    def _record_log(self, source: str, message: str) -> None:
        record_live_event(
            kind="log",
            strategy_id=source,
            created_at=datetime.now(timezone.utc),
            payload={"message": message},
            db_path=self.db_path,
        )


class DryRunGateway:
    def __init__(self, state: LiveGatewayState, initial_cash: float = 1_000_000.0) -> None:
        self.state = state
        self.subscribed: list[str] = []
        self._positions: dict[tuple[str, str], GatewayPosition] = {}
        self._cash = float(initial_cash)
        self._last_prices: dict[str, float] = {}

    def connect(self) -> None:
        self.state.set_connected(True, "干跑网关已连接，仅记录不触达券商")
        self._publish_account()

    def subscribe(self, symbols: list[str], exchange: str | None = None) -> None:
        for symbol in symbols:
            if symbol not in self.subscribed:
                self.subscribed.append(symbol)

    def send_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        price: float,
        volume: float,
        exchange: str | None = None,
    ) -> str:
        order_id = f"DRY-{uuid4().hex[:8].upper()}"
        self.state.update_order(GatewayOrder(order_id, symbol, direction, offset, price, volume, volume, "全部成交"))
        self.state.update_trade(
            GatewayTrade(
                trade_id=f"T-{order_id}",
                order_id=order_id,
                symbol=symbol,
                direction=direction,
                offset=offset,
                price=price,
                volume=volume,
                time=datetime.now(timezone.utc).isoformat(),
            )
        )
        self._update_position(symbol, direction, offset, price, volume)
        # 现金按买卖方向增减：卖出("空")回笼现金，买入("多")占用现金
        if "空" in direction:
            self._cash += price * volume
        else:
            self._cash -= price * volume
        self._last_prices[symbol] = price
        self.state.update_tick(
            GatewayTick(
                symbol=symbol,
                last_price=price,
                volume=volume,
                time=datetime.now(timezone.utc).isoformat(),
            )
        )
        self._publish_account()
        return order_id

    def close(self) -> None:
        self.state.set_connected(False, "干跑网关已关闭")

    def _update_position(self, symbol: str, direction: str, offset: str, price: float, volume: float) -> None:
        position_direction = direction if not _is_close(offset) else ("多" if "空" in direction else "空")
        key = (symbol, position_direction)
        current = self._positions.get(key)
        if not _is_close(offset):
            old_volume = current.volume if current else 0.0
            old_value = old_volume * (current.price if current else 0.0)
            new_volume = old_volume + volume
            avg_price = (old_value + volume * price) / new_volume if new_volume else price
            position = GatewayPosition(symbol, position_direction, new_volume, avg_price, 0.0)
        else:
            old_volume = current.volume if current else 0.0
            new_volume = max(old_volume - volume, 0.0)
            position = GatewayPosition(symbol, position_direction, new_volume, current.price if current else price, 0.0)
        self._positions[key] = position
        self.state.update_position(position)

    def _publish_account(self) -> None:
        holdings_value = sum(
            pos.volume * self._last_prices.get(pos.symbol, pos.price)
            for pos in self._positions.values()
        )
        self.state.update_account(
            GatewayAccount(
                account_id="DRY-RUN",
                balance=round(self._cash + holdings_value, 2),
                available=round(self._cash, 2),
                frozen=round(holdings_value, 2),
            )
        )


def build_live_runtime_from_env(live_state: LiveGatewayState, params: LiveParams | None = None) -> LiveRuntime:
    all_settings = load_live_settings()
    settings = all_settings.get("runtime", {})
    intraday_params = all_settings.get("intraday_params", {})

    config = RuntimeConfig(
        enabled=_env_bool("LIVE_RUNTIME_ENABLED", bool(settings.get("enabled", False))),
        dry_run=_env_bool("LIVE_RUNTIME_DRY_RUN", bool(settings.get("dry_run", True))),
        broker=_broker_from_env(str(settings.get("broker", "futu"))),
        poll_interval_seconds=float(
            os.getenv(
                "LIVE_RUNTIME_POLL_SECONDS",
                str(settings.get("poll_interval_seconds", "2")),
            )
        ),
        default_equity=float(
            os.getenv(
                "LIVE_RUNTIME_DEFAULT_EQUITY",
                str(settings.get("default_equity", "1000000")),
            )
        ),
    )
    market_data = BarAggregator()
    runtime_markets = _runtime_markets(all_settings, config.broker)
    symbols = [item for item in all_symbols() if item.market in runtime_markets]
    manual_symbols = _manual_intraday_symbols(all_settings, runtime_markets)
    manual_mode = all_settings.get("intraday_universe", {}).get("selection_mode") == "manual"
    universe_source = None
    intraday_candidate_source = None
    if config.broker == "futu":
        from quant.data.futu_market_scanner import FutuMarketScanner
        from quant.live.config import load_futu_config

        futu_config = load_futu_config()
        scanner = FutuMarketScanner(futu_config.host, futu_config.port, runtime_markets)
        universe_source = scanner.trend_symbols
        intraday_candidate_source = scanner.intraday_candidates
    data_provider = DefaultLiveDataProvider(
        market_data,
        symbols=symbols,
        intraday_symbols=[*manual_symbols, *symbols],
        universe_source=universe_source,
        intraday_candidate_source=intraday_candidate_source,
        markets=runtime_markets,
    )
    gateway: RuntimeGateway
    if config.dry_run:
        gateway = DryRunGateway(live_state, initial_cash=config.default_equity)
    elif config.broker == "tiger":
        from quant.live.config import load_tiger_config

        gateway = TigerLiveGateway(load_tiger_config(), live_state)
    else:
        from quant.live.config import load_futu_config

        gateway = FutuLiveGateway(load_futu_config(), live_state)

    # 从 intraday_params 读取筛选参数并合并到 params
    effective_params = params or LiveParams()
    if intraday_params:
        effective_params.update("intraday_macd", intraday_params)

    return LiveRuntime(
        live_state=live_state,
        gateway=gateway,
        scheduler=LiveScheduler(
            markets=runtime_markets,
            open_after_minutes=intraday_params.get("open_after_minutes", 30),
            close_before_minutes=intraday_params.get("close_before_minutes", 90),
        ),
        data_provider=data_provider,
        market_data=market_data,
        config=config,
        params=effective_params,
        db_path=live_db_path_for_mode(all_settings),
        manual_intraday_symbols=manual_symbols if manual_mode else None,
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _broker_from_env(default: str = "futu") -> str:
    broker = os.getenv("LIVE_RUNTIME_BROKER", default).strip().lower()
    if broker not in {"futu", "tiger"}:
        raise ValueError("LIVE_RUNTIME_BROKER must be futu or tiger")
    return broker


def _runtime_markets(settings: dict[str, Any], broker: str) -> tuple[Market, ...]:
    env_value = os.getenv("LIVE_RUNTIME_MARKETS")
    raw_items: object = env_value.split(",") if env_value else settings.get(broker, {}).get("markets", ["HK", "US"])
    if not isinstance(raw_items, list | tuple):
        raw_items = [raw_items]

    markets: list[Market] = []
    for item in raw_items:
        market = str(item).strip().upper()
        if market in {"HK", "US"} and market not in markets:
            markets.append(market)  # type: ignore[arg-type]
    return tuple(markets or ["HK"])  # type: ignore[return-value]


def _manual_intraday_symbols(
    settings: dict[str, Any],
    runtime_markets: Sequence[Market],
) -> list[SymbolInfo]:
    rows = settings.get("intraday_universe", {}).get("manual_symbols", [])
    return [
        SymbolInfo(
            symbol=str(item["symbol"]),
            name=str(item.get("name") or item["symbol"]),
            market=str(item["market"]),  # type: ignore[arg-type]
            shortable=bool(item.get("shortable", False)),
        )
        for item in rows
        if isinstance(item, dict) and item.get("market") in runtime_markets
    ]


def _account_equity(snapshot: dict[str, Any], default: float) -> float:
    account = snapshot.get("account")
    return float(account.balance) if account is not None and account.balance > 0 else default


def _current_symbols(snapshot: dict[str, Any]) -> list[str]:
    return [position.symbol for position in snapshot.get("positions", []) if position.volume > 0]


def _position_values(snapshot: dict[str, Any]) -> dict[str, float]:
    return {
        position.symbol: float(position.volume) * float(position.price)
        for position in snapshot.get("positions", [])
        if position.volume > 0
    }


def _has_position(snapshot: dict[str, Any], symbol: str) -> bool:
    normalized = symbol.upper()
    return any(position.symbol.upper() == normalized and position.volume > 0 for position in snapshot.get("positions", []))


def _position_side(direction: str) -> str:
    return "short" if "空" in direction or "SHORT" in direction.upper() else "long"


def _market_from_symbol(symbol: str) -> Market:
    value = symbol.upper()
    return "HK" if value.endswith(".HK") or value.startswith("HK.") or value.isdigit() else "US"


def _has_market_symbols(symbols: list[str], market: Market) -> bool:
    return any(_market_from_symbol(symbol) == market for symbol in symbols)


def _replace_market_symbols(existing: list[str], market: Market, symbols: list[str]) -> list[str]:
    kept = [symbol for symbol in existing if _market_from_symbol(symbol) != market]
    return _merge_unique([*kept, *symbols])


def _merge_unique(symbols: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        key = symbol.upper()
        if not symbol or key in seen:
            continue
        seen.add(key)
        merged.append(symbol)
    return merged


def _combined_selection_mode(manual_symbols: list[str], auto_symbols: list[str]) -> str:
    if manual_symbols and auto_symbols:
        return "manual+auto"
    if manual_symbols:
        return "manual"
    return "auto"


def _is_close(offset: str) -> bool:
    return "平" in offset or "CLOSE" in offset.upper()
