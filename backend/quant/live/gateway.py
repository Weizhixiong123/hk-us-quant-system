from __future__ import annotations

import os
import socket
from datetime import datetime, timezone

from quant.live.config import FutuGatewayConfig, TigerGatewayConfig
from quant.live.market_data import Bar
from quant.live.state import LiveGatewayState
from quant.live.translate import (
    GatewayTrade,
    account_from_vnpy,
    log_from_vnpy,
    order_from_vnpy,
    position_from_vnpy,
    tick_from_vnpy,
    trade_from_vnpy,
)

_FUTU_GATEWAY_NAME = "FUTU"
_TIGER_GATEWAY_NAME = "TIGER"
_FUTU_US_DEFAULT_EXCHANGE = "SMART"
_TIGER_US_DEFAULT_EXCHANGE = "NASDAQ"


def _check_tcp_endpoint(host: str, port: int, timeout: float = 1.0) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        pass


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
        self._gateway_names: dict[str, str] = {}
        self._synced_order_traded: dict[str, float] = {}

    def connect(self) -> None:
        checked_endpoints: set[tuple[str, int]] = set()
        for market in self.config.markets:
            account = self.config.account_for(market)
            endpoint = (account.host, account.port)
            if endpoint in checked_endpoints:
                continue
            try:
                _check_tcp_endpoint(*endpoint)
            except OSError as exc:
                detail = (
                    f"无法连接富途账户 {account.name} 的 FutuOpenD "
                    f"{account.host}:{account.port}，请启动对应 OpenD 或切换到干跑模式"
                )
                self.state.set_connected(False, detail)
                raise ConnectionError(detail) from exc
            checked_endpoints.add(endpoint)

        # 延迟 import:远程环境无 vnpy,导入只在本地真正调用时发生
        from vnpy.event import EventEngine
        from vnpy.trader.engine import MainEngine
        from vnpy.trader.event import (
            EVENT_ACCOUNT,
            EVENT_LOG,
            EVENT_ORDER,
            EVENT_POSITION,
            EVENT_TICK,
            EVENT_TRADE,
        )
        from vnpy_futu import FutuGateway

        self._event_engine = EventEngine()
        self._main_engine = MainEngine(self._event_engine)
        self._event_engine.register(EVENT_ACCOUNT, self._on_account)
        self._event_engine.register(EVENT_LOG, self._on_log)
        self._event_engine.register(EVENT_POSITION, self._on_position)
        self._event_engine.register(EVENT_ORDER, self._on_order)
        self._event_engine.register(EVENT_TRADE, self._on_trade)
        self._event_engine.register(EVENT_TICK, self._on_tick)

        try:
            for market in self.config.markets:
                account = self.config.account_for(market)
                gateway_name = _futu_gateway_name(market, account.account_id)
                self._main_engine.add_gateway(FutuGateway, gateway_name)
                self._gateway_names[market] = gateway_name
                self._main_engine.connect(
                    _futu_setting_from_config(self.config, market),
                    gateway_name,
                )
        except Exception:
            self.state.set_connected(False, "FUTU 连接失败")
            raise
        markets = "/".join(self.config.markets)
        self.state.set_connected(
            True,
            f"FUTU {markets} {self.config.trd_env} 连接请求已发送",
        )

    def subscribe(self, symbols: list[str], exchange: str | None = None) -> None:
        for symbol in symbols:
            market = _futu_route_market(symbol, self.config.market, exchange)
            main_engine, gateway_name = self._require_futu_gateway(market)
            gateway = main_engine.get_gateway(gateway_name)
            quote_ctx = getattr(gateway, "quote_ctx", None)
            if quote_ctx is None:
                raise RuntimeError(f"FUTU {market} quote connection is not ready")
            futu_symbol = f"{market}.{_clean_symbol(symbol)}"
            code, detail = quote_ctx.subscribe(futu_symbol, "QUOTE", True)
            if code:
                gateway.write_log(f"订阅行情失败：{detail}")

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

        market = _futu_route_market(symbol, self.config.market, exchange)
        order_type = _resolve_order_type()
        req = OrderRequest(
            symbol=_clean_symbol(symbol),
            exchange=_resolve_exchange(symbol, self.config.market, Exchange, exchange),
            direction=Direction(direction),
            type=order_type,
            volume=volume,
            price=price,
            offset=Offset(offset),
        )
        main_engine, gateway_name = self._require_futu_gateway(market)
        return main_engine.send_order(req, gateway_name)

    def cancel_order(
        self,
        order_id: str,
        symbol: str,
        exchange: str | None = None,
    ) -> None:
        # 延迟 import:远程环境无 vnpy
        from vnpy.trader.constant import Exchange
        from vnpy.trader.object import CancelRequest

        market = _futu_route_market(symbol, self.config.market, exchange)
        req = CancelRequest(
            orderid=order_id,
            symbol=_clean_symbol(symbol),
            exchange=_resolve_exchange(symbol, self.config.market, Exchange, exchange),
        )
        main_engine, gateway_name = self._require_futu_gateway(market)
        main_engine.cancel_order(req, gateway_name)

    def sync_trades(self) -> None:
        """模拟盘不提供成交查询，以订单的累计成交量补齐成交记录。"""
        if not self.config.paper:
            return
        for market, gateway_name in self._gateway_names.items():
            gateway = self._require_main_engine().get_gateway(gateway_name)
            trade_ctx = getattr(gateway, "trade_ctx", None)
            if trade_ctx is None:
                continue
            code, rows = trade_ctx.order_list_query("", trd_env=gateway.env)
            if code:
                continue
            for _, row in rows.iterrows():
                order_id = str(row["order_id"])
                cumulative = float(row.get("dealt_qty", 0.0))
                previous = self._synced_order_traded.get(order_id, 0.0)
                self._synced_order_traded[order_id] = max(previous, cumulative)
                if cumulative <= previous:
                    continue
                direction, offset = _futu_trade_direction(str(row.get("trd_side", "")))
                self.state.update_trade(
                    GatewayTrade(
                        trade_id=f"SIM-{order_id}-{cumulative:g}",
                        order_id=order_id,
                        symbol=_futu_symbol(str(row["code"]), market),
                        direction=direction,
                        offset=offset,
                        price=float(row.get("dealt_avg_price", 0.0) or row.get("price", 0.0)),
                        volume=cumulative - previous,
                        time=str(
                            row.get("updated_time")
                            or row.get("create_time")
                            or datetime.now(timezone.utc).isoformat()
                        ),
                    )
                )

    def query_history_minute(
        self,
        symbol: str,
        count: int = 800,
        exchange: str | None = None,
    ) -> list[Bar]:
        # 先校验连接（未连接抛 RuntimeError），再延迟 import vnpy（远程无 vnpy）。
        market = _futu_route_market(symbol, self.config.market, exchange)
        main_engine, gateway_name = self._require_futu_gateway(market)
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
        _install_pandas_append_compat()
        raw_bars = main_engine.query_history(req, gateway_name) or []
        return _bars_from_vnpy(symbol, raw_bars)[-count:]

    def close(self) -> None:
        if self._main_engine is not None:
            self._main_engine.close()
        self.state.set_connected(False, "已断开")

    def _require_main_engine(self):
        if self._main_engine is None:
            raise RuntimeError("FutuLiveGateway is not connected")
        return self._main_engine

    def _require_futu_gateway(self, market: str):
        main_engine = self._require_main_engine()
        gateway_name = self._gateway_names.get(market)
        if gateway_name is None:
            raise RuntimeError(f"FUTU {market} market is not configured")
        return main_engine, gateway_name

    # ---- 内部事件回调 ----

    def _on_account(self, event) -> None:
        gateway_name = str(getattr(event.data, "gateway_name", ""))
        event_source = f"{gateway_name} {getattr(event, 'type', '')}".upper()
        if event_source.endswith("_US") or "_US " in event_source:
            market = "US"
        elif event_source.endswith("_HK") or "_HK " in event_source:
            market = "HK"
        else:
            market = self.config.market
        self.state.update_account(account_from_vnpy(event.data, market))
        self.state.set_connected(True, f"FUTU {self.config.trd_env} 已收到账户回报")

    def _on_position(self, event) -> None:
        self.state.update_position(position_from_vnpy(event.data))

    def _on_order(self, event) -> None:
        self.state.update_order(order_from_vnpy(event.data))

    def _on_trade(self, event) -> None:
        if self.config.paper:
            return
        self.state.update_trade(trade_from_vnpy(event.data))

    def _on_tick(self, event) -> None:
        self.state.update_tick(tick_from_vnpy(event.data))

    def _on_log(self, event) -> None:
        self.state.update_log(log_from_vnpy(event.data))


def _resolve_order_type():
    """下单类型:LIVE_ORDER_TYPE 环境变量控制,默认市价单。

    - market / MARKET → 市价单(挂上去立即按对手价成交,不等待)
    - limit  / LIMIT  → 限价单(挂在指定 price,等待撮合)
    市价单可避免「闭市/无 tick 时限价单挂在最新价永不成交」的资金占用问题。
    vnpy OrderType 在函数内延迟导入,避免顶层依赖远程测试环境无 vnpy。
    """
    from vnpy.trader.constant import OrderType

    raw = os.getenv("LIVE_ORDER_TYPE", "market").strip().lower()
    if raw in {"limit", "limit_price"}:
        return OrderType.LIMIT
    return OrderType.MARKET


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
            type=_resolve_order_type(),
            volume=volume,
            price=price if price > 0 else 0.0,
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

    def sync_trades(self) -> None:
        pass

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
        self.state.update_account(account_from_vnpy(event.data, self.config.market))
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


def _futu_gateway_name(market: str, account_id: str = "default") -> str:
    if account_id == "default":
        return f"{_FUTU_GATEWAY_NAME}_{market.upper()}"
    safe_account_id = "".join(
        character if character.isalnum() else "_" for character in account_id.upper()
    )
    return f"{_FUTU_GATEWAY_NAME}_{safe_account_id}_{market.upper()}"


def _futu_setting_from_config(
    config: FutuGatewayConfig,
    market: str | None = None,
) -> dict[str, object]:
    selected_market = (market or config.market).upper()
    account = config.account_for(selected_market)
    return {
        "密码": "",
        "地址": account.host,
        "端口": account.port,
        "市场": selected_market,
        "环境": config.trd_env,
    }


def _futu_route_market(
    symbol: str,
    default_market: str,
    exchange: str | None = None,
) -> str:
    if exchange:
        exchange_market = {
            "SEHK": "HK",
            "HKFE": "HK",
            "SMART": "US",
            "NASDAQ": "US",
            "NYSE": "US",
        }.get(exchange.upper())
        if exchange_market:
            return exchange_market
    return _market_from_symbol(symbol) or default_market.upper()


def _clean_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    market = ""
    if value.endswith(".HK") or value.endswith(".US"):
        market = value[-2:]
        value = value[:-3]
    elif value.startswith("HK.") or value.startswith("US."):
        market = value[:2]
        value = value[3:]
    if (market == "HK" or (not market and value.isdigit())) and value.isdigit():
        return value.zfill(5)
    return value


def _futu_symbol(code: str, market: str) -> str:
    value = code.strip().upper()
    if "." in value:
        prefix, symbol = value.split(".", 1)
        return f"{symbol}.{prefix}"
    return f"{value}.{market.upper()}"


def _futu_trade_direction(side: str) -> tuple[str, str]:
    value = side.upper()
    if value == "BUY_BACK":
        return "多", "平"
    if value == "SELL_SHORT":
        return "空", "开"
    if value == "SELL":
        return "空", "平"
    return "多", "开"


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
    if not value:
        return None
    return "HK" if value.isdigit() else "US"


def _install_pandas_append_compat() -> None:
    """Keep the current vnpy_futu history adapter working with pandas >= 2."""
    import pandas as pd

    if hasattr(pd.DataFrame, "append"):
        return

    def append(frame, other, ignore_index=False, **kwargs):
        return pd.concat([frame, other], ignore_index=ignore_index, **kwargs)

    pd.DataFrame.append = append  # type: ignore[attr-defined]


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
