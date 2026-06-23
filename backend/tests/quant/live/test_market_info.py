from __future__ import annotations

from quant.live.market_info import MarketInfoProvider, SymbolMarketInfo


def test_no_source_does_not_block():
    assert MarketInfoProvider().lookup("AAPL") == (False, False, False)


def test_news_blocklist_flags_major_news():
    assert MarketInfoProvider(news_blocklist=["AAPL"]).lookup("aapl") == (False, False, True)


def test_source_values_passthrough():
    provider = MarketInfoProvider(source=lambda s: SymbolMarketInfo(halted=True, ex_dividend_soon=False))
    assert provider.lookup("AAPL") == (True, False, False)


def test_configured_source_unknown_symbol_is_conservative():
    provider = MarketInfoProvider(source=lambda s: None)
    assert provider.lookup("AAPL") == (True, False, False)
