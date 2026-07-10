from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from quant.live.risk import PdtTracker
from quant.live.store import DbPath, record_live_event


@dataclass
class StrategyRuntimeState:
    intraday_watchlist: list[str] = field(default_factory=list)
    portfolio_watchlist: list[str] = field(default_factory=list)
    intraday_open_symbols: set[str] = field(default_factory=set)
    stopped_symbols_today: set[str] = field(default_factory=set)
    intraday_half_taken: set[str] = field(default_factory=set)
    trend_half_taken: set[str] = field(default_factory=set)
    portfolio_stage: dict[str, str] = field(default_factory=dict)
    consecutive_order_failures: int = 0
    pdt_tracker: PdtTracker = field(default_factory=PdtTracker)
    _current_day: date | None = None
    day_start_equity: float | None = None
    halted_today: bool = False
    _seen_orders: set[tuple[str, str, float]] = field(default_factory=set)
    _seen_trades: set[str] = field(default_factory=set)
    _seen_positions: set[tuple[str, str, float, float, float]] = field(default_factory=set)
    portfolio_entry_dates: dict[str, date] = field(default_factory=dict)

    def reset_for_day(self, day: date) -> None:
        if self._current_day == day:
            return
        self._current_day = day
        self.stopped_symbols_today.clear()
        self.intraday_half_taken.clear()
        self.day_start_equity = None
        self.halted_today = False

    def observe_account_equity(self, balance: float, day: date) -> None:
        self.reset_for_day(day)
        if self.day_start_equity is None and balance > 0:
            self.day_start_equity = float(balance)

    def daily_loss_pct(self, current_balance: float) -> float:
        if not self.day_start_equity or self.day_start_equity <= 0:
            return 0.0
        return (float(current_balance) - self.day_start_equity) / self.day_start_equity * 100

    def trip_halt_if_breached(self, current_balance: float, max_daily_loss_pct: float) -> bool:
        if self.daily_loss_pct(current_balance) <= -abs(max_daily_loss_pct):
            self.halted_today = True
        return self.halted_today

    def is_halted(self) -> bool:
        return self.halted_today

    def mark_stopped(self, symbol: str) -> None:
        self.stopped_symbols_today.add(_normalize(symbol))

    def mark_intraday_half_taken(self, symbol: str) -> None:
        self.intraday_half_taken.add(_normalize(symbol))

    def intraday_half_done(self, symbol: str) -> bool:
        return _normalize(symbol) in self.intraday_half_taken

    def mark_trend_half_taken(self, symbol: str) -> None:
        self.trend_half_taken.add(_normalize(symbol))

    def trend_half_done(self, symbol: str) -> bool:
        return _normalize(symbol) in self.trend_half_taken

    def mark_intraday_open(self, symbol: str) -> None:
        self.intraday_open_symbols.add(_normalize(symbol))

    def mark_intraday_closed(self, symbol: str) -> None:
        normalized = _normalize(symbol)
        self.intraday_open_symbols.discard(normalized)
        self.intraday_half_taken.discard(normalized)

    def owns_intraday_symbol(self, symbol: str) -> bool:
        return _normalize(symbol) in self.intraday_open_symbols

    def next_portfolio_stage(self, symbol: str) -> str:
        return "add" if self.portfolio_stage.get(_normalize(symbol)) == "first_filled" else "first"

    def mark_portfolio_entry_submitted(self, symbol: str, stage: str) -> None:
        if stage == "first":
            self.portfolio_stage[_normalize(symbol)] = "first_filled"
        elif stage == "add":
            self.portfolio_stage[_normalize(symbol)] = "full"

    def record_order_result(self, submitted: bool, reasons: tuple[str, ...]) -> None:
        if submitted:
            self.consecutive_order_failures = 0
            return
        if any(reason.startswith("下单失败") for reason in reasons):
            self.consecutive_order_failures += 1

    def pdt_remaining(self, day: date) -> int:
        return self.pdt_tracker.remaining(day)

    def record_portfolio_entry_date(self, symbol: str, day: date) -> None:
        self.portfolio_entry_dates.setdefault(_normalize(symbol), day)

    def holding_days(self, symbol: str, today: date) -> int:
        entry = self.portfolio_entry_dates.get(_normalize(symbol))
        return (today - entry).days if entry is not None else 0

    def load_entry_dates_from_events(self, events) -> None:
        for event in events:
            payload = event.payload or {}
            key = payload.get("trade_id") or (
                f"{payload.get('order_id', '')}:{payload.get('symbol', event.symbol or '')}:"
                f"{payload.get('time', '')}"
            )
            self._seen_trades.add(str(key))
        for symbol, day in entry_dates_from_trade_events(events).items():
            self.portfolio_entry_dates.setdefault(symbol, day)

    def persist_gateway_snapshot(
        self,
        snapshot: dict[str, Any],
        at: datetime,
        db_path: DbPath | None = None,
    ) -> None:
        self._persist_orders(snapshot.get("orders", []), at, db_path)
        self._persist_trades(snapshot.get("trades", []), at, db_path)
        self._persist_positions(snapshot.get("positions", []), at, db_path)

    def _persist_orders(self, orders: list[Any], at: datetime, db_path: DbPath | None) -> None:
        for order in orders:
            key = (order.order_id, order.status, float(order.traded))
            if key in self._seen_orders:
                continue
            self._seen_orders.add(key)
            record_live_event(
                kind="signal",
                strategy_id="live",
                symbol=order.symbol,
                created_at=at,
                payload={"event": "order", **asdict(order)},
                db_path=db_path,
            )

    def _persist_trades(self, trades: list[Any], at: datetime, db_path: DbPath | None) -> None:
        for trade in trades:
            key = trade.trade_id or f"{trade.order_id}:{trade.symbol}:{trade.time}"
            if key in self._seen_trades:
                continue
            self._seen_trades.add(key)
            if _market_from_symbol(trade.symbol) == "US" and _is_close(trade.offset):
                self.pdt_tracker.record_day_trade(at.date())
            record_live_event(
                kind="trade",
                strategy_id="live",
                symbol=trade.symbol,
                created_at=at,
                payload={"event": "trade", **asdict(trade)},
                db_path=db_path,
            )

    def _persist_positions(self, positions: list[Any], at: datetime, db_path: DbPath | None) -> None:
        for position in positions:
            key = (
                position.symbol,
                position.direction,
                float(position.volume),
                float(position.price),
                float(position.pnl),
            )
            if key in self._seen_positions:
                continue
            self._seen_positions.add(key)
            record_live_event(
                kind="position",
                strategy_id="live",
                symbol=position.symbol,
                created_at=at,
                payload={"event": "position", **asdict(position)},
                db_path=db_path,
            )


def _normalize(symbol: str) -> str:
    return symbol.strip().upper()


def _is_close(offset: str) -> bool:
    return "平" in offset or "CLOSE" in offset.upper()


def _market_from_symbol(symbol: str) -> str:
    value = symbol.upper()
    if value.endswith(".HK") or value.startswith("HK.") or value.isdigit():
        return "HK"
    return "US"


def entry_dates_from_trade_events(events) -> dict[str, date]:
    result: dict[str, date] = {}
    for event in sorted(events, key=lambda item: item.created_at):
        payload = getattr(event, "payload", {}) or {}
        offset = str(payload.get("offset", ""))
        symbol = getattr(event, "symbol", None) or payload.get("symbol")
        if symbol and "开" in offset:
            result.setdefault(_normalize(symbol), event.created_at.date())
    return result
