from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from quant.live.clock import HK_TZ
from quant.live.intraday import (
    IntradayPosition,
    build_premarket_watchlist,
    evaluate_intraday_entry_signal,
    evaluate_intraday_exit_signal,
)
from quant.screening.intraday_screener import IntradayCandidate


def _candidate(**kwargs):
    base = {
        "symbol": "AAPL",
        "market": "US",
        "avg_turnover": 8_000_000,
        "prev_amplitude_pct": 4.0,
        "price": 180.0,
        "halted": False,
        "ex_dividend_soon": False,
        "major_news": False,
    }
    base.update(kwargs)
    return IntradayCandidate(**base)


def test_premarket_watchlist_keeps_only_passed_candidates():
    watchlist = build_premarket_watchlist(
        [
            _candidate(symbol="AAPL"),
            _candidate(symbol="PENNY", price=1.2),
        ]
    )

    assert watchlist == ["AAPL"]


def test_entry_signal_uses_trade_window_and_maps_long_action(monkeypatch):
    calls = {}

    def fake_decision(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(action="long", confidence=1.0, reasons=("全部条件通过",))

    monkeypatch.setattr("quant.live.intraday.build_intraday_decision", fake_decision)

    signal = evaluate_intraday_entry_signal(
        symbol="0700.HK",
        market="HK",
        at=datetime(2026, 6, 23, 10, 15, tzinfo=HK_TZ),
        closes_15m=[1.0] * 30,
        lows_15m=[1.0] * 30,
        highs_15m=[1.0] * 30,
        closes_5m=[1.0] * 30,
        current_price=100,
        ma5_15m=99,
    )

    assert calls["within_trade_window"] is True
    assert signal.action == "enter_long"
    assert signal.side == "long"


def test_exit_signal_stop_loss_exits_all_and_marks_stopped_today():
    signal = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "long", 300, 100),
        market="HK",
        at=datetime(2026, 6, 23, 15, 50, tzinfo=HK_TZ),
        current_price=98.4,
    )

    assert signal.action == "exit_all"
    assert signal.quantity == 300
    assert signal.stopped_today is True
    assert "止损" in signal.reasons[0]


def test_exit_signal_take_profit_second_level_exits_all():
    signal = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "long", 300, 100),
        market="HK",
        at=datetime(2026, 6, 23, 10, 30, tzinfo=HK_TZ),
        current_price=103.6,
    )

    assert signal.action == "exit_all"
    assert signal.quantity == 300
    assert "第二档止盈" in signal.reasons[0]


def test_exit_signal_reverse_cross_exits_all():
    signal = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "long", 300, 100),
        market="HK",
        at=datetime(2026, 6, 23, 10, 30, tzinfo=HK_TZ),
        current_price=101,
        reverse_cross=True,
    )

    assert signal.action == "exit_all"
    assert "反向交叉" in signal.reasons[0]


def test_exit_signal_force_close_exits_all_before_half_take_profit():
    signal = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "long", 300, 100),
        market="HK",
        at=datetime(2026, 6, 23, 15, 50, tzinfo=HK_TZ),
        current_price=102.2,
    )

    assert signal.action == "exit_all"
    assert signal.quantity == 300
    assert "强制清仓" in signal.reasons[0]


def test_exit_signal_first_take_profit_exits_half_once():
    first = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "long", 301, 100),
        market="HK",
        at=datetime(2026, 6, 23, 10, 30, tzinfo=HK_TZ),
        current_price=102.1,
    )
    second = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "long", 151, 100, first_take_profit_done=True),
        market="HK",
        at=datetime(2026, 6, 23, 10, 35, tzinfo=HK_TZ),
        current_price=102.1,
    )

    assert first.action == "exit_half"
    assert first.quantity == 150
    assert second.action == "wait"
