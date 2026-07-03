from quant.live.gateway import (
    _clean_symbol,
    _futu_setting_from_config,
    _install_pandas_append_compat,
    _resolve_exchange,
    _tiger_setting_from_config,
)


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


def test_resolve_exchange_infers_market_for_bare_symbols():
    assert _resolve_exchange("00700", "US", _Exchange) == "SEHK"
    assert _resolve_exchange("AAPL", "HK", _Exchange) == "SMART"


def test_resolve_exchange_uses_config_market_and_explicit_override():
    assert _resolve_exchange("00700", "HK", _Exchange) == "SEHK"
    assert _resolve_exchange("AAPL", "US", _Exchange) == "SMART"
    assert _resolve_exchange("AAPL", "US", _Exchange, "NASDAQ") == "NASDAQ"


def test_resolve_exchange_allows_gateway_specific_us_default():
    assert (
        _resolve_exchange("AAPL.US", "HK", _Exchange, us_default_exchange="NASDAQ")
        == "NASDAQ"
    )


def test_pandas_append_compat_supports_legacy_futu_history_adapter():
    import pandas as pd

    original = getattr(pd.DataFrame, "append", None)
    try:
        if original is not None:
            delattr(pd.DataFrame, "append")
        _install_pandas_append_compat()

        result = pd.DataFrame({"value": [1]}).append(
            pd.DataFrame({"value": [2]}), ignore_index=True
        )

        assert result["value"].tolist() == [1, 2]
    finally:
        if original is None:
            delattr(pd.DataFrame, "append")
        else:
            pd.DataFrame.append = original


def test_tiger_setting_maps_config_keys():
    from quant.live.config import TigerGatewayConfig

    config = TigerGatewayConfig(
        tiger_id="tid",
        account="acc",
        private_key="key",
        private_key_path="",
        tiger_public_key_path="/tmp/tiger.pub",
        environment="sandbox",
        language="zh_CN",
        max_contracts=50,
        use_preset_contracts=True,
        market="US",
        markets=("US",),
        paper=True,
        live_trading_confirmed=False,
    )

    setting = _tiger_setting_from_config(config)

    assert setting == {
        "tiger_id": "tid",
        "account": "acc",
        "private_key": "key",
        "private_key_path": "",
        "tiger_public_key_path": "/tmp/tiger.pub",
        "environment": "sandbox",
        "language": "zh_CN",
        "max_contracts": "50",
        "use_preset_contracts": "true",
    }


def test_futu_setting_maps_vnpy_futu_chinese_keys():
    from quant.live.config import FutuGatewayConfig

    config = FutuGatewayConfig(
        host="127.0.0.1",
        port=11111,
        trd_env="SIMULATE",
        market="HK",
        markets=("HK", "US"),
        paper=True,
        real_trading_confirmed=False,
    )

    setting = _futu_setting_from_config(config)

    assert setting == {
        "密码": "",
        "地址": "127.0.0.1",
        "端口": 11111,
        "市场": "HK",
        "环境": "SIMULATE",
    }


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


def test_bars_from_vnpy_skips_bar_with_none_datetime():
    """Finding 2: _bars_from_vnpy must drop any raw bar whose datetime is None."""
    from datetime import datetime, timezone

    from quant.live.gateway import _bars_from_vnpy

    dt = datetime(2026, 6, 24, 9, 30, tzinfo=timezone.utc)

    class _GoodBar:
        datetime = dt
        open_price = 1.0
        high_price = 2.0
        low_price = 0.5
        close_price = 1.5
        volume = 100.0

    class _NullBar:
        datetime = None
        open_price = 0.0
        high_price = 0.0
        low_price = 0.0
        close_price = 0.0
        volume = 0.0

    bars = _bars_from_vnpy("AAPL", [_NullBar(), _GoodBar(), _NullBar()])
    assert len(bars) == 1
    assert bars[0].start == dt


def test_query_history_minute_requires_connection():
    import pytest

    from quant.live.config import FutuGatewayConfig
    from quant.live.gateway import FutuLiveGateway
    from quant.live.state import LiveGatewayState

    config = FutuGatewayConfig(
        "127.0.0.1",
        11111,
        "SIMULATE",
        "HK",
        ("HK",),
        True,
        False,
    )
    gateway = FutuLiveGateway(config, LiveGatewayState())
    with pytest.raises(RuntimeError):
        gateway.query_history_minute("AAPL")


def test_futu_connect_fails_fast_when_opend_is_unavailable(monkeypatch):
    import pytest

    from quant.live.config import FutuGatewayConfig
    from quant.live.gateway import FutuLiveGateway
    from quant.live.state import LiveGatewayState

    config = FutuGatewayConfig(
        "127.0.0.1",
        11111,
        "SIMULATE",
        "HK",
        ("HK",),
        True,
        False,
    )
    state = LiveGatewayState()
    gateway = FutuLiveGateway(config, state)

    def refuse_connection(*args, **kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(
        "quant.live.gateway.socket.create_connection",
        refuse_connection,
    )

    with pytest.raises(ConnectionError, match="切换到干跑模式"):
        gateway.connect()

    assert state.snapshot()["connected"] is False
    assert "FutuOpenD" in state.snapshot()["detail"]


def test_tiger_query_history_minute_requires_connection():
    import pytest

    from quant.live.config import TigerGatewayConfig
    from quant.live.gateway import TigerLiveGateway
    from quant.live.state import LiveGatewayState

    config = TigerGatewayConfig(
        "",
        "",
        "",
        "",
        "",
        "sandbox",
        "zh_CN",
        100,
        False,
        "US",
        ("US",),
        True,
        False,
    )
    gateway = TigerLiveGateway(config, LiveGatewayState())
    with pytest.raises(RuntimeError):
        gateway.query_history_minute("AAPL")

