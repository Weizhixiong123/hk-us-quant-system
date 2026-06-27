from __future__ import annotations

from quant.live.config import FutuGatewayConfig, TigerGatewayConfig
from quant.live.market_data import Bar
from quant.live.state import LiveGatewayState
from quant.live.translate import (
    account_from_vnpy,
    order_from_vnpy,
    position_from_vnpy,
    tick_from_vnpy,
    trade_from_vnpy,
)

_FUTU_GATEWAY_NAME = "FUTU"
_TIGER_GATEWAY_NAME = "TIGER"
_FUTU_US_DEFAULT_EXCHANGE = "SMART"
_TIGER_US_DEFAULT_EXCHANGE = "NASDAQ"


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

        setting = _futu_setting_from_config(self.config)
        try:
            self._main_engine.connect(setting, _FUTU_GATEWAY_NAME)
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
            main_engine.subscribe(req, _FUTU_GATEWAY_NAME)

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
        return self._require_main_engine().send_order(req, _FUTU_GATEWAY_NAME)

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
        self._require_main_engine().cancel_order(req, _FUTU_GATEWAY_NAME)

    def query_history_minute(
        self,
        symbol: str,
        count: int = 800,
        exchange: str | None = None,
    ) -> list[Bar]:
        # 先校验连接（未连接抛 RuntimeError），再延迟 import vnpy（远程无 vnpy）。
        main_engine = self._require_main_engine()
        from datetime import datetime, timedelta

        from vnpy.trader.constant import Exchange, Interval
        from vnpy.trader.object import HistoryRequest

        req = HistoryRequest(
            symbol=_clean_symbol(symbol),
            exchange=_resolve_exchange(symbol, self.config.market, Exchange, exchange),
            start=datetime.now() - timedelta(days=5),
            end=datetime.now(),
            interval=Interval.MINUTE,
        )
        raw_bars = main_engine.query_history(req, _FUTU_GATEWAY_NAME) or []
        return _bars_from_vnpy(symbol, raw_bars)[-count:]

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


class TigerLiveGateway:
    """vnpy 老虎网关封装。仅本地安装 vnpy_tiger/tigeropen 后可运行。"""

    def __init__(self, config: TigerGatewayConfig, state: LiveGatewayState) -> None:
        self.config = config
        self.state = state
        self._main_engine = None
        self._event_engine = None

    def connect(self) -> None:
        # 延迟 import:远程环境无 vnpy/tigeropen,导入只在本地真正调用时发生
        from vnpy.event import EventEngine
        from vnpy.trader.engine import MainEngine
        from vnpy.trader.event import (
            EVENT_ACCOUNT,
            EVENT_ORDER,
            EVENT_POSITION,
            EVENT_TICK,
            EVENT_TRADE,
        )
        from vnpy_tiger import TigerGateway

        self._event_engine = EventEngine()
        self._main_engine = MainEngine(self._event_engine)
        self._main_engine.add_gateway(TigerGateway)

        self._event_engine.register(EVENT_ACCOUNT, self._on_account)
        self._event_engine.register(EVENT_POSITION, self._on_position)
        self._event_engine.register(EVENT_ORDER, self._on_order)
        self._event_engine.register(EVENT_TRADE, self._on_trade)
        self._event_engine.register(EVENT_TICK, self._on_tick)

        try:
            self._main_engine.connect(
                _tiger_setting_from_config(self.config),
                _TIGER_GATEWAY_NAME,
            )
        except Exception:
            self.state.set_connected(False, "TIGER 连接失败")
            raise
        self.state.set_connected(
            True,
            f"TIGER {self.config.environment} 连接请求已发送",
        )

    def subscribe(self, symbols: list[str], exchange: str | None = None) -> None:
        # 延迟 import:远程环境无 vnpy
        from vnpy.trader.constant import Exchange
        from vnpy.trader.object import SubscribeRequest

        main_engine = self._require_main_engine()
        for symbol in symbols:
            req = SubscribeRequest(
                symbol=_clean_symbol(symbol),
                exchange=_resolve_exchange(
                    symbol,
                    self.config.market,
                    Exchange,
                    exchange,
                    us_default_exchange=_TIGER_US_DEFAULT_EXCHANGE,
                ),
            )
            main_engine.subscribe(req, _TIGER_GATEWAY_NAME)

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
            exchange=_resolve_exchange(
                symbol,
                self.config.market,
                Exchange,
                exchange,
                us_default_exchange=_TIGER_US_DEFAULT_EXCHANGE,
            ),
            direction=Direction(direction),
            type=OrderType.LIMIT,
            volume=volume,
            price=price,
            offset=Offset(offset),
        )
        return self._require_main_engine().send_order(req, _TIGER_GATEWAY_NAME)

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
            exchange=_resolve_exchange(
                symbol,
                self.config.market,
                Exchange,
                exchange,
                us_default_exchange=_TIGER_US_DEFAULT_EXCHANGE,
            ),
        )
        self._require_main_engine().cancel_order(req, _TIGER_GATEWAY_NAME)

    def query_history_minute(
        self,
        symbol: str,
        count: int = 800,
        exchange: str | None = None,
    ) -> list[Bar]:
        main_engine = self._require_main_engine()
        from datetime import datetime, timedelta

        from vnpy.trader.constant import Exchange, Interval
        from vnpy.trader.object import HistoryRequest

        req = HistoryRequest(
            symbol=_clean_symbol(symbol),
            exchange=_resolve_exchange(
                symbol,
                self.config.market,
                Exchange,
                exchange,
                us_default_exchange=_TIGER_US_DEFAULT_EXCHANGE,
            ),
            start=datetime.now() - timedelta(days=5),
            end=datetime.now(),
            interval=Interval.MINUTE,
        )
        raw_bars = main_engine.query_history(req, _TIGER_GATEWAY_NAME) or []
        return _bars_from_vnpy(symbol, raw_bars)[-count:]

    def close(self) -> None:
        if self._main_engine is not None:
            self._main_engine.close()
        self.state.set_connected(False, "已断开")

    def _require_main_engine(self):
        if self._main_engine is None:
            raise RuntimeError("TigerLiveGateway is not connected")
        return self._main_engine

    # ---- 内部事件回调 ----

    def _on_account(self, event) -> None:
        self.state.update_account(account_from_vnpy(event.data))
        self.state.set_connected(
            True,
            f"TIGER {self.config.environment} 已收到账户回报",
        )

    def _on_position(self, event) -> None:
        self.state.update_position(position_from_vnpy(event.data))

    def _on_order(self, event) -> None:
        self.state.update_order(order_from_vnpy(event.data))

    def _on_trade(self, event) -> None:
        self.state.update_trade(trade_from_vnpy(event.data))

    def _on_tick(self, event) -> None:
        self.state.update_tick(tick_from_vnpy(event.data))


def _tiger_setting_from_config(config: TigerGatewayConfig) -> dict[str, str]:
    return {
        "tiger_id": config.tiger_id,
        "account": config.account,
        "private_key": config.private_key,
        "private_key_path": config.private_key_path,
        "tiger_public_key_path": config.tiger_public_key_path,
        "environment": config.environment,
        "language": config.language,
        "max_contracts": str(config.max_contracts),
        "use_preset_contracts": "true" if config.use_preset_contracts else "false",
    }


def _futu_setting_from_config(config: FutuGatewayConfig) -> dict[str, object]:
    return {
        "密码": "",
        "地址": config.host,
        "端口": config.port,
        "市场": config.market,
        "环境": config.trd_env,
    }


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
    us_default_exchange: str = _FUTU_US_DEFAULT_EXCHANGE,
):
    if exchange:
        return getattr(exchange_enum, exchange.upper())

    symbol_market = _market_from_symbol(symbol) or market.upper()
    if symbol_market == "HK":
        return exchange_enum.SEHK

    if symbol_market == "US":
        if hasattr(exchange_enum, us_default_exchange):
            return getattr(exchange_enum, us_default_exchange)
        return exchange_enum.NASDAQ

    raise ValueError(f"unsupported market for gateway: {symbol_market}")


def _market_from_symbol(symbol: str) -> str | None:
    value = symbol.strip().upper()
    if value.endswith(".HK") or value.startswith("HK."):
        return "HK"
    if value.endswith(".US") or value.startswith("US."):
        return "US"
    return None


def _bars_from_vnpy(symbol: str, raw_bars) -> list[Bar]:
    bars: list[Bar] = []
    for item in raw_bars:
        dt = getattr(item, "datetime", None)
        if dt is None:
            continue
        bars.append(
            Bar(
                symbol=symbol,
                start=dt,
                open=float(getattr(item, "open_price", 0.0)),
                high=float(getattr(item, "high_price", 0.0)),
                low=float(getattr(item, "low_price", 0.0)),
                close=float(getattr(item, "close_price", 0.0)),
                volume=float(getattr(item, "volume", 0.0)),
            )
        )
    return bars

