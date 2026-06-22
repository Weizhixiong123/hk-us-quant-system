import pytest
from quant.data.universe import SymbolInfo, get_universe, all_symbols


def test_get_universe_us_returns_only_us():
    items = get_universe("US")
    assert items
    assert all(isinstance(i, SymbolInfo) for i in items)
    assert all(i.market == "US" for i in items)


def test_get_universe_unknown_market_raises():
    with pytest.raises(ValueError):
        get_universe("CN")


def test_all_symbols_covers_both_markets():
    markets = {i.market for i in all_symbols()}
    assert markets == {"HK", "US"}
