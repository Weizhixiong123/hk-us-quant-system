from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.state import AppState
from quant.live.state import LiveGatewayState
from quant.live.translate import (
    GatewayAccount,
    GatewayLog,
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
    live_state.update_log(
        GatewayLog(
            "L1",
            "2026-06-23T10:00:30+00:00",
            "FUTU_US",
            "warning",
            "委托失败：账户不支持交易 US.AAPL",
        )
    )

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
    assert dashboard.logs[1].source == "FUTU_US"
    assert dashboard.logs[1].severity == "warning"


def test_order_is_not_marked_filled_without_dealt_quantity():
    live_state = LiveGatewayState()
    live_state.update_order(
        GatewayOrder("O-MARKET", "AAPL", "多", "开", 0, 1, 0, "全部成交")
    )

    order = AppState(live_state).dashboard().orders[0]

    assert order.status == "submitted"


def test_app_state_dashboard_does_not_show_seed_data_without_live_account():
    state = AppState(LiveGatewayState())

    dashboard = state.dashboard()

    assert dashboard.positions == []
    assert dashboard.orders == []
    assert dashboard.trades == []
    assert dashboard.risk[0].status == "blocked"


def test_intraday_strategies_declare_cross_strategy_position_exclusivity():
    state = AppState(LiveGatewayState())
    strategies = {strategy.id: strategy for strategy in state.strategies}

    rule = "同一标的跨策略排他，已有仓位优先"
    assert rule in strategies["intraday_macd"].risk_controls
    assert rule in strategies["ma_atr_intraday"].risk_controls


def test_switching_to_an_enabled_strategy_pauses_all_others():
    state = AppState()

    enabled = state.set_strategy_enabled("ma_atr_intraday", True)
    strategies = {strategy.id: strategy for strategy in state.strategies}

    assert enabled.enabled is True
    assert enabled.state == "running"
    assert strategies["intraday_macd"].enabled is False
    assert strategies["intraday_macd"].state == "paused"
    assert strategies["trend_portfolio"].enabled is False
    assert strategies["trend_portfolio"].state == "idle"


def test_update_strategy_params_syncs_live_params():
    from quant.live.params import LiveParams
    from quant.live.state import LiveGatewayState
    from app.services.state import AppState

    params = LiveParams()
    state = AppState(LiveGatewayState(), params)
    state.update_strategy_params(
        "intraday_macd",
        {"stop_loss_pct": 2.5, "max_daily_loss_pct": 4.0, "max_positions": 5},
    )
    assert params.intraday.stop_loss_pct == 2.5
    assert state.dashboard().account.max_daily_loss_pct == 4.0
    risk = {item.code: item for item in state.risk_status()}
    assert risk["daily_loss"].detail.endswith("阈值 -4.00%")
    assert risk["intraday_position_count"].detail.endswith("/5")


def test_update_strategy_params_persists_when_enabled(monkeypatch, tmp_path):
    from app.services.state import AppState
    from quant.live.params import LiveParams

    settings_path = tmp_path / "live-settings.json"
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_path))

    state = AppState(params=LiveParams(), persist_strategy_params=True)
    state.update_strategy_params(
        "intraday_macd",
        {"fast_ema": 8, "slow_ema": 21, "signal_ema": 5},
    )

    restored = AppState(params=LiveParams(), persist_strategy_params=True)
    assert restored.params.intraday.fast_ema == 8
    assert restored.params.intraday.slow_ema == 21


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


def test_risk_counts_only_positions_opened_by_intraday_strategy(tmp_path):
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    record_live_event(
        kind="signal",
        strategy_id="intraday_macd",
        symbol="AAPL",
        payload={"submitted": True, "reasons": ["日内开仓"]},
        db_path=db,
    )
    record_live_event(
        kind="signal",
        strategy_id="trend_portfolio",
        symbol="0700.HK",
        payload={"submitted": True, "reasons": ["中长线建仓"]},
        db_path=db,
    )
    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=700_000, frozen=300_000)
    )
    live_state.update_position(GatewayPosition("AAPL", "多", 100, 100, 0))
    live_state.update_position(GatewayPosition("HK.00700", "多", 100, 300, 0))
    live_state.update_position(GatewayPosition("MSFT", "多", 100, 200, 0))

    dashboard = AppState(live_state, db_path=db).dashboard()
    strategies = {position.symbol: position.strategy_id for position in dashboard.positions}
    intraday = next(item for item in dashboard.risk if item.code == "intraday_position_count")

    assert strategies == {
        "AAPL": "intraday_macd",
        "HK.00700": "trend_portfolio",
        "MSFT": "live",
    }
    assert intraday.detail == "1/3"


def test_live_position_strategy_can_be_restored_from_open_trade_event(tmp_path):
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    record_live_event(
        kind="trade",
        strategy_id="intraday_macd",
        symbol="AAPL",
        payload={
            "event": "trade",
            "symbol": "AAPL",
            "direction": "多",
            "offset": "开",
            "volume": 100,
            "price": 100,
        },
        db_path=db,
    )
    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=900_000, frozen=100_000)
    )
    live_state.update_position(GatewayPosition("AAPL", "多", 100, 100, 0))

    dashboard = AppState(live_state, db_path=db).dashboard()

    assert dashboard.positions[0].strategy_id == "intraday_macd"
    assert dashboard.orders == []


def test_dashboard_watchlist_from_live_signals(tmp_path):
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    record_live_event(
        kind="signal",
        strategy_id="intraday_macd",
        symbol="AAPL",
        payload={"submitted": False, "reasons": ["15m 缩量", "5m 金叉"]},
        db_path=db,
    )

    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=1_000_000, frozen=0)
    )
    state = AppState(live_state, db_path=db)

    watchlist = state.dashboard().watchlist
    aapl = next(w for w in watchlist if w.symbol == "AAPL")
    assert aapl.market == "US"
    assert aapl.tags == ["15m 缩量", "5m 金叉"]
    assert aapl.triggered is False


def test_dashboard_watchlist_ignores_order_block_signal_for_candidate_score(tmp_path):
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        payload={
            "market": "US",
            "symbols": ["AAPL"],
            "selection_mode": "auto",
            "score_components": {
                "AAPL": {
                    "consistency": 1.0,
                    "daily_volume_ratio": 2.0,
                    "prev_amplitude_pct": 4.0,
                    "avg_turnover": 150_000_000,
                }
            },
        },
        db_path=db,
    )
    record_live_event(
        kind="signal",
        strategy_id="intraday_macd",
        symbol="AAPL",
        payload={"submitted": False, "reasons": ["下单失败：券商未返回订单号"]},
        db_path=db,
    )

    row = AppState(LiveGatewayState(), db_path=db).dashboard().watchlist[0]

    assert row.symbol == "AAPL"
    assert row.score > 0.5
    assert row.strategy_id == "intraday_macd"
    assert row.tags == ["盘前筛选", "等待 15m 收线确认"]


def test_dashboard_watchlist_marks_submitted_signal_triggered_today(tmp_path):
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    record_live_event(
        kind="signal",
        strategy_id="intraday_macd",
        symbol="AAPL",
        payload={"submitted": True, "reasons": ["15m 金叉"]},
        db_path=db,
    )
    record_live_event(
        kind="signal",
        strategy_id="intraday_macd",
        symbol="AAPL",
        payload={"submitted": False, "reasons": ["持仓观察"]},
        db_path=db,
    )

    live_state = LiveGatewayState()
    live_state.update_position(GatewayPosition("AAPL", "多", 100, 100, 0))
    watchlist = AppState(live_state, db_path=db).dashboard().watchlist

    assert len(watchlist) == 1
    assert watchlist[0].triggered is True


def test_dashboard_watchlist_does_not_trigger_rejected_order_without_position(tmp_path):
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    record_live_event(
        kind="signal",
        strategy_id="intraday_macd",
        symbol="AAPL",
        payload={"submitted": True, "reasons": ["日内仓位检查通过"]},
        db_path=db,
    )

    watchlist = AppState(LiveGatewayState(), db_path=db).dashboard().watchlist

    assert len(watchlist) == 1
    assert watchlist[0].triggered is False


def test_dashboard_watchlist_includes_live_selection_events(monkeypatch, tmp_path):
    from quant.live.store import record_live_event
    from quant.live.settings import save_live_settings

    db = tmp_path / "live.sqlite3"
    settings_path = tmp_path / "live-settings.json"
    save_live_settings({"intraday_universe": {"selection_mode": "auto"}}, settings_path)
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_path))
    created_at = datetime(2026, 6, 25, 13, 0, tzinfo=timezone.utc)
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=created_at,
        payload={"symbols": ["AAPL", "MSFT"], "candidate_count": 2, "selection_mode": "auto"},
        db_path=db,
    )

    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=1_000_000, frozen=0)
    )
    state = AppState(live_state, db_path=db)

    watchlist = state.dashboard().watchlist

    assert [item.symbol for item in watchlist] == ["AAPL", "MSFT"]
    assert watchlist[0].tags == ["盘前筛选", "等待 15m 收线确认"]
    assert watchlist[0].updated_at == created_at


def test_dashboard_watchlist_labels_manual_selection(monkeypatch, tmp_path):
    from quant.live.store import record_live_event
    from quant.live.settings import save_live_settings

    db = tmp_path / "live.sqlite3"
    settings_path = tmp_path / "live-settings.json"
    save_live_settings(
        {
            "intraday_universe": {
                "selection_mode": "manual",
                "manual_symbols": [
                    {"symbol": "TSLA", "name": "Tesla", "market": "US", "shortable": False}
                ],
            }
        },
        settings_path,
    )
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_path))
    created_at = datetime(2026, 6, 24, 9, 0, tzinfo=timezone.utc)
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=created_at,
        payload={
            "symbols": ["TSLA"],
            "selection_mode": "manual",
            "names": {"TSLA": "Tesla"},
        },
        db_path=db,
    )

    watchlist = AppState(LiveGatewayState(), db_path=db).dashboard().watchlist

    assert watchlist[0].name == "Tesla"
    assert watchlist[0].tags == ["手动选股", "等待 MACD 开仓信号"]


def test_dashboard_watchlist_labels_manual_auto_selection(monkeypatch, tmp_path):
    from quant.live.settings import save_live_settings
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    settings_path = tmp_path / "live-settings.json"
    save_live_settings(
        {"intraday_universe": {"selection_mode": "manual", "manual_symbols": [{"symbol": "TSLA", "name": "Tesla", "market": "US", "shortable": True}]}},
        settings_path,
    )
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_path))
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=datetime(2026, 6, 24, 13, 0, tzinfo=timezone.utc),
        payload={
            "market": "US",
            "symbols": ["TSLA", "AAPL"],
            "selection_mode": "manual+auto",
            "manual_symbols": ["TSLA"],
            "auto_symbols": ["AAPL"],
            "names": {"TSLA": "Tesla"},
        },
        db_path=db,
    )

    watchlist = AppState(LiveGatewayState(), db_path=db).dashboard().watchlist

    assert [item.symbol for item in watchlist] == ["TSLA", "AAPL"]
    assert watchlist[0].name == "Tesla"
    assert watchlist[0].tags == ["手动+筛选", "等待 15m 收线确认"]


def test_dashboard_watchlist_removes_deleted_manual_symbol_but_keeps_auto(monkeypatch, tmp_path):
    from quant.live.settings import save_live_settings
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    settings_path = tmp_path / "live-settings.json"
    save_live_settings(
        {"intraday_universe": {"selection_mode": "manual", "manual_symbols": []}},
        settings_path,
    )
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_path))
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=datetime(2026, 7, 4, 14, 0, tzinfo=timezone.utc),
        payload={
            "market": "US",
            "symbols": ["TSLA", "AAPL"],
            "selection_mode": "manual+auto",
            "manual_symbols": ["TSLA"],
            "auto_symbols": ["AAPL"],
        },
        db_path=db,
    )

    watchlist = AppState(LiveGatewayState(), db_path=db).dashboard().watchlist

    assert [item.symbol for item in watchlist] == ["AAPL"]


def test_dashboard_watchlist_only_shows_latest_selection_for_current_mode(monkeypatch, tmp_path):
    from quant.live.settings import save_live_settings
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    settings_path = tmp_path / "live-settings.json"
    save_live_settings(
        {
            "intraday_universe": {
                "selection_mode": "manual",
                "manual_symbols": [
                    {"symbol": "TSLA", "name": "Tesla", "market": "US", "shortable": False}
                ],
            }
        },
        settings_path,
    )
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_path))
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=datetime(2026, 6, 24, 8, 0, tzinfo=timezone.utc),
        payload={"symbols": ["AAPL", "MSFT"], "selection_mode": "auto"},
        db_path=db,
    )
    record_live_event(
        kind="signal",
        strategy_id="intraday_macd",
        symbol="AAPL",
        created_at=datetime(2026, 6, 24, 8, 30, tzinfo=timezone.utc),
        payload={"submitted": False, "reasons": ["旧自动信号"]},
        db_path=db,
    )
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=datetime(2026, 6, 24, 9, 0, tzinfo=timezone.utc),
        payload={"symbols": ["TSLA"], "selection_mode": "manual"},
        db_path=db,
    )

    watchlist = AppState(LiveGatewayState(), db_path=db).dashboard().watchlist

    assert [item.symbol for item in watchlist] == ["TSLA"]


def test_dashboard_watchlist_keeps_latest_selection_per_market(tmp_path):
    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=datetime(2026, 6, 24, 1, 0, tzinfo=timezone.utc),
        payload={"market": "HK", "symbols": ["0700.HK"], "selection_mode": "auto"},
        db_path=db,
    )
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=datetime(2026, 6, 24, 13, 0, tzinfo=timezone.utc),
        payload={"market": "US", "symbols": ["AAPL"], "selection_mode": "auto"},
        db_path=db,
    )

    watchlist = AppState(LiveGatewayState(), db_path=db).dashboard().watchlist

    assert [item.symbol for item in watchlist] == ["AAPL", "0700.HK"]


    from quant.live.store import record_live_event

    db = tmp_path / "live.sqlite3"
    record_live_event(
        kind="signal",
        strategy_id="intraday_macd",
        symbol="AAPL",
        payload={"submitted": True, "reasons": ["5m 金叉"]},
        db_path=db,
    )

    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=1_000_000, frozen=0)
    )
    state = AppState(live_state, db_path=db)

    aapl = next(s for s in state.dashboard().signals if s.symbol == "AAPL")
    assert aapl.strategy_id == "intraday_macd"
    assert aapl.reason == "5m 金叉"
    assert aapl.status == "executed"


def test_broker_account_day_pnl_from_gateway():
    live_state = LiveGatewayState()
    # 券商账户回报:当日盈亏 +2000(权益 102000,当日基线 100000)
    live_state.update_account(
        GatewayAccount("ACC1", balance=102_000, available=50_000, frozen=52_000, day_pnl=2_000)
    )

    account = AppState(live_state).dashboard().account

    assert account.source == "broker"
    assert account.day_pnl == 2_000  # 不再写死 0,来自券商账户
    assert account.day_pnl_pct == 2.0  # 2000 / (102000-2000) * 100


def test_dashboard_keeps_hk_and_us_accounts_separate():
    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("HK-ACC", 998_819, 600_000, 398_819, 1_200, "HK", "HKD")
    )
    live_state.update_account(
        GatewayAccount("US-ACC", 993_378, 500_000, 493_378, -320, "US", "USD")
    )

    dashboard = AppState(live_state).dashboard()

    assert [(item.market, item.account_id) for item in dashboard.accounts] == [
        ("HK", "HK-ACC"),
        ("US", "US-ACC"),
    ]
    assert dashboard.accounts[0].total_equity == 998_819
    assert dashboard.accounts[1].total_equity == 993_378
    assert dashboard.account.market == "HK"


def test_updating_us_account_does_not_replace_primary_hk_account():
    live_state = LiveGatewayState()
    live_state.update_account(GatewayAccount("HK-ACC", 998_819, 600_000, 398_819, market="HK"))
    live_state.update_account(GatewayAccount("US-ACC", 993_378, 500_000, 493_378, market="US"))
    live_state.update_account(GatewayAccount("US-ACC", 990_000, 500_000, 490_000, market="US"))

    snapshot = live_state.snapshot()

    assert snapshot["account"].account_id == "HK-ACC"
    assert {item.market: item.balance for item in snapshot["accounts"]} == {
        "HK": 998_819,
        "US": 990_000,
    }


def test_position_risk_setting_is_only_saved_for_an_open_position(tmp_path):
    live_state = LiveGatewayState()
    live_state.update_position(GatewayPosition("AAPL", "多", 100, 100, 0))
    state = AppState(live_state, db_path=tmp_path / "live.sqlite3")

    saved = state.set_position_risk_setting("US", "AAPL", 2.0, 2.5, True)
    position = state.current_positions()[0]

    assert saved["stop_loss_pct"] == 2.0
    assert saved["take_profit_r"] == 2.5
    assert position.risk_setting is not None
    assert position.risk_setting.active is True


def test_position_risk_setting_rejects_symbol_without_position(tmp_path):
    import pytest

    state = AppState(LiveGatewayState(), db_path=tmp_path / "live.sqlite3")

    with pytest.raises(KeyError):
        state.set_position_risk_setting("US", "AAPL", 2.0, 2.5, True)


def test_position_risk_setting_rejects_position_with_pending_close_order(tmp_path):
    import pytest

    live_state = LiveGatewayState()
    live_state.update_position(GatewayPosition("AAPL", "多", 100, 100, 0))
    live_state.update_order(GatewayOrder("CLOSE-1", "AAPL", "空", "平", 99, 100, 0, "已提交"))
    state = AppState(live_state, db_path=tmp_path / "live.sqlite3")

    with pytest.raises(ValueError, match="已有平仓委托"):
        state.set_position_risk_setting("US", "AAPL", 2.0, 2.5, True)


def test_dashboard_watchlist_score_is_no_longer_hardcoded_072(monkeypatch, tmp_path):
    """回归测试:watchlist 不再统一写 0.72 — 至少有 score_components 全 1 的输入时分数应当显著高。"""
    from quant.live.store import record_live_event
    from quant.live.settings import save_live_settings

    db = tmp_path / "live.sqlite3"
    settings_path = tmp_path / "live-settings.json"
    save_live_settings({"intraday_universe": {"selection_mode": "auto"}}, settings_path)
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_path))
    # 用「未来 1 小时」时刻确保 freshness ≈ 1,不受系统时钟影响
    fresh_at = datetime.now(timezone.utc) + timedelta(hours=1)
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=fresh_at,
        payload={
            "symbols": ["AAPL"],
            "candidate_count": 1,
            "selection_mode": "auto",
            "score_components": {
                "AAPL": {
                    "consistency": 1.0,
                    "daily_volume_ratio": 2.0,
                    "intraday_volume_ratio": 1.0,
                    "prev_amplitude_pct": 4.0,
                    "price_vs_ma20_pct": 2.0,
                    "price_vs_ma30_pct": 2.0,
                    "short_term_gain_pct": 10.0,
                    "avg_turnover": 150_000_000.0,
                }
            },
        },
        db_path=db,
    )

    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=1_000_000, frozen=0)
    )
    rows = AppState(live_state, db_path=db).dashboard().watchlist

    assert len(rows) == 1
    assert rows[0].score != 0.72  # 不再是写死的常量
    assert rows[0].freshness > 0.99  # fresh_at 在未来,freshness 钳到 1
    assert rows[0].score_breakdown["weighted"] >= 0.95
    assert rows[0].score >= 0.95    # 全优输入 → 接近满分


def test_dashboard_watchlist_breakdown_exposes_5_dims(monkeypatch, tmp_path):
    """score_breakdown 必须含五维 + weighted 六个键。"""
    from quant.live.store import record_live_event
    from quant.live.settings import save_live_settings

    db = tmp_path / "live.sqlite3"
    settings_path = tmp_path / "live-settings.json"
    save_live_settings({"intraday_universe": {"selection_mode": "auto"}}, settings_path)
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(settings_path))
    fresh_at = datetime.now(timezone.utc) + timedelta(hours=1)
    record_live_event(
        kind="selection",
        strategy_id="intraday_macd",
        created_at=fresh_at,
        payload={
            "symbols": ["AAPL"],
            "selection_mode": "auto",
            "score_components": {
                "AAPL": {
                    "consistency": 0.9,
                    "daily_volume_ratio": 1.6,
                    "intraday_volume_ratio": 0.8,
                    "prev_amplitude_pct": 5.0,
                    "price_vs_ma20_pct": 1.5,
                    "price_vs_ma30_pct": 1.5,
                    "short_term_gain_pct": 12.0,
                    "avg_turnover": 80_000_000.0,
                }
            },
        },
        db_path=db,
    )

    live_state = LiveGatewayState()
    live_state.update_account(
        GatewayAccount("DRY-RUN", balance=1_000_000, available=1_000_000, frozen=0)
    )
    rows = AppState(live_state, db_path=db).dashboard().watchlist

    bd = rows[0].score_breakdown
    assert bd is not None
    assert set(bd) == {"consistency", "volume_ratio", "atr_quality",
                       "trend_filter", "liquidity_rank", "weighted"}
    assert bd["consistency"] == 0.9
    assert 0.0 <= rows[0].score <= 1.0
    assert 0.0 <= rows[0].freshness <= 1.0
    # AAPL 不在 manual 列表里,shortable 默认 False
    assert rows[0].shortable is False
