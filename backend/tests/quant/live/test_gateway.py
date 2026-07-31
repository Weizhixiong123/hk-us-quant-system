from quant.live.gateway import (
    _clean_symbol,
    _futu_gateway_name,
    _futu_route_market,
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
    assert _clean_symbol("7709.HK") == "07709"
    assert _clean_symbol("HK.7747") == "07747"
    assert _clean_symbol("0700.HK") == "00700"
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
    from quant.live.config import FutuAccountConfig, FutuGatewayConfig

    config = FutuGatewayConfig(
        host="127.0.0.1",
        port=11111,
        trd_env="SIMULATE",
        market="HK",
        markets=("HK", "US"),
        paper=True,
        real_trading_confirmed=False,
        accounts=(
            FutuAccountConfig("hk_main", "港股主账户", "127.0.0.1", 11111, ("HK",)),
            FutuAccountConfig("us_main", "美股主账户", "10.0.0.8", 11112, ("US",)),
        ),
        market_accounts=(("HK", "hk_main"), ("US", "us_main")),
    )

    setting = _futu_setting_from_config(config)

    assert setting == {
        "密码": "",
        "地址": "127.0.0.1",
        "端口": 11111,
        "市场": "HK",
        "环境": "SIMULATE",
    }
    assert _futu_setting_from_config(config, "US") == {
        "密码": "",
        "地址": "10.0.0.8",
        "端口": 11112,
        "市场": "US",
        "环境": "SIMULATE",
    }


def test_futu_subscribe_uses_quote_only():
    from quant.live.config import FutuGatewayConfig
    from quant.live.gateway import FutuLiveGateway
    from quant.live.state import LiveGatewayState

    calls = []

    class _QuoteContext:
        def subscribe(self, symbol, data_type, push):
            calls.append((symbol, data_type, push))
            return 0, ""

    class _Gateway:
        quote_ctx = _QuoteContext()

        def write_log(self, message):
            raise AssertionError(message)

    class _MainEngine:
        def get_gateway(self, name):
            assert name == "FUTU_US"
            return _Gateway()

    config = FutuGatewayConfig(
        host="127.0.0.1",
        port=11111,
        trd_env="SIMULATE",
        market="US",
        markets=("US",),
        paper=True,
        real_trading_confirmed=False,
    )
    gateway = FutuLiveGateway(config, LiveGatewayState())
    gateway._main_engine = _MainEngine()
    gateway._gateway_names = {"US": "FUTU_US"}

    gateway.subscribe(["AAPL"])

    assert calls == [("US.AAPL", "QUOTE", True)]


def test_futu_history_kline_quota_returns_used_symbol_details():
    from quant.live.config import FutuGatewayConfig
    from quant.live.gateway import FutuLiveGateway
    from quant.live.state import LiveGatewayState

    class _QuoteContext:
        def get_history_kl_quota(self, get_detail):
            assert get_detail is True
            return 0, (
                2,
                98,
                [
                    {"code": "HK.00700", "request_time": "2026-07-15 09:30:00"},
                    {"code": "US.AAPL", "request_time": "2026-07-17 09:30:00"},
                ],
            )

    class _Gateway:
        quote_ctx = _QuoteContext()

    class _MainEngine:
        def get_gateway(self, name):
            assert name == "FUTU_HK"
            return _Gateway()

    config = FutuGatewayConfig(
        "127.0.0.1", 11111, "SIMULATE", "HK", ("HK",), True, False
    )
    gateway = FutuLiveGateway(config, LiveGatewayState())
    gateway._main_engine = _MainEngine()
    gateway._gateway_names = {"HK": "FUTU_HK"}

    quota = gateway.history_kline_quota()

    assert quota.used == 2
    assert quota.remaining == 98
    assert quota.used_symbols == frozenset({"HK.00700", "US.AAPL"})
    assert quota.next_release_date.isoformat() == "2026-07-22"
    assert quota.next_release_count == 1


def test_futu_routes_each_market_to_its_own_gateway():
    assert _futu_gateway_name("HK") == "FUTU_HK"
    assert _futu_gateway_name("US") == "FUTU_US"
    assert _futu_gateway_name("US", "us-main") == "FUTU_US_MAIN_US"
    assert _futu_route_market("00700.HK", "US") == "HK"
    assert _futu_route_market("AAPL.US", "HK") == "US"
    assert _futu_route_market("AAPL", "HK") == "US"
    assert _futu_route_market("00700", "US") == "HK"
    assert _futu_route_market("00700", "HK", "NASDAQ") == "US"


def test_futu_account_events_are_tagged_by_market():
    from types import SimpleNamespace

    from quant.live.config import FutuGatewayConfig
    from quant.live.gateway import FutuLiveGateway
    from quant.live.state import LiveGatewayState

    state = LiveGatewayState()
    config = FutuGatewayConfig(
        "127.0.0.1", 11111, "SIMULATE", "HK", ("HK", "US"), True, False
    )
    gateway = FutuLiveGateway(config, state)

    gateway._on_account(
        SimpleNamespace(
            type="eAccount.FUTU_HK",
            data=SimpleNamespace(
                gateway_name="FUTU_HK",
                accountid="HK-ACC",
                balance=1_000_000,
                frozen=200_000,
            ),
        )
    )
    gateway._on_account(
        SimpleNamespace(
            type="eAccount.FUTU_US",
            data=SimpleNamespace(
                gateway_name="FUTU_US",
                accountid="US-ACC",
                balance=500_000,
                frozen=100_000,
            ),
        )
    )

    accounts = {item.market: item for item in state.snapshot()["accounts"]}
    assert accounts["HK"].currency == "HKD"
    assert accounts["US"].currency == "USD"


def test_futu_send_order_uses_market_specific_gateway():
    from quant.live.config import FutuGatewayConfig
    from quant.live.gateway import FutuLiveGateway
    from quant.live.state import LiveGatewayState

    class _MainEngine:
        def __init__(self):
            self.calls = []

        def send_order(self, request, gateway_name):
            self.calls.append((request, gateway_name))
            return f"{gateway_name}.ORDER"

    config = FutuGatewayConfig(
        "127.0.0.1", 11111, "SIMULATE", "HK", ("HK", "US"), True, False
    )
    gateway = FutuLiveGateway(config, LiveGatewayState())
    gateway._main_engine = _MainEngine()
    gateway._gateway_names = {"HK": "FUTU_HK", "US": "FUTU_US"}

    us_order = gateway.send_order("AAPL", "多", "开", 200, 10)
    hk_order = gateway.send_order("00700.HK", "多", "开", 400, 100)

    assert us_order == "FUTU_US.ORDER"
    assert hk_order == "FUTU_HK.ORDER"
    assert [call[1] for call in gateway._main_engine.calls] == ["FUTU_US", "FUTU_HK"]


def test_futu_paper_sync_converts_filled_orders_to_incremental_trades():
    import pandas as pd

    from quant.live.config import FutuGatewayConfig
    from quant.live.gateway import FutuLiveGateway
    from quant.live.state import LiveGatewayState

    rows = pd.DataFrame(
        [
            {
                "order_id": "7843139",
                "code": "HK.07709",
                "trd_side": "BUY",
                "dealt_qty": 100,
                "dealt_avg_price": 23.45,
                "updated_time": "2026-07-06 11:55:36",
            }
        ]
    )

    class _TradeContext:
        def order_list_query(self, _status, trd_env):
            assert trd_env == "SIMULATE"
            return 0, rows

    class _Gateway:
        env = "SIMULATE"
        trade_ctx = _TradeContext()

    class _MainEngine:
        def get_gateway(self, name):
            assert name == "FUTU_HK"
            return _Gateway()

    state = LiveGatewayState()
    config = FutuGatewayConfig(
        "127.0.0.1", 11111, "SIMULATE", "HK", ("HK",), True, False
    )
    gateway = FutuLiveGateway(config, state)
    gateway._main_engine = _MainEngine()
    gateway._gateway_names = {"HK": "FUTU_HK"}

    gateway.sync_trades()
    gateway.sync_trades()
    trade = state.snapshot()["trades"][0]

    assert len(state.snapshot()["trades"]) == 1
    assert trade.order_id == "7843139"
    assert trade.symbol == "07709.HK"
    assert trade.volume == 100
    assert trade.price == 23.45


def test_futu_trade_side_maps_sell_and_short_correctly():
    from quant.live.gateway import _futu_trade_direction

    assert _futu_trade_direction("SELL") == ("空", "平")
    assert _futu_trade_direction("SELL_SHORT") == ("空", "开")
    assert _futu_trade_direction("BUY_BACK") == ("多", "平")


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

