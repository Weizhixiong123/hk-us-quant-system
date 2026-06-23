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
