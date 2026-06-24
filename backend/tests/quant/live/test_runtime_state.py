from __future__ import annotations

from datetime import datetime, timezone

from quant.live.runtime_state import StrategyRuntimeState
from quant.live.store import list_live_events
from quant.live.translate import GatewayOrder, GatewayPosition, GatewayTrade


def test_runtime_state_persists_snapshot_once_and_updates_pdt(tmp_path):
    state = StrategyRuntimeState()
    db_path = tmp_path / "live.sqlite3"
    snapshot = {
        "orders": [GatewayOrder("O1", "AAPL", "空", "平", 101, 100, 100, "全部成交")],
        "trades": [GatewayTrade("T1", "O1", "AAPL", "空", "平", 101, 100, "2026-06-23T10:00:00+00:00")],
        "positions": [GatewayPosition("AAPL", "多", 0, 101, 10)],
    }
    at = datetime(2026, 6, 23, 10, 1, tzinfo=timezone.utc)

    state.persist_gateway_snapshot(snapshot, at, db_path)
    state.persist_gateway_snapshot(snapshot, at, db_path)

    assert len(list_live_events(db_path=db_path)) == 3
    assert state.pdt_remaining(at.date()) == 2


def test_runtime_state_tracks_intraday_and_portfolio_flags():
    state = StrategyRuntimeState()

    state.mark_intraday_open("aapl")
    state.mark_intraday_half_taken("AAPL")
    state.mark_stopped("AAPL")
    state.mark_portfolio_entry_submitted("AAPL", "first")

    assert state.owns_intraday_symbol("AAPL")
    assert state.intraday_half_done("AAPL")
    assert "AAPL" in state.stopped_symbols_today
    assert state.next_portfolio_stage("AAPL") == "add"

    state.mark_intraday_closed("AAPL")

    assert not state.owns_intraday_symbol("AAPL")
    assert not state.intraday_half_done("AAPL")


def test_equity_baseline_and_daily_loss_pct():
    from datetime import date
    from quant.live.runtime_state import StrategyRuntimeState

    state = StrategyRuntimeState()
    day = date(2026, 6, 24)
    state.observe_account_equity(1000.0, day)
    state.observe_account_equity(900.0, day)  # 基线只取当日第一次
    assert state.daily_loss_pct(900.0) == -10.0


def test_daily_loss_pct_without_baseline_is_zero():
    from quant.live.runtime_state import StrategyRuntimeState

    assert StrategyRuntimeState().daily_loss_pct(900.0) == 0.0


def test_trip_halt_latches_until_day_reset():
    from datetime import date
    from quant.live.runtime_state import StrategyRuntimeState

    state = StrategyRuntimeState()
    day = date(2026, 6, 24)
    state.observe_account_equity(1000.0, day)
    assert state.trip_halt_if_breached(965.0, 3.0) is True  # -3.5% 触发
    assert state.is_halted() is True
    assert state.trip_halt_if_breached(1000.0, 3.0) is True  # 回升仍闩锁
    assert state.is_halted() is True
    state.reset_for_day(date(2026, 6, 25))
    assert state.is_halted() is False


def test_trip_halt_not_breached():
    from datetime import date
    from quant.live.runtime_state import StrategyRuntimeState

    state = StrategyRuntimeState()
    state.observe_account_equity(1000.0, date(2026, 6, 24))
    assert state.trip_halt_if_breached(980.0, 3.0) is False  # -2%
    assert state.is_halted() is False
