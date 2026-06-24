from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from quant.live.clock import Market
from quant.live.data_provider import DefaultLiveDataProvider, LiveDataProvider
from quant.live.executor import execute_exit_order, execute_intraday_entry, execute_portfolio_entry
from quant.live.gateway import FutuLiveGateway
from quant.live.intraday import (
    IntradayPosition,
    build_premarket_watchlist,
    evaluate_intraday_entry_signal,
    evaluate_intraday_exit_signal,
)
from quant.live.market_data import BarAggregator
from quant.live.risk import evaluate_live_order_risk
from quant.live.runtime_state import StrategyRuntimeState
from quant.live.scheduler import LiveScheduler, SchedulerAction
from quant.live.state import LiveGatewayState
from quant.live.store import DbPath, record_live_event
from quant.live.translate import GatewayOrder, GatewayPosition, GatewayTick, GatewayTrade
from quant.live.trend import (
    TrendPosition,
    build_month_end_watchlist,
    evaluate_trend_entry_signal,
    evaluate_trend_exit_signal,
)
from quant.indicators.macd import has_bearish_cross, has_bullish_cross, macd


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
    ) -> None:
        self.live_state = live_state
        self.gateway = gateway
        self.scheduler = scheduler
        self.data_provider = data_provider
        self.market_data = market_data
        self.runtime_state = runtime_state or StrategyRuntimeState()
        self.config = config or RuntimeConfig()
        self.db_path = db_path
        self._task: asyncio.Task | None = None
        self._running = False
        self._seeded_day = None
        self._seeded_symbols: set[str] = set()

    async def start(self) -> None:
        if not self.config.enabled or self._running:
            return
        self.gateway.connect()
        self.gateway.subscribe(self._subscription_symbols())
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
                self.run_once(datetime.now(timezone.utc))
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
        for action in self.scheduler.due_actions(at):
            self.handle_action(action, at)

    def _observe_account(self, snapshot: dict[str, Any], at: datetime) -> None:
        account = snapshot.get("account")
        if account is None:
            return
        self.runtime_state.observe_account_equity(float(account.balance), at.date())
        self.runtime_state.trip_halt_if_breached(float(account.balance), self.config.max_daily_loss_pct)

    def handle_action(self, action: SchedulerAction, at: datetime) -> None:
        if action.hook == "intraday_premarket_scan":
            self._run_intraday_premarket_scan(at)
        elif action.hook == "intraday_15m_signal":
            self._run_intraday_entries(action.market, at)
            self._run_intraday_exits(action.market, at)
        elif action.hook == "intraday_force_close":
            self._run_intraday_exits(action.market, at, force=True)
        elif action.hook == "portfolio_month_end_scan":
            self._run_portfolio_month_end_scan(at)
        elif action.hook == "portfolio_daily_review":
            self._run_portfolio_daily_review(action.market, at)

    def _run_intraday_premarket_scan(self, at: datetime) -> None:
        candidates = self.data_provider.intraday_candidates()
        symbols = build_premarket_watchlist(candidates)
        self.runtime_state.intraday_watchlist = symbols
        if symbols:
            self.gateway.subscribe(symbols)
            self._seed_history(symbols)
        record_live_event(
            kind="selection",
            strategy_id="intraday_macd",
            created_at=at,
            payload={"symbols": symbols, "candidate_count": len(candidates)},
            db_path=self.db_path,
        )

    def _run_intraday_entries(self, market: Market, at: datetime) -> None:
        snapshot = self.live_state.snapshot()
        for symbol in self.runtime_state.intraday_watchlist:
            if _market_from_symbol(symbol) != market or _has_position(snapshot, symbol):
                continue
            bars5 = self.market_data.interval_bars(symbol, 5, limit=80)
            bars15 = self.market_data.interval_bars(symbol, 15, limit=80)
            if len(bars5) < 26 or len(bars15) < 26:
                continue
            price = self.market_data.latest_price(symbol) or bars5[-1].close
            closes15 = [bar.close for bar in bars15]
            signal = evaluate_intraday_entry_signal(
                symbol=symbol,
                market=market,
                at=at,
                closes_15m=closes15,
                lows_15m=[bar.low for bar in bars15],
                highs_15m=[bar.high for bar in bars15],
                closes_5m=[bar.close for bar in bars5],
                current_price=price,
                ma5_15m=sum(closes15[-5:]) / 5,
            )
            if signal.action != "enter_long":
                continue
            risk = self._live_risk(symbol, market, "open", at)
            if not risk.allowed:
                self._record_signal("intraday_macd", symbol, risk.reasons, at)
                continue
            result = execute_intraday_entry(
                gateway=self.gateway,
                symbol=symbol,
                price=price,
                total_equity=_account_equity(snapshot, self.config.default_equity),
                current_symbols=_current_symbols(snapshot),
                stopped_symbols_today=tuple(self.runtime_state.stopped_symbols_today),
                daily_loss_pct=self.runtime_state.daily_loss_pct(_account_equity(snapshot, self.config.default_equity)),
                pdt_trades_remaining=self.runtime_state.pdt_remaining(at.date()) if market == "US" else None,
            )
            self.runtime_state.record_order_result(result.submitted, result.reasons)
            if result.submitted:
                self.runtime_state.mark_intraday_open(symbol)
            self._record_signal("intraday_macd", symbol, result.reasons, at, submitted=result.submitted)

    def _run_intraday_exits(self, market: Market, at: datetime, force: bool = False) -> None:
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
                    first_take_profit_done=self.runtime_state.intraday_half_done(position.symbol),
                ),
                market=market,
                at=at,
                current_price=price,
                reverse_cross=self._reverse_cross(position.symbol, _position_side(position.direction)),
            )
            if force and signal.action == "wait":
                signal = evaluate_intraday_exit_signal(
                    IntradayPosition(position.symbol, _position_side(position.direction), int(position.volume), float(position.price)),
                    market,
                    at,
                    price,
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
            if result.submitted and signal.action == "exit_half":
                self.runtime_state.mark_intraday_half_taken(position.symbol)
            if result.submitted and signal.action == "exit_all":
                self.runtime_state.mark_intraday_closed(position.symbol)
            if result.submitted and signal.stopped_today:
                self.runtime_state.mark_stopped(position.symbol)
            self._record_signal("intraday_macd", position.symbol, result.reasons, at, submitted=result.submitted)

    def _reverse_cross(self, symbol: str, side: str) -> bool:
        bars15 = self.market_data.interval_bars(symbol, 15, limit=80)
        points = macd([bar.close for bar in bars15])
        if len(points) < 2:
            return False
        return has_bearish_cross(points) if side == "long" else has_bullish_cross(points)

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
            signal = evaluate_trend_entry_signal(symbol, timing, stage=stage)
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
            )
            self.runtime_state.record_order_result(result.submitted, result.reasons)
            if result.submitted:
                self.runtime_state.mark_portfolio_entry_submitted(symbol, signal.stage)
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
                    holding_days=0,
                    take_profit_done=self.runtime_state.trend_half_done(position.symbol),
                ),
                current_price=price,
                **asdict(context),
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

    def _live_risk(self, symbol: str, market: Market, purpose: str, at: datetime):
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
        )

    def _subscription_symbols(self) -> list[str]:
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
        record_live_event(
            kind="signal",
            strategy_id=strategy_id,
            symbol=symbol,
            created_at=at,
            payload={"submitted": submitted, "reasons": list(reasons)},
            db_path=self.db_path,
        )

    def _record_log(self, source: str, message: str) -> None:
        record_live_event(
            kind="log",
            strategy_id=source,
            created_at=datetime.now(timezone.utc),
            payload={"message": message},
            db_path=self.db_path,
        )


class DryRunGateway:
    def __init__(self, state: LiveGatewayState) -> None:
        self.state = state
        self.subscribed: list[str] = []
        self._positions: dict[tuple[str, str], GatewayPosition] = {}

    def connect(self) -> None:
        self.state.set_connected(True, "DRY RUN 网关已连接，仅记录不触达券商")

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
        return order_id

    def close(self) -> None:
        self.state.set_connected(False, "DRY RUN 网关已关闭")

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


def build_live_runtime_from_env(live_state: LiveGatewayState) -> LiveRuntime:
    config = RuntimeConfig(
        enabled=_env_bool("LIVE_RUNTIME_ENABLED", False),
        dry_run=_env_bool("LIVE_RUNTIME_DRY_RUN", True),
        poll_interval_seconds=float(os.getenv("LIVE_RUNTIME_POLL_SECONDS", "2")),
        default_equity=float(os.getenv("LIVE_RUNTIME_DEFAULT_EQUITY", "1000000")),
    )
    market_data = BarAggregator()
    data_provider = DefaultLiveDataProvider(market_data)
    gateway: RuntimeGateway
    if config.dry_run:
        gateway = DryRunGateway(live_state)
    else:
        from quant.live.config import load_futu_config

        gateway = FutuLiveGateway(load_futu_config(), live_state)
    return LiveRuntime(
        live_state=live_state,
        gateway=gateway,
        scheduler=LiveScheduler(),
        data_provider=data_provider,
        market_data=market_data,
        config=config,
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


def _is_close(offset: str) -> bool:
    return "平" in offset or "CLOSE" in offset.upper()
