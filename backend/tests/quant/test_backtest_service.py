from types import SimpleNamespace

import pandas as pd
import pytest

from app.models.schemas import BacktestRequest
from quant.backtest.service import run_backtest


def _trend_fetch(symbol, market, start, end):
    idx = pd.date_range("2024-01-01", periods=120, freq="D")
    close = [100 + i * 0.5 for i in range(120)]
    return pd.DataFrame(
        {
            "Open": close,
            "High": [value * 1.01 for value in close],
            "Low": [value * 0.99 for value in close],
            "Close": close,
            "Volume": [1_000_000] * 120,
        },
        index=idx,
    )


def _empty_minute_fetch(symbol, market, start, end, interval):
    return pd.DataFrame()


def _empty_fetch(symbol, market, start, end):
    raise RuntimeError("source unavailable")


def _minute_fetch(symbol, market, start, end, interval):
    assert interval == "1m"
    indexes = [
        pd.date_range(f"2024-01-0{day} 09:30", periods=390, freq="min", tz="America/New_York")
        for day in (2, 3)
    ]
    index = indexes[0].append(indexes[1])
    close = [100 + offset * 0.01 for offset in range(len(index))]
    return pd.DataFrame(
        {
            "Open": close,
            "High": [value + 0.1 for value in close],
            "Low": [value - 0.1 for value in close],
            "Close": close,
            "Volume": [1_000] * len(index),
        },
        index=index,
    )

def test_trend_backtest_uses_price_data():
    result = run_backtest(
        BacktestRequest(
            strategy_id="trend_portfolio",
            market="US",
            start_date="2024-01-01",
            end_date="2024-05-01",
            symbols=["AAPL"],
            initial_capital=100_000,
        ),
        fetcher=_trend_fetch,
    )

    assert result.total_return_pct > 0
    assert result.trades >= 1
    assert result.trade_rows
    first_trade = result.trade_rows[0]
    assert first_trade.symbol == "AAPL"
    assert first_trade.entry_time
    assert first_trade.exit_time
    assert first_trade.position_size == 100_000
    assert first_trade.quantity > 0
    assert first_trade.pnl > 0
    assert result.equity_curve
    assert result.equity_curve[0].equity == 100_000
    assert result.equity_curve[-1].equity > result.equity_curve[0].equity
    assert any("日线趋势代理回测" in note for note in result.notes)


def test_backtest_uses_strategy_position_param_for_trade_size():
    result = run_backtest(
        BacktestRequest(
            strategy_id="trend_portfolio",
            market="US",
            start_date="2024-01-01",
            end_date="2024-05-01",
            symbols=["AAPL", "MSFT"],
            initial_capital=100_000,
            params_snapshot={"single_position_cap_pct": 15},
            symbols_source="当前候选股票池",
        ),
        fetcher=_trend_fetch,
    )

    assert result.trade_rows
    assert {row.symbol for row in result.trade_rows} == {"AAPL", "MSFT"}
    assert all(row.position_size == 15_000 for row in result.trade_rows)
    assert all(row.symbols_source == "当前候选股票池" for row in result.trade_rows)
    assert all(row.position_source == "策略参数 single_position_cap_pct=15%" for row in result.trade_rows)


def test_intraday_backtest_does_not_fall_back_to_daily_proxy():
    result = run_backtest(
        BacktestRequest(
            strategy_id="intraday_macd",
            market="HK",
            start_date="2024-01-01",
            end_date="2024-02-15",
            symbols=["0700.HK"],
            initial_capital=100_000,
            params_snapshot={"position_fraction_pct": 20},
            symbols_source="日内选股（自动筛选）",
        ),
        fetcher=_empty_fetch,
        minute_fetcher=_empty_minute_fetch,
    )

    assert result.trade_rows == []
    assert any("日内策略不使用日线代理" in note for note in result.notes)
    assert not any("日线代理" in note and "回退" in note for note in result.notes)


@pytest.mark.parametrize(
    ("entry_action", "expected_side", "exit_momentum"),
    [("enter_long", "long", "falling"), ("enter_short", "short", "rising")],
)
def test_intraday_minute_backtest_reuses_live_long_and_short_logic(
    monkeypatch,
    entry_action,
    expected_side,
    exit_momentum,
):
    def fake_entry_signal(**kwargs):
        at = kwargs["at"]
        action = entry_action if at.day == 2 and at.hour == 10 and at.minute == 30 else "wait"
        return SimpleNamespace(action=action)

    monkeypatch.setattr("quant.backtest.service.evaluate_intraday_entry_signal", fake_entry_signal)
    monkeypatch.setattr(
        "quant.backtest.service.three_period_macd_momentum",
        lambda *args, **kwargs: exit_momentum,
    )

    result = run_backtest(
        BacktestRequest(
            strategy_id="intraday_macd",
            market="US",
            start_date="2024-01-02",
            end_date="2024-01-04",
            symbols=["AAPL"],
            initial_capital=100_000,
            params_snapshot={
                "fast_ema": 2,
                "slow_ema": 3,
                "signal_ema": 2,
                "position_fraction_pct": 20,
                "open_after_minutes": 30,
                "close_before_minutes": 90,
            },
        ),
        fetcher=_empty_fetch,
        minute_fetcher=_minute_fetch,
    )

    assert len(result.trade_rows) == 1
    trade = result.trade_rows[0]
    assert trade.side == expected_side
    assert trade.entry_time.endswith("10:30:00")
    assert trade.exit_time.endswith("10:33:00")
    assert trade.position_size == 20_000
    assert trade.entry_reason.startswith("15/5/3分钟 MACD 柱同步")
    assert "三周期 MACD 柱同步" in trade.exit_reason
    assert any("复用实盘多空与退出逻辑" in note for note in result.notes)

def test_empty_intraday_candidate_pool_runs_auto_selection(monkeypatch):
    monkeypatch.setattr(
        "quant.backtest.service.get_universe",
        lambda market: [
            SimpleNamespace(symbol="AAPL", market="US"),
            SimpleNamespace(symbol="MSFT", market="US"),
        ],
    )
    minute_symbols: list[str] = []

    def daily_fetch(symbol, market, start, end):
        idx = pd.date_range("2024-01-01", periods=25, freq="D")
        close = [100.0] * 25
        high = [101.0] * 25
        low = [99.0] * 25
        volume = [100_000] * 25
        if symbol == "MSFT":
            volume = [1] * 25
        return pd.DataFrame(
            {"Open": close, "High": high, "Low": low, "Close": close, "Volume": volume},
            index=idx,
        )

    def minute_fetch(symbol, market, start, end, interval):
        minute_symbols.append(symbol)
        return pd.DataFrame()

    result = run_backtest(
        BacktestRequest(
            strategy_id="intraday_macd",
            market="US",
            start_date="2024-01-01",
            end_date="2024-02-01",
            symbols=[],
            symbols_mode="auto",
            initial_capital=100_000,
            params_snapshot={
                "min_turnover": 5_000_000,
                "min_amplitude_pct": 1,
                "max_amplitude_pct": 3,
                "min_price": 2,
            },
        ),
        fetcher=daily_fetch,
        minute_fetcher=minute_fetch,
    )

    assert minute_symbols == ["AAPL"]
    assert any("自动选股策略" in note for note in result.notes)


def test_custom_empty_candidate_pool_does_not_auto_select(monkeypatch):
    monkeypatch.setattr(
        "quant.backtest.service.get_universe",
        lambda market: [SimpleNamespace(symbol="AAPL", market="US")],
    )
    result = run_backtest(
        BacktestRequest(
            strategy_id="intraday_macd",
            market="US",
            start_date="2024-01-01",
            end_date="2024-02-01",
            symbols=[],
            symbols_mode="custom",
            initial_capital=100_000,
            symbols_source="自选候选池",
        ),
        fetcher=_trend_fetch,
        minute_fetcher=_minute_fetch,
    )

    assert result.trade_rows == []
    assert any("自选候选池为空" in note for note in result.notes)
    assert not any("自动选股策略" in note for note in result.notes)


def test_backtest_returns_empty_result_when_all_data_fails():
    result = run_backtest(
        BacktestRequest(
            strategy_id="intraday_macd",
            market="US",
            start_date="2024-01-01",
            end_date="2024-05-01",
            symbols=["AAPL"],
            initial_capital=100_000,
        ),
        fetcher=_empty_fetch,
        minute_fetcher=_empty_minute_fetch,
    )

    assert result.total_return_pct == 0
    assert result.trades == 0
    assert result.trade_rows == []
    assert result.equity_curve == []
    assert any("AAPL 1分钟线不足" in note for note in result.notes)
