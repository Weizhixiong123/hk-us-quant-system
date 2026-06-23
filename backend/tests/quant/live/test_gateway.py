from quant.live.gateway import _clean_symbol, _resolve_exchange


class _Exchange:
    SEHK = "SEHK"
    SMART = "SMART"
    NASDAQ = "NASDAQ"


def test_clean_symbol_removes_market_suffix_or_prefix():
    assert _clean_symbol("00700.HK") == "00700"
    assert _clean_symbol("HK.00700") == "00700"
    assert _clean_symbol("AAPL.US") == "AAPL"
    assert _clean_symbol("us.msft") == "MSFT"


def test_resolve_exchange_uses_symbol_market_first():
    assert _resolve_exchange("00700.HK", "US", _Exchange) == "SEHK"
    assert _resolve_exchange("AAPL.US", "HK", _Exchange) == "SMART"


def test_resolve_exchange_uses_config_market_and_explicit_override():
    assert _resolve_exchange("00700", "HK", _Exchange) == "SEHK"
    assert _resolve_exchange("AAPL", "US", _Exchange) == "SMART"
    assert _resolve_exchange("AAPL", "US", _Exchange, "NASDAQ") == "NASDAQ"

