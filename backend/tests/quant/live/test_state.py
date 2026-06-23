from quant.live.state import LiveGatewayState
from quant.live.translate import GatewayAccount, GatewayOrder, GatewayPosition, GatewayTick, GatewayTrade


def test_connection_flag():
    s = LiveGatewayState()
    assert s.is_connected() is False
    s.set_connected(True, "ok")
    assert s.is_connected() is True
    assert s.snapshot()["detail"] == "ok"


def test_position_upsert_and_remove_on_zero():
    s = LiveGatewayState()
    s.update_position(GatewayPosition("AAPL", "多", 400, 198.4, 0.0))
    s.update_position(GatewayPosition("AAPL", "多", 500, 199.0, 10.0))  # 覆盖
    assert len(s.snapshot()["positions"]) == 1
    assert s.snapshot()["positions"][0].volume == 500
    s.update_position(GatewayPosition("AAPL", "多", 0, 0.0, 0.0))  # 清零移除
    assert s.snapshot()["positions"] == []


def test_order_trade_and_tick_upsert():
    s = LiveGatewayState()
    s.update_order(GatewayOrder("O1", "AAPL", "多", "开", 198.4, 400, 0, "提交中"))
    s.update_order(GatewayOrder("O1", "AAPL", "多", "开", 198.4, 400, 400, "全部成交"))
    assert len(s.snapshot()["orders"]) == 1
    assert s.snapshot()["orders"][0].status == "全部成交"

    s.update_trade(GatewayTrade("T1", "O1", "AAPL", "多", "开", 198.5, 400, "t1"))
    assert len(s.snapshot()["trades"]) == 1
    assert s.snapshot()["trades"][0].trade_id == "T1"

    s.update_tick(GatewayTick("AAPL", 201.1, 1000, "t1"))
    s.update_tick(GatewayTick("AAPL", 202.0, 1100, "t2"))
    assert len(s.snapshot()["ticks"]) == 1
    assert s.snapshot()["ticks"][0].last_price == 202.0


def test_account_update():
    s = LiveGatewayState()
    s.update_account(GatewayAccount("ACC1", 100000.0, 80000.0, 20000.0))
    assert s.snapshot()["account"].available == 80000.0

