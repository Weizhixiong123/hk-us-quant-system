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
    calls = []

    def fake_decision(**kwargs):
        calls.append(kwargs)
        action = "long" if kwargs["side"] == "long" else "wait"
        return SimpleNamespace(action=action, confidence=1.0, reasons=("三周期柱同步抬高",))

    monkeypatch.setattr("quant.live.intraday.build_intraday_decision", fake_decision)

    signal = evaluate_intraday_entry_signal(
        symbol="0700.HK",
        market="HK",
        at=datetime(2026, 6, 23, 10, 15, tzinfo=HK_TZ),
        closes_15m=[1.0] * 30,
        closes_5m=[1.0] * 30,
        closes_3m=[1.0] * 30,
    )

    assert calls[0]["within_trade_window"] is True
    assert signal.action == "enter_long"
    assert signal.side == "long"


def test_entry_signal_falls_back_to_short_when_long_waits(monkeypatch):
    def fake_decision(**kwargs):
        action = "short" if kwargs["side"] == "short" else "wait"
        return SimpleNamespace(action=action, confidence=1.0, reasons=("三周期柱同步下降",))

    monkeypatch.setattr("quant.live.intraday.build_intraday_decision", fake_decision)

    signal = evaluate_intraday_entry_signal(
        symbol="AAPL",
        market="US",
        at=datetime(2026, 6, 23, 10, 15, tzinfo=HK_TZ),
        closes_15m=[1.0] * 30,
        closes_5m=[1.0] * 30,
        closes_3m=[1.0] * 30,
    )

    assert signal.action == "enter_short"
    assert signal.side == "short"


def test_exit_signal_long_exits_all_when_momentum_falling():
    signal = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "long", 300, 100),
        momentum="falling",
    )

    assert signal.action == "exit_all"
    assert signal.quantity == 300
    assert "平多" in signal.reasons[0]


def test_exit_signal_short_exits_all_when_momentum_rising():
    signal = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "short", 300, 100),
        momentum="rising",
    )

    assert signal.action == "exit_all"
    assert signal.quantity == 300
    assert "平空" in signal.reasons[0]


def test_exit_signal_waits_when_momentum_same_side():
    long_wait = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "long", 300, 100),
        momentum="rising",
    )
    short_wait = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "short", 300, 100),
        momentum="falling",
    )
    mixed_wait = evaluate_intraday_exit_signal(
        position=IntradayPosition("AAPL", "long", 300, 100),
        momentum="mixed",
    )

    assert long_wait.action == "wait"
    assert short_wait.action == "wait"
    assert mixed_wait.action == "wait"
