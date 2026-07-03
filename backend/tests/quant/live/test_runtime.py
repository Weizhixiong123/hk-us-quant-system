from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from quant.data.universe import SymbolInfo
from quant.live.market_data import Bar
from quant.live.runtime import (
    DryRunGateway,
    LiveRuntime,
    RuntimeConfig,
    build_live_runtime_from_env,
)
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
            for index in range(30)
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


def test_build_live_runtime_uses_broker_env(monkeypatch):
    live_state = LiveGatewayState()
    monkeypatch.setenv("LIVE_RUNTIME_BROKER", "tiger")
    monkeypatch.setenv("LIVE_RUNTIME_DRY_RUN", "1")

    runtime = build_live_runtime_from_env(live_state)

    assert runtime.config.broker == "tiger"
    assert isinstance(runtime.gateway, DryRunGateway)


def test_build_live_runtime_rejects_unknown_broker(monkeypatch):
    import pytest

    monkeypatch.setenv("LIVE_RUNTIME_BROKER", "unknown")

    with pytest.raises(ValueError, match="LIVE_RUNTIME_BROKER"):
        build_live_runtime_from_env(LiveGatewayState())


def test_build_live_runtime_uses_settings_file(monkeypatch, tmp_path):
    from quant.live.settings import save_live_settings

    path = tmp_path / "live-settings.json"
    save_live_settings(
        {
            "runtime": {"broker": "tiger", "enabled": True},
            "tiger": {"markets": ["US", "HK"]},
        },
        path,
    )
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(path))
    monkeypatch.delenv("LIVE_RUNTIME_BROKER", raising=False)
    monkeypatch.delenv("LIVE_RUNTIME_ENABLED", raising=False)
    monkeypatch.delenv("LIVE_RUNTIME_MARKETS", raising=False)

    runtime = build_live_runtime_from_env(LiveGatewayState())

    assert runtime.config.broker == "tiger"
    assert runtime.config.enabled is True
    assert runtime.scheduler.markets == ("US", "HK")


def test_build_live_runtime_uses_saved_manual_intraday_universe(monkeypatch, tmp_path):
    from quant.live.settings import save_live_settings

    path = tmp_path / "live-settings.json"
    save_live_settings(
        {
            "runtime": {"broker": "tiger"},
            "tiger": {"markets": ["US"]},
            "intraday_universe": {
                "selection_mode": "manual",
                "manual_symbols": [
                    {"symbol": "TSLA", "name": "Tesla", "market": "US", "shortable": True}
                ],
            },
        },
        path,
    )
    monkeypatch.setenv("LIVE_SETTINGS_PATH", str(path))
    monkeypatch.setenv("LIVE_RUNTIME_DRY_RUN", "1")
    monkeypatch.delenv("LIVE_RUNTIME_BROKER", raising=False)
    monkeypatch.delenv("LIVE_RUNTIME_MARKETS", raising=False)

    runtime = build_live_runtime_from_env(LiveGatewayState())

    assert runtime.runtime_state.intraday_watchlist == ["TSLA"]
    assert [item.symbol for item in runtime.data_provider.intraday_symbols] == ["TSLA"]
    assert runtime._is_shortable("TSLA") is True


def test_runtime_premarket_scan_subscribes_and_persists_selection(tmp_path):
    runtime, gateway = _runtime(tmp_path)
    at = datetime(2026, 6, 23, 9, 0, tzinfo=timezone.utc)

    runtime._run_intraday_premarket_scan(at)

    assert runtime.runtime_state.intraday_watchlist == ["AAPL"]
    assert gateway.subscribed == ["AAPL"]
    events = list_live_events(kind="selection", db_path=tmp_path / "live.sqlite3")
    assert events[0].payload["symbols"] == ["AAPL"]


def test_manual_intraday_universe_bypasses_premarket_screener(tmp_path):
    live_state = LiveGatewayState()
    runtime = LiveRuntime(
        live_state=live_state,
        gateway=DryRunGateway(live_state),
        scheduler=LiveScheduler(markets=("US",)),
        data_provider=FakeDataProvider(),
        market_data=FakeMarketData(),
        runtime_state=StrategyRuntimeState(),
        config=RuntimeConfig(enabled=True, dry_run=True),
        db_path=tmp_path / "live.sqlite3",
        manual_intraday_symbols=[SymbolInfo("TSLA", "Tesla", "US", shortable=True)],
    )

    runtime._run_intraday_premarket_scan(datetime(2026, 6, 23, 9, 0, tzinfo=timezone.utc))

    assert runtime.runtime_state.intraday_watchlist == ["TSLA"]
    assert runtime._is_shortable("TSLA") is True
    event = list_live_events(kind="selection", db_path=tmp_path / "live.sqlite3")[0]
    assert event.payload["selection_mode"] == "manual"
    assert event.payload["names"] == {"TSLA": "Tesla"}


def test_runtime_catches_up_missed_us_premarket_scan(tmp_path):
    live_state = LiveGatewayState()
    gateway = DryRunGateway(live_state)
    runtime = LiveRuntime(
        live_state=live_state,
        gateway=gateway,
        scheduler=LiveScheduler(markets=("US",)),
        data_provider=FakeDataProvider(),
        market_data=FakeMarketData(),
        runtime_state=StrategyRuntimeState(),
        config=RuntimeConfig(enabled=True, dry_run=True),
        db_path=tmp_path / "live.sqlite3",
    )
    gateway.connect()

    runtime.run_once(datetime(2026, 6, 23, 13, 3, tzinfo=timezone.utc))

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


def test_runtime_force_close_only_closes_owned_intraday_positions(tmp_path):
    runtime, gateway = _runtime(tmp_path)
    gateway.send_order("AAPL", "多", "开", 100, 10)
    gateway.send_order("MSFT", "多", "开", 100, 10)
    runtime.runtime_state.mark_intraday_open("AAPL")

    runtime._force_close_intraday_positions(
        "US",
        datetime(2026, 6, 23, 19, 50, tzinfo=timezone.utc),
    )

    positions = runtime.live_state.snapshot()["positions"]
    assert [position.symbol for position in positions] == ["MSFT"]
    assert not runtime.runtime_state.owns_intraday_symbol("AAPL")
    events = list_live_events(kind="signal", db_path=tmp_path / "live.sqlite3")
    assert events[0].payload["reasons"] == ["尾盘强制清仓"]


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


def test_three_period_momentum_detects_falling(tmp_path):
    runtime, _gateway = _runtime(tmp_path)
    # 先涨后加速下跌 → 三周期最后一根柱均低于上一根
    closes = list(range(1, 31)) + [30 - x * x * 0.3 for x in range(30)]
    bars = [
        Bar("AAPL", datetime(2026, 6, 24, 9, i, tzinfo=timezone.utc), c, c + 1, c - 1, c, 100)
        for i, c in enumerate(closes)
    ]

    class _MD:
        def interval_bars(self, symbol, interval_minutes, limit=100):
            return bars

    runtime.market_data = _MD()
    assert runtime._three_period_momentum("AAPL") == "falling"


def test_three_period_momentum_insufficient_bars_is_mixed(tmp_path):
    runtime, _gateway = _runtime(tmp_path)

    class _MD:
        def interval_bars(self, symbol, interval_minutes, limit=100):
            return []

    runtime.market_data = _MD()
    assert runtime._three_period_momentum("AAPL") == "mixed"


def test_intraday_short_entry_for_shortable_symbol(tmp_path, monkeypatch):
    from types import SimpleNamespace

    runtime, gateway = _runtime(tmp_path)
    runtime.runtime_state.intraday_watchlist = ["AAPL"]  # universe 中 AAPL shortable=True

    monkeypatch.setattr(
        "quant.live.runtime.evaluate_intraday_entry_signal",
        lambda **kwargs: SimpleNamespace(action="enter_short", side="short"),
    )

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
        lambda **kwargs: SimpleNamespace(action="enter_short", side="short"),
    )

    runtime._run_intraday_entries("US", datetime(2026, 6, 24, 14, 15, tzinfo=timezone.utc))
    assert runtime.live_state.snapshot()["positions"] == []


def test_runtime_uses_injected_params_for_entry(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from quant.live.params import LiveParams

    params = LiveParams()
    params.update("intraday_macd", {"position_fraction_pct": 25.0})

    runtime, _gateway = _runtime(tmp_path)
    runtime.params = params
    runtime.runtime_state.intraday_watchlist = ["AAPL"]

    captured = {}

    def fake_execute(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(submitted=False, reasons=("x",))

    monkeypatch.setattr("quant.live.runtime.evaluate_intraday_entry_signal", lambda **k: SimpleNamespace(action="enter_long"))
    monkeypatch.setattr("quant.live.runtime.execute_intraday_entry", fake_execute)

    runtime._run_intraday_entries("US", datetime(2026, 6, 24, 14, 15, tzinfo=timezone.utc))
    assert captured["position_fraction_pct"] == 25.0


def test_portfolio_entry_passes_hot_gain_block_pct_to_signal(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from quant.live.params import LiveParams

    runtime, _gateway = _runtime(tmp_path)
    runtime.params.update("trend_portfolio", {"hot_gain_block_pct": 55.0})
    runtime.runtime_state.portfolio_watchlist = ["0700.HK"]

    captured = {}

    def fake_evaluate(symbol, timing, stage, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(action="wait", symbol=symbol, stage=None, pullback_confirmed=False)

    monkeypatch.setattr("quant.live.runtime.evaluate_trend_entry_signal", fake_evaluate)

    class _DP(FakeDataProvider):
        def daily_timing(self, symbol, market):
            return SimpleNamespace(close=100.0)

    runtime.data_provider = _DP()
    at = datetime(2026, 6, 24, 20, 5, tzinfo=timezone.utc)
    runtime._run_portfolio_entries("HK", at)

    assert captured.get("hot_gain_block_pct") == 55.0


def test_portfolio_entry_records_entry_date(tmp_path, monkeypatch):
    from types import SimpleNamespace

    runtime, gateway = _runtime(tmp_path)
    runtime.runtime_state.portfolio_watchlist = ["0700.HK"]

    monkeypatch.setattr(
        "quant.live.runtime.evaluate_trend_entry_signal",
        lambda symbol, timing, stage, **kw: SimpleNamespace(
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


def test_dry_run_gateway_simulates_cash_account():
    live_state = LiveGatewayState()
    gateway = DryRunGateway(live_state, initial_cash=1_000_000.0)
    gateway.connect()

    # 买入 AAPL 100 股 @100 → 现金扣 10000，持仓市值 10000，权益不变
    gateway.send_order("AAPL", "多", "开", price=100.0, volume=100)
    account = live_state.snapshot()["account"]
    assert account is not None
    assert account.available == 990_000.0
    assert account.balance == 1_000_000.0

    # 卖出平仓 @120 → 回笼 12000，已实现盈利 2000，无持仓
    gateway.send_order("AAPL", "空", "平", price=120.0, volume=100)
    account = live_state.snapshot()["account"]
    assert account.available == 1_002_000.0
    assert account.balance == 1_002_000.0


def test_run_once_runs_off_event_loop_thread(tmp_path):
    """run_once 是同步阻塞函数,必须在工作线程跑,否则会卡住整个 asyncio event loop。"""
    import asyncio
    import threading

    runtime, _gateway = _runtime(tmp_path)
    main_thread = threading.get_ident()
    seen: dict = {}

    def record(at):
        seen["thread"] = threading.get_ident()
        runtime._running = False  # 跑一次即停循环

    runtime.run_once = record

    async def scenario():
        await runtime.start()
        await asyncio.sleep(0.1)
        await runtime.stop()

    asyncio.run(scenario())

    assert "thread" in seen
    assert seen["thread"] != main_thread  # 在工作线程执行,没有阻塞 event loop


def test_observe_account_writes_day_pnl(tmp_path):
    from quant.live.translate import GatewayAccount

    runtime, _gateway = _runtime(tmp_path)
    live_state = runtime.live_state
    at = datetime(2026, 6, 26, 10, 0, tzinfo=timezone.utc)

    # 当日首次回报 → 记基线 100000,当日盈亏 0
    live_state.update_account(GatewayAccount("ACC1", 100_000, 50_000, 50_000))
    runtime._observe_account(live_state.snapshot(), at)
    assert live_state.snapshot()["account"].day_pnl == 0

    # 权益涨到 103000 → 当日盈亏 +3000(券商账户没这字段,由 runtime 按基线算)
    live_state.update_account(GatewayAccount("ACC1", 103_000, 50_000, 53_000))
    runtime._observe_account(live_state.snapshot(), at)
    assert live_state.snapshot()["account"].day_pnl == 3_000
