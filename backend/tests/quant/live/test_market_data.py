from __future__ import annotations

from quant.live.market_data import BarAggregator
from quant.live.translate import GatewayTick


def test_bar_aggregator_builds_minute_and_interval_bars():
    aggregator = BarAggregator()
    aggregator.ingest_tick(GatewayTick("AAPL", 100.0, 10, "2026-06-23T10:00:03+00:00"))
    aggregator.ingest_tick(GatewayTick("AAPL", 101.0, 12, "2026-06-23T10:00:30+00:00"))
    aggregator.ingest_tick(GatewayTick("AAPL", 99.0, 18, "2026-06-23T10:01:02+00:00"))
    aggregator.flush_open_bars()

    minute_bars = aggregator.minute_bars("AAPL")
    bars_5m = aggregator.interval_bars("AAPL", 5)

    assert len(minute_bars) == 2
    assert minute_bars[0].open == 100.0
    assert minute_bars[0].high == 101.0
    assert minute_bars[0].low == 100.0
    assert minute_bars[0].close == 101.0
    assert bars_5m[0].open == 100.0
    assert bars_5m[0].low == 99.0
    assert bars_5m[0].close == 99.0


def test_bar_aggregator_ignores_duplicate_ticks():
    aggregator = BarAggregator()
    tick = GatewayTick("AAPL", 100.0, 10, "2026-06-23T10:00:03+00:00")

    aggregator.ingest_tick(tick)
    aggregator.ingest_tick(tick)
    aggregator.flush_open_bars()

    assert len(aggregator.minute_bars("AAPL")) == 1
