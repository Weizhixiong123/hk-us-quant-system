from __future__ import annotations

from quant.live.trend import (
    DailyTimingSnapshot,
    TrendPosition,
    build_month_end_watchlist,
    evaluate_trend_entry_signal,
    evaluate_trend_exit_signal,
)
from quant.screening.portfolio_screener import PortfolioHit


def _timing(**kwargs):
    base = {
        "close": 101,
        "low": 99.5,
        "ma20": 100,
        "ma30": 98,
        "previous_close": 100,
        "volume": 1_000_000,
        "avg_volume20": 1_000_000,
        "macd_bearish_break": False,
        "macd_recover_cross": False,
        "short_term_gain_pct": 12,
    }
    base.update(kwargs)
    return DailyTimingSnapshot(**base)


def test_month_end_watchlist_keeps_passed_symbols_sorted_by_score(monkeypatch):
    def fake_screen(rows):
        return [
            PortfolioHit("MSFT", "US", True, 0.9, ()),
            PortfolioHit("AAPL", "US", True, 1.0, ()),
            PortfolioHit("TSLA", "US", False, 0.8, ()),
        ]

    monkeypatch.setattr("quant.live.trend.screen_portfolio", fake_screen)

    assert build_month_end_watchlist([]) == ["AAPL", "MSFT"]


def test_trend_entry_first_and_add_require_daily_timing():
    first = evaluate_trend_entry_signal("AAPL", _timing(), stage="first")
    add = evaluate_trend_entry_signal("AAPL", _timing(), stage="add")

    assert first.action == "enter_first"
    assert first.pullback_confirmed is True
    assert add.action == "enter_add"
    assert add.stage == "add"


def test_trend_entry_blocks_macd_break_volume_selloff_and_hot_gain():
    signal = evaluate_trend_entry_signal(
        "AAPL",
        _timing(
            close=97,
            low=96,
            macd_bearish_break=True,
            macd_recover_cross=False,
            previous_close=100,
            volume=2_000_000,
            avg_volume20=1_000_000,
            short_term_gain_pct=45,
        ),
        stage="first",
    )

    assert signal.action == "wait"
    assert "日线回踩 20/30 日均线企稳未满足" in signal.reasons
    assert "MACD 未破位或已重新金叉未满足" in signal.reasons
    assert "无放量大跌未满足" in signal.reasons
    assert "短期涨幅未过热未满足" in signal.reasons


def test_trend_exit_drawdown_has_priority():
    signal = evaluate_trend_exit_signal(
        position=TrendPosition("AAPL", 100, 100, holding_days=10),
        current_price=120,
        symbol_drawdown_pct=18.1,
        monthly_below_ma60_months=2,
    )

    assert signal.action == "exit_all"
    assert signal.quantity == 100
    assert "回撤" in signal.reasons[0]


def test_trend_exit_month_week_macd_and_top_divergence_clear_position():
    position = TrendPosition("AAPL", 100, 100, holding_days=10)

    assert evaluate_trend_exit_signal(position, 101, monthly_below_ma60_months=2).action == "exit_all"
    assert evaluate_trend_exit_signal(position, 101, weekly_ma5=9, weekly_ma10=10).action == "exit_all"
    assert evaluate_trend_exit_signal(position, 101, monthly_macd_dif=-0.1).action == "exit_all"
    assert evaluate_trend_exit_signal(position, 101, top_divergence=True).action == "exit_all"


def test_trend_exit_take_profit_half_once_and_rebalance_cycle():
    half = evaluate_trend_exit_signal(
        position=TrendPosition("AAPL", 101, 100, holding_days=30),
        current_price=121,
    )
    wait = evaluate_trend_exit_signal(
        position=TrendPosition("AAPL", 51, 100, holding_days=31, take_profit_done=True),
        current_price=121,
    )
    rebalance = evaluate_trend_exit_signal(
        position=TrendPosition("AAPL", 51, 100, holding_days=180, take_profit_done=True),
        current_price=121,
    )

    assert half.action == "exit_half"
    assert half.quantity == 50
    assert wait.action == "wait"
    assert rebalance.action == "exit_all"
    assert "调仓周期" in rebalance.reasons[0]
