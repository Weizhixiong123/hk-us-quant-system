from types import SimpleNamespace

import pandas as pd
import pytest

from app.models.schemas import BacktestRequest
from quant.data.universe import SymbolInfo
from quant.backtest.service import run_backtest


def _trend_fetch(symbol, market, start, end):
    idx = pd.date_range("2018-01-01", periods=2500, freq="D")
    close = [100 + i * 0.05 for i in range(2500)]
    return pd.DataFrame(
        {
            "Open": close,
            "High": [value * 1.01 for value in close],
            "Low": [value * 0.99 for value in close],
            "Close": close,
            "Volume": [1_000_000] * 2500,
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


def _ma_atr_minute_fetch(symbol, market, start, end, interval):
    assert interval == "1m"
    indexes = [
        pd.date_range(f"{day:%Y-%m-%d} 09:30", periods=390, freq="min", tz="America/New_York")
        for day in pd.bdate_range("2024-01-02", periods=6)
    ]
    index = indexes[0]
    for item in indexes[1:]:
        index = index.append(item)
    close = [100 + (offset % 120) * 0.02 for offset in range(len(index))]
    return pd.DataFrame(
        {
            "Open": close,
            "High": [value + 0.2 for value in close],
            "Low": [value - 0.2 for value in close],
            "Close": close,
            "Volume": [2_000] * len(index),
        },
        index=index,
    )


def test_ma_atr_backtest_runs_with_float_params():
    result = run_backtest(
        BacktestRequest(
            strategy_id="ma_atr_intraday",
            market="US",
            start_date="2024-01-01",
            end_date="2024-03-01",
            symbols=["AAPL"],
            initial_capital=100_000,
            params_snapshot={
                "atr_multiplier": 1.4,
                "stop_loss_pct": 2.0,
                "take_profit_pct": 5.0,
                "trailing_start_pct": 2.5,
                "trailing_stop_pct": 1.2,
            },
        ),
        minute_fetcher=_ma_atr_minute_fetch,
    )

    assert result.strategy_id == "ma_atr_intraday"
    assert result.equity_curve
    assert any("MA+MACD+ATR" in note for note in result.notes)

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
    assert first_trade.position_size <= 15_000
    assert first_trade.action in {"open", "add", "reduce", "close"}
    assert first_trade.quantity > 0
    assert any(row.pnl > 0 for row in result.trade_rows if row.action == "close")
    assert result.equity_curve
    assert result.equity_curve[0].equity == 100_000
    assert result.equity_curve[-1].equity > result.equity_curve[0].equity
    assert any("日线趋势代理回测" in note for note in result.notes)


def test_trend_backtest_loads_five_year_warmup_but_reports_requested_period():
    requested_ranges = []

    def fetch(symbol, market, start, end):
        requested_ranges.append((start, end))
        return _trend_fetch(symbol, market, start, end)

    result = run_backtest(
        BacktestRequest(
            strategy_id="trend_portfolio",
            market="US",
            start_date="2024-01-01",
            end_date="2024-05-01",
            symbols=["AAPL"],
            initial_capital=100_000,
        ),
        fetcher=fetch,
    )

    assert requested_ranges == [("2018-09-01", "2024-05-01")]
    assert result.equity_curve
    assert result.equity_curve[0].time >= result.start_date
    assert result.equity_curve[-1].time <= result.end_date
    assert any("60 月均线" in note for note in result.notes)


def test_trend_selection_waits_for_daily_entry_after_month_end(monkeypatch):
    entry_checks = 0

    monkeypatch.setattr(
        "quant.backtest.service._trend_rank_candidates",
        lambda *args, **kwargs: [("AAPL", 1.0)],
    )

    def daily_entry_after_selection(*args, **kwargs):
        nonlocal entry_checks
        entry_checks += 1
        return entry_checks >= 2

    monkeypatch.setattr(
        "quant.backtest.service._trend_daily_entry_ok",
        daily_entry_after_selection,
    )

    result = run_backtest(
        BacktestRequest(
            strategy_id="trend_portfolio",
            market="US",
            start_date="2024-01-01",
            end_date="2024-07-01",
            symbols=["AAPL"],
            initial_capital=100_000,
        ),
        fetcher=_trend_fetch,
    )

    opens = [row for row in result.trade_rows if row.action == "open"]
    assert opens
    assert opens[0].entry_time.startswith("2024-02-01")


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
    assert all(row.position_size <= 15_000 for row in result.trade_rows if row.action in {"open", "add"})
    assert all(row.symbols_source == "当前候选股票池" for row in result.trade_rows)
    assert all("15%" in row.position_source for row in result.trade_rows)


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


def test_intraday_auto_backtest_scans_injected_full_market_universe():
    daily_symbols: list[str] = []
    minute_symbols: list[str] = []

    def daily_fetch(symbol, market, start, end):
        daily_symbols.append(symbol)
        idx = pd.date_range("2024-01-01", periods=25, freq="D")
        close = [100.0] * 25
        return pd.DataFrame(
            {"Open": close, "High": [103.0] * 25, "Low": [99.0] * 25, "Close": close, "Volume": [100_000] * 25},
            index=idx,
        )

    def minute_fetch(symbol, market, start, end, interval):
        minute_symbols.append(symbol)
        return pd.DataFrame()

    universe = [SymbolInfo(f"S{i}", f"Stock {i}", "US") for i in range(4)]
    run_backtest(
        BacktestRequest(
            strategy_id="intraday_macd",
            market="US",
            start_date="2024-01-01",
            end_date="2024-02-01",
            symbols=[],
            symbols_mode="auto",
            initial_capital=100_000,
            params_snapshot={"min_amplitude_pct": 1, "max_amplitude_pct": 5, "backtest_candidate_limit": 2},
        ),
        fetcher=daily_fetch,
        minute_fetcher=minute_fetch,
        universe_provider=lambda market: universe,
    )

    assert set(daily_symbols) == {"S0", "S1", "S2", "S3"}
    assert len(minute_symbols) == 2


def test_trend_auto_backtest_loads_entire_injected_universe():
    loaded: list[str] = []

    def fetch(symbol, market, start, end):
        loaded.append(symbol)
        return _trend_fetch(symbol, market, start, end)

    universe = [SymbolInfo("AAA", "AAA", "US"), SymbolInfo("BBB", "BBB", "US")]
    run_backtest(
        BacktestRequest(
            strategy_id="trend_portfolio",
            market="US",
            start_date="2024-01-01",
            end_date="2024-05-01",
            symbols=[],
            symbols_mode="auto",
            initial_capital=100_000,
        ),
        fetcher=fetch,
        universe_provider=lambda market: universe,
    )

    assert loaded == ["AAA", "BBB"]


def test_default_backtest_daily_data_is_cached(monkeypatch, tmp_path):
    from quant.backtest.service import _load_backtest_daily

    calls = 0

    def load(*args, **kwargs):
        nonlocal calls
        calls += 1
        frame = _trend_fetch(*args[:4])
        return frame.rename(columns=str.lower)

    monkeypatch.setenv("BACKTEST_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("quant.backtest.service.load_daily", load)

    first = _load_backtest_daily("AAPL", "US", "2024-01-01", "2024-02-01", None)
    second = _load_backtest_daily("AAPL", "US", "2024-01-01", "2024-02-01", None)

    assert calls == 1
    assert len(first) == len(second)


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
