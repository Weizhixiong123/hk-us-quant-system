from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from quant.live.market_data import Bar
from quant.live.runtime import DryRunGateway, LiveRuntime, RuntimeConfig
from quant.live.runtime_state import StrategyRuntimeState
from quant.live.scheduler import LiveScheduler
from quant.live.state import LiveGatewayState
from quant.live.store import list_live_events
from quant.screening.intraday_screener import IntradayCandidate


class FakeDataProvider:
    symbols = []

    def intraday_candidates(self):
        return [
            IntradayCandidate(
                symbol="AAPL",
                market="US",
                avg_turnover=8_000_000,
                prev_amplitude_pct=4,
                price=100,
                halted=False,
                ex_dividend_soon=False,
                major_news=False,
            )
        ]

    def portfolio_rows(self):
        return []

    def daily_timing(self, symbol, market):
        return None

    def trend_exit_context(self, symbol, market):
        return SimpleNamespace()


class FakeMarketData:
    def __init__(self):
        self.bars = [
            Bar("AAPL", datetime(2026, 6, 23, 10, index, tzinfo=timezone.utc), 100, 101, 99, 100, index)
            for index in range(26)
        ]

    def ingest_ticks(self, ticks):
        return None

    def interval_bars(self, symbol, interval_minutes, limit=100):
        return self.bars

    def latest_price(self, symbol):
        return 100.0


def _runtime(tmp_path):
    live_state = LiveGatewayState()
    gateway = DryRunGateway(live_state)
    runtime = LiveRuntime(
        live_state=live_state,
        gateway=gateway,
        scheduler=LiveScheduler(markets=()),
        data_provider=FakeDataProvider(),
        market_data=FakeMarketData(),
        runtime_state=StrategyRuntimeState(),
        config=RuntimeConfig(enabled=True, dry_run=True),
        db_path=tmp_path / "live.sqlite3",
    )
    gateway.connect()
    return runtime, gateway


def test_runtime_premarket_scan_subscribes_and_persists_selection(tmp_path):
    runtime, gateway = _runtime(tmp_path)
    at = datetime(2026, 6, 23, 9, 0, tzinfo=timezone.utc)

    runtime._run_intraday_premarket_scan(at)

    assert runtime.runtime_state.intraday_watchlist == ["AAPL"]
    assert gateway.subscribed == ["AAPL"]
    events = list_live_events(kind="selection", db_path=tmp_path / "live.sqlite3")
    assert events[0].payload["symbols"] == ["AAPL"]


def test_runtime_intraday_entry_calls_executor_and_updates_state(tmp_path, monkeypatch):
    runtime, _gateway = _runtime(tmp_path)
    runtime.runtime_state.intraday_watchlist = ["AAPL"]

    monkeypatch.setattr(
        "quant.live.runtime.evaluate_intraday_entry_signal",
        lambda **kwargs: SimpleNamespace(action="enter_long"),
    )

    runtime._run_intraday_entries("US", datetime(2026, 6, 23, 14, 15, tzinfo=timezone.utc))
    snapshot = runtime.live_state.snapshot()

    assert runtime.runtime_state.owns_intraday_symbol("AAPL")
    assert len(snapshot["orders"]) == 1
    assert len(snapshot["trades"]) == 1
    assert snapshot["positions"][0].symbol == "AAPL"


def test_runtime_run_once_persists_gateway_snapshot(tmp_path):
    runtime, gateway = _runtime(tmp_path)
    gateway.send_order("AAPL", "多", "开", 100, 10)

    runtime.run_once(datetime(2026, 6, 23, 14, 16, tzinfo=timezone.utc))

    assert list_live_events(kind="trade", db_path=tmp_path / "live.sqlite3")


def test_seed_history_populates_market_data_once(tmp_path):
    from quant.live.market_data import BarAggregator

    calls: list[str] = []

    class SeedGateway(DryRunGateway):
        def query_history_minute(self, symbol, count=800, exchange=None):
            calls.append(symbol)
            return [
                Bar(symbol, datetime(2026, 6, 23, 9, m, tzinfo=timezone.utc), 100, 100, 100, 100, 100)
                for m in range(20)
            ]

    live_state = LiveGatewayState()
    gateway = SeedGateway(live_state)
    market_data = BarAggregator()
    runtime = LiveRuntime(
        live_state=live_state,
        gateway=gateway,
        scheduler=LiveScheduler(markets=()),
        data_provider=FakeDataProvider(),
        market_data=market_data,
        runtime_state=StrategyRuntimeState(),
        config=RuntimeConfig(enabled=True, dry_run=True),
        db_path=tmp_path / "live.sqlite3",
    )
    runtime._seeded_day = datetime(2026, 6, 23, tzinfo=timezone.utc).date()

    runtime._seed_history(["AAPL"])
    runtime._seed_history(["AAPL"])

    assert market_data.minute_bars("AAPL")
    assert calls == ["AAPL"]  # 当日只补种一次


def test_seed_history_skips_gateway_without_history(tmp_path):
    runtime, _gateway = _runtime(tmp_path)  # DryRunGateway 无 query_history_minute
    runtime._seed_history(["AAPL"])  # 不抛异常即可


def test_seed_history_first_symbol_failure_does_not_abort_second(tmp_path):
    """Finding 1: seed_minute_bars failure on first symbol must not skip second symbol."""
    from quant.live.market_data import BarAggregator

    class FailFirstGateway(DryRunGateway):
        def query_history_minute(self, symbol, count=800, exchange=None):
            if symbol == "AAPL":
                raise ValueError("intentional failure for AAPL")
            return [
                Bar(symbol, datetime(2026, 6, 24, 9, m, tzinfo=timezone.utc), 100, 100, 100, 100, 100)
                for m in range(5)
            ]

    live_state = LiveGatewayState()
    gateway = FailFirstGateway(live_state)
    market_data = BarAggregator()
    runtime = LiveRuntime(
        live_state=live_state,
        gateway=gateway,
        scheduler=LiveScheduler(markets=()),
        data_provider=FakeDataProvider(),
        market_data=market_data,
        runtime_state=StrategyRuntimeState(),
        config=RuntimeConfig(enabled=True, dry_run=True),
        db_path=tmp_path / "live.sqlite3",
    )
    runtime._seeded_day = datetime(2026, 6, 24, tzinfo=timezone.utc).date()

    runtime._seed_history(["AAPL", "MSFT"])

    # Failed symbol must NOT be in _seeded_symbols
    assert "AAPL" not in runtime._seeded_symbols
    # Second symbol must be seeded successfully
    assert "MSFT" in runtime._seeded_symbols
    assert market_data.minute_bars("MSFT")


def test_run_once_trips_halt_on_daily_loss(tmp_path):
    from datetime import date
    from quant.live.translate import GatewayAccount

    runtime, _gateway = _runtime(tmp_path)
    day = date(2026, 6, 24)
    runtime.runtime_state.observe_account_equity(1000.0, day)
    runtime.live_state.update_account(GatewayAccount("acc", 950.0, 950.0, 0.0))

    runtime.run_once(datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc))

    assert runtime.runtime_state.is_halted() is True


def test_seed_history_seed_minute_bars_failure_does_not_abort_second(tmp_path):
    """Finding 1: if seed_minute_bars itself raises (e.g. bad bar), second symbol still seeded."""
    from quant.live.market_data import BarAggregator, Bar as RealBar

    call_count = {"n": 0}

    class RaisingSeedAggregator(BarAggregator):
        def seed_minute_bars(self, symbol, bars):
            if symbol == "AAPL":
                raise TypeError("bad bar for AAPL")
            super().seed_minute_bars(symbol, bars)

    class SimpleGateway(DryRunGateway):
        def query_history_minute(self, symbol, count=800, exchange=None):
            call_count["n"] += 1
            return [
                RealBar(symbol, datetime(2026, 6, 24, 9, m, tzinfo=timezone.utc), 100, 100, 100, 100, 100)
                for m in range(5)
            ]

    live_state = LiveGatewayState()
    gateway = SimpleGateway(live_state)
    market_data = RaisingSeedAggregator()
    runtime = LiveRuntime(
        live_state=live_state,
        gateway=gateway,
        scheduler=LiveScheduler(markets=()),
        data_provider=FakeDataProvider(),
        market_data=market_data,
        runtime_state=StrategyRuntimeState(),
        config=RuntimeConfig(enabled=True, dry_run=True),
        db_path=tmp_path / "live.sqlite3",
    )
    runtime._seeded_day = datetime(2026, 6, 24, tzinfo=timezone.utc).date()

    runtime._seed_history(["AAPL", "MSFT"])

    assert "AAPL" not in runtime._seeded_symbols
    assert "MSFT" in runtime._seeded_symbols
    assert market_data.minute_bars("MSFT")


def test_reverse_cross_long_detects_bearish_cross(tmp_path):
    runtime, _gateway = _runtime(tmp_path)
    # 构造一段先涨后急跌的 15m 收盘价，使 MACD 形成死叉
    closes = (
        [100] * 5 +
        list(range(100, 140)) +       # 强势上涨
        [140] * 10 +                  # 平台期
        list(range(140, 138, -1))     # 小幅下跌
    )[:49]
    bars = [
        Bar("AAPL", datetime(2026, 6, 24, 9, i, tzinfo=timezone.utc), c, c + 1, c - 1, c, 100)
        for i, c in enumerate(closes)
    ]

    class _MD:
        def interval_bars(self, symbol, interval_minutes, limit=100):
            return bars

    runtime.market_data = _MD()
    assert runtime._reverse_cross("AAPL", "long") is True


def test_reverse_cross_insufficient_bars_is_false(tmp_path):
    runtime, _gateway = _runtime(tmp_path)

    class _MD:
        def interval_bars(self, symbol, interval_minutes, limit=100):
            return []

    runtime.market_data = _MD()
    assert runtime._reverse_cross("AAPL", "long") is False


def test_intraday_short_entry_for_shortable_symbol(tmp_path, monkeypatch):
    from types import SimpleNamespace

    runtime, gateway = _runtime(tmp_path)
    runtime.runtime_state.intraday_watchlist = ["AAPL"]  # universe 中 AAPL shortable=True

    def fake_signal(**kwargs):
        if kwargs.get("side") == "short":
            return SimpleNamespace(action="enter_short")
        return SimpleNamespace(action="wait")

    monkeypatch.setattr("quant.live.runtime.evaluate_intraday_entry_signal", fake_signal)

    runtime._run_intraday_entries("US", datetime(2026, 6, 24, 14, 15, tzinfo=timezone.utc))
    snapshot = runtime.live_state.snapshot()

    assert snapshot["positions"][0].symbol == "AAPL"
    assert "空" in snapshot["positions"][0].direction


def test_intraday_short_blocked_for_non_shortable(tmp_path, monkeypatch):
    from types import SimpleNamespace

    runtime, gateway = _runtime(tmp_path)
    runtime.runtime_state.intraday_watchlist = ["NVDA"]  # universe 中 NVDA shortable=False

    monkeypatch.setattr(
        "quant.live.runtime.evaluate_intraday_entry_signal",
        lambda **kwargs: SimpleNamespace(action="enter_short") if kwargs.get("side") == "short" else SimpleNamespace(action="wait"),
    )

    runtime._run_intraday_entries("US", datetime(2026, 6, 24, 14, 15, tzinfo=timezone.utc))
    assert runtime.live_state.snapshot()["positions"] == []


def test_portfolio_entry_records_entry_date(tmp_path, monkeypatch):
    from types import SimpleNamespace

    runtime, gateway = _runtime(tmp_path)
    runtime.runtime_state.portfolio_watchlist = ["0700.HK"]

    monkeypatch.setattr(
        "quant.live.runtime.evaluate_trend_entry_signal",
        lambda symbol, timing, stage: SimpleNamespace(
            action="enter_first", symbol=symbol, stage="first", pullback_confirmed=True
        ),
    )

    class _DP(FakeDataProvider):
        def daily_timing(self, symbol, market):
            return SimpleNamespace(close=100.0)

    runtime.data_provider = _DP()
    at = datetime(2026, 6, 24, 20, 5, tzinfo=timezone.utc)
    runtime._run_portfolio_entries("HK", at)

    assert runtime.runtime_state.holding_days("0700.HK", at.date()) == 0
    assert "0700.HK" in runtime.runtime_state.portfolio_entry_dates
