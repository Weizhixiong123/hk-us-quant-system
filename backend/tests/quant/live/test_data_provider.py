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
