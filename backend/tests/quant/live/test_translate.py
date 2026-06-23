from types import SimpleNamespace

from quant.live.translate import (
    GatewayAccount,
    GatewayOrder,
    GatewayPosition,
    GatewayTick,
    GatewayTrade,
    account_from_vnpy,
    order_from_vnpy,
    position_from_vnpy,
    tick_from_vnpy,
    trade_from_vnpy,
)


class _Enum:
    def __init__(self, value):
        self.value = value


def test_account_from_vnpy_computes_available():
    obj = SimpleNamespace(accountid="ACC1", balance=100000.0, frozen=20000.0)
    acc = account_from_vnpy(obj)
    assert acc == GatewayAccount(account_id="ACC1", balance=100000.0, available=80000.0, frozen=20000.0)


def test_position_from_vnpy_maps_enum_direction():
    obj = SimpleNamespace(symbol="AAPL", direction=_Enum("多"), volume=400, price=198.4, pnl=1080.0)
    pos = position_from_vnpy(obj)
    assert pos == GatewayPosition(symbol="AAPL", direction="多", volume=400, price=198.4, pnl=1080.0)


def test_order_from_vnpy():
    obj = SimpleNamespace(
        orderid="ORD1", symbol="AAPL", direction=_Enum("多"), offset=_Enum("开"),
        price=198.4, volume=400, traded=0, status=_Enum("提交中"),
    )
    o = order_from_vnpy(obj)
    assert o.order_id == "ORD1" and o.status == "提交中" and o.offset == "开"


def test_trade_from_vnpy():
    obj = SimpleNamespace(
        tradeid="TRD1",
        orderid="ORD1",
        symbol="00700",
        direction=_Enum("多"),
        offset=_Enum("开"),
        price=389.4,
        volume=100,
        datetime=SimpleNamespace(isoformat=lambda: "2026-06-23T10:30:00"),
    )
    trade = trade_from_vnpy(obj)
    assert trade == GatewayTrade(
        trade_id="TRD1",
        order_id="ORD1",
        symbol="00700",
        direction="多",
        offset="开",
        price=389.4,
        volume=100,
        time="2026-06-23T10:30:00",
    )


def test_tick_from_vnpy_formats_time():
    obj = SimpleNamespace(symbol="AAPL", last_price=201.1, volume=1000,
                          datetime=SimpleNamespace(isoformat=lambda: "2026-06-22T10:00:00"))
    t = tick_from_vnpy(obj)
    assert t == GatewayTick(symbol="AAPL", last_price=201.1, volume=1000, time="2026-06-22T10:00:00")

