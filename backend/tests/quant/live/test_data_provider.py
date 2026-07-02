from __future__ import annotations

from datetime import date

import pandas as pd

from quant.data.universe import SymbolInfo
from quant.live.data_provider import DefaultLiveDataProvider
from quant.live.market_data import BarAggregator
from quant.live.translate import GatewayTick


def _daily(symbol: str, market: str, start: str, end: str) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=90, freq="D")
    close = pd.Series([100 + item * 0.1 for item in range(90)], index=index)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": [100_000] * 90,
        },
        index=index,
    )


def test_default_data_provider_builds_intraday_candidates_from_daily_and_tick():
    market_data = BarAggregator()
    market_data.ingest_tick(GatewayTick("AAPL", 123.0, 1_000, "2026-06-23T10:00:00+00:00"))
    provider = DefaultLiveDataProvider(
        market_data=market_data,
        symbols=[SymbolInfo("AAPL", "Apple", "US")],
        daily_loader=_daily,
        today=date(2026, 6, 23),
    )

    candidates = provider.intraday_candidates()

    assert candidates[0].symbol == "AAPL"
    assert candidates[0].price == 123.0
    assert candidates[0].avg_turnover > 0


def test_intraday_candidates_can_use_a_separate_manual_universe():
    provider = DefaultLiveDataProvider(
        market_data=BarAggregator(),
        symbols=[SymbolInfo("AAPL", "Apple", "US")],
        intraday_symbols=[SymbolInfo("TSLA", "Tesla", "US")],
        daily_loader=_daily,
        today=date(2026, 6, 23),
    )

    assert [item.symbol for item in provider.intraday_candidates()] == ["TSLA"]


def test_default_data_provider_builds_daily_timing_snapshot():
    provider = DefaultLiveDataProvider(
        market_data=BarAggregator(),
        symbols=[SymbolInfo("AAPL", "Apple", "US")],
        daily_loader=_daily,
        today=date(2026, 6, 23),
    )

    timing = provider.daily_timing("AAPL", "US")

    assert timing is not None
    assert timing.ma20 > 0
    assert timing.ma30 > 0
    assert timing.avg_volume20 == 100_000


def test_intraday_candidates_use_market_info():
    from quant.live.market_info import MarketInfoProvider, SymbolMarketInfo

    provider = DefaultLiveDataProvider(
        market_data=BarAggregator(),
        symbols=[SymbolInfo("AAPL", "Apple", "US")],
        daily_loader=_daily,
        today=date(2026, 6, 23),
        market_info=MarketInfoProvider(source=lambda s: SymbolMarketInfo(halted=True, ex_dividend_soon=False)),
    )

    assert provider.intraday_candidates()[0].halted is True


def test_portfolio_rows_use_real_fundamentals():
    from quant.data.fundamentals import RawFundamentals

    provider = DefaultLiveDataProvider(
        market_data=BarAggregator(),
        symbols=[SymbolInfo("0700.HK", "腾讯", "HK")],
        daily_loader=_daily,
        today=date(2026, 6, 23),
        fundamentals_source=lambda s, m: RawFundamentals(market_cap=6e9, positive_profit_quarters=4),
    )

    rows = provider.portfolio_rows()
    assert rows[0][3].market_cap == 6e9
    assert rows[0][3].positive_profit_quarters == 4
