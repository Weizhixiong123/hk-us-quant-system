from __future__ import annotations

from quant.live.config import FutuGatewayConfig
from quant.live.state import LiveGatewayState
from quant.live.translate import (
    account_from_vnpy,
    order_from_vnpy,
    position_from_vnpy,
    tick_from_vnpy,
    trade_from_vnpy,
)

_GATEWAY_NAME = "FUTU"
_US_DEFAULT_EXCHANGE = "SMART"


class FutuLiveGateway:
    """vnpy 富途网关封装。仅本地(连 FutuOpenD)可运行。

    字段映射依赖 quant.live.translate;若本地 vnpy 版本字段名不同,
    在 translate.py 的 *_from_vnpy 集中调整。
    """

    def __init__(self, config: FutuGatewayConfig, state: LiveGatewayState) -> None:
        self.config = config
        self.state = state
        self._main_engine = None
        self._event_engine = None

    def connect(self) -> None:
        # 延迟 import:远程环境无 vnpy,导入只在本地真正调用时发生
        from vnpy.event import EventEngine
        from vnpy.trader.engine import MainEngine
        from vnpy.trader.event import (
            EVENT_ACCOUNT,
            EVENT_ORDER,
            EVENT_POSITION,
            EVENT_TICK,
            EVENT_TRADE,
        )
        from vnpy_futu import FutuGateway

        self._event_engine = EventEngine()
        self._main_engine = MainEngine(self._event_engine)
        self._main_engine.add_gateway(FutuGateway)

        self._event_engine.register(EVENT_ACCOUNT, self._on_account)
        self._event_engine.register(EVENT_POSITION, self._on_position)
        self._event_engine.register(EVENT_ORDER, self._on_order)
        self._event_engine.register(EVENT_TRADE, self._on_trade)
        self._event_engine.register(EVENT_TICK, self._on_tick)

        setting = {
            "市场": self.config.market,
            "host": self.config.host,
            "port": self.config.port,
            "trd_env": self.config.trd_env,
        }
        try:
            self._main_engine.connect(setting, _GATEWAY_NAME)
        except Exception:
            self.state.set_connected(False, "FUTU 连接失败")
            raise
        self.state.set_connected(True, f"FUTU {self.config.trd_env} 连接请求已发送")

    def subscribe(self, symbols: list[str], exchange: str | None = None) -> None:
        # 延迟 import:远程环境无 vnpy
        from vnpy.trader.constant import Exchange
        from vnpy.trader.object import SubscribeRequest

        main_engine = self._require_main_engine()
        for symbol in symbols:
            req = SubscribeRequest(
                symbol=_clean_symbol(symbol),
                exchange=_resolve_exchange(symbol, self.config.market, Exchange, exchange),
            )
            main_engine.subscribe(req, _GATEWAY_NAME)

    def send_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        price: float,
        volume: float,
        exchange: str | None = None,
    ) -> str:
        # 延迟 import:远程环境无 vnpy
        from vnpy.trader.constant import Direction, Exchange, Offset, OrderType
        from vnpy.trader.object import OrderRequest

        req = OrderRequest(
            symbol=_clean_symbol(symbol),
            exchange=_resolve_exchange(symbol, self.config.market, Exchange, exchange),
            direction=Direction(direction),
            type=OrderType.LIMIT,
            volume=volume,
            price=price,
            offset=Offset(offset),
        )
        return self._require_main_engine().send_order(req, _GATEWAY_NAME)

    def cancel_order(
        self,
        order_id: str,
        symbol: str,
        exchange: str | None = None,
    ) -> None:
        # 延迟 import:远程环境无 vnpy
        from vnpy.trader.constant import Exchange
        from vnpy.trader.object import CancelRequest

        req = CancelRequest(
            orderid=order_id,
            symbol=_clean_symbol(symbol),
            exchange=_resolve_exchange(symbol, self.config.market, Exchange, exchange),
        )
        self._require_main_engine().cancel_order(req, _GATEWAY_NAME)

    def close(self) -> None:
        if self._main_engine is not None:
            self._main_engine.close()
        self.state.set_connected(False, "已断开")

    def _require_main_engine(self):
        if self._main_engine is None:
            raise RuntimeError("FutuLiveGateway is not connected")
        return self._main_engine

    # ---- 内部事件回调 ----

    def _on_account(self, event) -> None:
        self.state.update_account(account_from_vnpy(event.data))
        self.state.set_connected(True, f"FUTU {self.config.trd_env} 已收到账户回报")

    def _on_position(self, event) -> None:
        self.state.update_position(position_from_vnpy(event.data))

    def _on_order(self, event) -> None:
        self.state.update_order(order_from_vnpy(event.data))

    def _on_trade(self, event) -> None:
        self.state.update_trade(trade_from_vnpy(event.data))

    def _on_tick(self, event) -> None:
        self.state.update_tick(tick_from_vnpy(event.data))


def _clean_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if value.endswith(".HK") or value.endswith(".US"):
        return value[:-3]
    if value.startswith("HK.") or value.startswith("US."):
        return value[3:]
    return value


def _resolve_exchange(
    symbol: str,
    market: str,
    exchange_enum,
    exchange: str | None = None,
):
    if exchange:
        return getattr(exchange_enum, exchange.upper())

    symbol_market = _market_from_symbol(symbol) or market.upper()
    if symbol_market == "HK":
        return exchange_enum.SEHK

    if symbol_market == "US":
        if hasattr(exchange_enum, _US_DEFAULT_EXCHANGE):
            return getattr(exchange_enum, _US_DEFAULT_EXCHANGE)
        return exchange_enum.NASDAQ

    raise ValueError(f"unsupported market for Futu gateway: {symbol_market}")


def _market_from_symbol(symbol: str) -> str | None:
    value = symbol.strip().upper()
    if value.endswith(".HK") or value.startswith("HK."):
        return "HK"
    if value.endswith(".US") or value.startswith("US."):
        return "US"
    return None

