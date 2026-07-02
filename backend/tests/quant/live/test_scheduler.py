from __future__ import annotations

from datetime import datetime

from quant.live.clock import HK_TZ, US_TZ
from quant.live.scheduler import LiveScheduler, build_due_actions


def test_scheduler_triggers_hk_premarket_scan():
    actions = build_due_actions(datetime(2026, 6, 23, 9, 0, tzinfo=HK_TZ), markets=("HK",))

    assert [action.hook for action in actions] == ["intraday_premarket_scan"]
    assert actions[0].strategy_id == "intraday_macd"


def test_scheduler_triggers_3m_intraday_signal():
    actions = build_due_actions(datetime(2026, 6, 23, 10, 15, tzinfo=HK_TZ), markets=("HK",))

    assert [action.hook for action in actions] == ["intraday_3m_signal"]


def test_scheduler_skips_non_3m_boundary():
    actions = build_due_actions(datetime(2026, 6, 23, 10, 16, tzinfo=HK_TZ), markets=("HK",))

    assert actions == []


def test_scheduler_skips_intraday_signals_during_hk_lunch_break():
    actions = build_due_actions(datetime(2026, 6, 23, 12, 15, tzinfo=HK_TZ), markets=("HK",))

    assert actions == []


def test_scheduler_no_longer_emits_force_close():
    scheduler = LiveScheduler(markets=("HK",))
    at = datetime(2026, 6, 23, 15, 50, tzinfo=HK_TZ)

    actions = scheduler.due_actions(at)

    assert actions == []


def test_scheduler_triggers_month_end_scan_and_daily_review():
    actions = build_due_actions(datetime(2026, 6, 30, 16, 5, tzinfo=US_TZ), markets=("US",))

    assert [action.hook for action in actions] == [
        "portfolio_month_end_scan",
        "portfolio_daily_review",
    ]
    assert all(action.strategy_id == "trend_portfolio" for action in actions)


def test_scheduler_skips_weekend():
    actions = build_due_actions(datetime(2026, 6, 27, 10, 15, tzinfo=US_TZ), markets=("US",))

    assert actions == []
