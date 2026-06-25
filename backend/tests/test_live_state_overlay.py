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

    assert dashboard.account.source == "broker"
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

    assert dashboard.account.source == "dry_run"
    assert dashboard.account.total_equity == 1_000_000
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


def test_dashboard_account_reflects_dry_run_simulated_account():
    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_002_000, available=1_002_000, frozen=0)
    )

    account = AppState(live_state).dashboard().account

    assert account.source == "dry_run"
    assert account.total_equity == 1_002_000
    assert account.day_pnl == 2_000  # balance − default_equity(1,000,000)
    assert account.day_pnl_pct == 0.2


def test_dashboard_hides_seed_demo_when_live_account_present():
    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=1_000_000, frozen=0)
    )

    dashboard = AppState(live_state).dashboard()

    # 网关已初始化(有账户)但尚无成交 → 显示空,而非 seed 演示数据
    assert dashboard.positions == []
    assert dashboard.orders == []
    assert dashboard.trades == []


def test_tick_skips_demo_drift_when_live_account_present():
    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=1_000_000, frozen=0)
    )
    state = AppState(live_state)

    first = [candle.close for candle in state.tick().chart]
    second = [candle.close for candle in state.tick().chart]

    # 已接网关:不做随机演示漂移,连续推送一致
    assert first == second
    assert state.tick().positions == []


def test_risk_intraday_count_matches_live_positions():
    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=1_000_000, frozen=0)
    )

    risk = AppState(live_state).dashboard().risk
    intraday = next(r for r in risk if r.code == "intraday_position_count")

    # 接网关后无真实持仓 → 0/3，与持仓栏(空)一致，而非 seed 的 1/3
    assert intraday.detail == "0/3"
