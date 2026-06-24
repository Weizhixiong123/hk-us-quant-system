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


def test_bars_from_vnpy_maps_fields():
    from datetime import datetime, timezone

    from quant.live.gateway import _bars_from_vnpy

    dt = datetime(2026, 6, 23, 9, 30, tzinfo=timezone.utc)

    class _FakeBar:
        pass

    fake_bar = _FakeBar()
    fake_bar.datetime = dt
    fake_bar.open_price = 1.0
    fake_bar.high_price = 2.0
    fake_bar.low_price = 0.5
    fake_bar.close_price = 1.5
    fake_bar.volume = 100.0

    bars = _bars_from_vnpy("AAPL", [fake_bar])
    assert bars[0].symbol == "AAPL"
    assert bars[0].high == 2.0
    assert bars[0].close == 1.5
    assert bars[0].volume == 100.0


def test_query_history_minute_requires_connection():
    import pytest

    from quant.live.config import FutuGatewayConfig
    from quant.live.gateway import FutuLiveGateway
    from quant.live.state import LiveGatewayState

    config = FutuGatewayConfig("127.0.0.1", 11111, "SIMULATE", "HK", True, False)
    gateway = FutuLiveGateway(config, LiveGatewayState())
    with pytest.raises(RuntimeError):
        gateway.query_history_minute("AAPL")

