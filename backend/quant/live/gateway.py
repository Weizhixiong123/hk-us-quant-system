from __future__ import annotations

from quant.live.config import FutuGatewayConfig
from quant.live.state import LiveGatewayState
from quant.live.translate import (
    account_from_vnpy,
    order_from_vnpy,
    position_from_vnpy,
    tick_from_vnpy,
)


class FutuLiveGateway:
    """vnpy 富途网关封装。仅本地(连 FutuOpenD)可运行。

    字段映射依赖 quant.live.translate;若本地 vnpy 版本字段名不同,
    在 translate.py 的 *_from_vnpy 集中调整。

    Exchange 映射说明(本地联调待细化):
    - 港股: Exchange.SEHK
    - 美股: Exchange.NASDAQ / Exchange.NYSE / Exchange.SMART
      (具体值以 vnpy_futu 实际支持为准,多市场时在 subscribe/send_order 按 symbol 前缀分支)
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
        self._main_engine.connect(setting, "FUTU")
        self.state.set_connected(True, f"FUTU {self.config.trd_env} 已连接")

    def subscribe(self, symbols: list[str]) -> None:
        # 延迟 import:远程环境无 vnpy
        from vnpy.trader.constant import Exchange
        from vnpy.trader.object import SubscribeRequest

        for symbol in symbols:
            # 占位:港股用 SEHK;美股映射(NASDAQ/NYSE/SMART)本地联调时按 vnpy_futu 实际要求补全
            req = SubscribeRequest(symbol=symbol, exchange=Exchange.SEHK)
            self._main_engine.subscribe(req, "FUTU")

    def send_order(self, symbol, direction, offset, price, volume) -> str:
        # 延迟 import:远程环境无 vnpy
        from vnpy.trader.constant import Direction, Exchange, Offset, OrderType
        from vnpy.trader.object import OrderRequest

        # 占位:港股用 SEHK;多市场时本地联调按 symbol 前缀/config.market 分支
        req = OrderRequest(
            symbol=symbol,
            exchange=Exchange.SEHK,
            direction=Direction(direction),
            type=OrderType.LIMIT,
            volume=volume,
            price=price,
            offset=Offset(offset),
        )
        return self._main_engine.send_order(req, "FUTU")

    def close(self) -> None:
        if self._main_engine is not None:
            self._main_engine.close()
        self.state.set_connected(False, "已断开")

    # ---- 内部事件回调 ----

    def _on_account(self, event) -> None:
        self.state.update_account(account_from_vnpy(event.data))

    def _on_position(self, event) -> None:
        self.state.update_position(position_from_vnpy(event.data))

    def _on_order(self, event) -> None:
        self.state.update_order(order_from_vnpy(event.data))

    def _on_trade(self, event) -> None:
        # 成交回报暂不单独入 state:持仓由 EVENT_POSITION 维护,订单状态由 EVENT_ORDER 维护。
        # 待新增专用 trade_from_vnpy 后再记录成交明细(TradeData 字段与 OrderData 不同,
        # 直接复用 order_from_vnpy 会写入不完整订单)。
        return

    def _on_tick(self, event) -> None:
        self.state.update_tick(tick_from_vnpy(event.data))
