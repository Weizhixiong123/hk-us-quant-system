import pandas as pd

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


def _empty_fetch(symbol, market, start, end):
    raise RuntimeError("source unavailable")


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
    assert result.equity_curve
    assert result.equity_curve[0].equity == 100_000
    assert result.equity_curve[-1].equity > result.equity_curve[0].equity
    assert any("日线趋势代理回测" in note for note in result.notes)


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
    )

    assert result.total_return_pct == 0
    assert result.trades == 0
    assert result.equity_curve == []
    assert "AAPL 数据加载失败" in result.notes[0]

