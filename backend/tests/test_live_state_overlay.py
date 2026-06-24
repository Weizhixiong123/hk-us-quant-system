from __future__ import annotations

from app.services.state import AppState
from quant.live.state import LiveGatewayState
from quant.live.translate import (
    GatewayAccount,
    GatewayOrder,
    GatewayPosition,
    GatewayTick,
    GatewayTrade,
)


def test_app_state_dashboard_uses_live_gateway_snapshot():
    live_state = LiveGatewayState()
    live_state.set_connected(True, "FUTU SIMULATE 已收到账户回报")
    live_state.update_account(GatewayAccount("ACC1", balance=100_000, available=80_000, frozen=20_000))
    live_state.update_position(GatewayPosition("AAPL", "多", 300, 100, 450))
    live_state.update_tick(GatewayTick("AAPL", last_price=101.5, volume=1_000, time="2026-06-23T10:00:00"))
    live_state.update_order(GatewayOrder("O1", "AAPL", "多", "开", 100, 300, 300, "全部成交"))
    live_state.update_trade(GatewayTrade("T1", "O1", "AAPL", "多", "开", 100.5, 300, "2026-06-23T10:01:00+00:00"))

    dashboard = AppState(live_state).dashboard()

    assert dashboard.account.total_equity == 100_000
    assert dashboard.account.cash == 80_000
    assert dashboard.risk[0].code == "broker_connection"
    assert dashboard.risk[0].status == "pass"
    assert dashboard.positions[0].symbol == "AAPL"
    assert dashboard.positions[0].last_price == 101.5
    assert dashboard.positions[0].pnl == 450
    assert dashboard.orders[0].side == "buy"
    assert dashboard.orders[0].status == "filled"
    assert dashboard.trades[0].id == "T1"
    assert dashboard.trades[0].side == "buy"
    assert dashboard.trades[0].price == 100.5
    assert dashboard.logs[0].source == "gateway"


def test_app_state_dashboard_falls_back_without_live_account():
    state = AppState(LiveGatewayState())

    dashboard = state.dashboard()

    assert dashboard.account.total_equity == 1_285_000
    assert dashboard.positions
    assert dashboard.orders
    assert dashboard.risk[0].status == "blocked"


def test_update_strategy_params_syncs_live_params():
    from quant.live.params import LiveParams
    from quant.live.state import LiveGatewayState
    from app.services.state import AppState

    params = LiveParams()
    state = AppState(LiveGatewayState(), params)
    state.update_strategy_params("intraday_macd", {"stop_loss_pct": 2.5})
    assert params.intraday.stop_loss_pct == 2.5
