from __future__ import annotations

from threading import RLock

from quant.live.translate import (
    GatewayAccount,
    GatewayOrder,
    GatewayPosition,
    GatewayTick,
)


class LiveGatewayState:
    def __init__(self) -> None:
        self._lock = RLock()
        self._connected = False
        self._detail = ""
        self._account: GatewayAccount | None = None
        self._positions: dict[str, GatewayPosition] = {}
        self._orders: dict[str, GatewayOrder] = {}
        self._ticks: dict[str, GatewayTick] = {}

    def set_connected(self, connected: bool, detail: str = "") -> None:
        with self._lock:
            self._connected = connected
            self._detail = detail

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def update_account(self, acc: GatewayAccount) -> None:
        with self._lock:
            self._account = acc

    def update_position(self, pos: GatewayPosition) -> None:
        key = f"{pos.symbol}:{pos.direction}"
        with self._lock:
            if pos.volume == 0:
                self._positions.pop(key, None)
            else:
                self._positions[key] = pos

    def update_order(self, order: GatewayOrder) -> None:
        with self._lock:
            self._orders[order.order_id] = order

    def update_tick(self, tick: GatewayTick) -> None:
        with self._lock:
            self._ticks[tick.symbol] = tick

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "connected": self._connected,
                "detail": self._detail,
                "account": self._account,
                "positions": list(self._positions.values()),
                "orders": list(self._orders.values()),
                "ticks": list(self._ticks.values()),
            }
