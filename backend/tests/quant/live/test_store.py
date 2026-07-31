from __future__ import annotations

from datetime import datetime, timezone

from quant.live.store import (
    LiveEvent,
    count_history_kline_usage,
    get_or_create_history_kline_daily_budget,
    list_live_events,
    record_history_kline_usage,
    record_live_event,
    save_live_event,
)


def test_live_store_round_trips_event(tmp_path):
    db_path = tmp_path / "live.sqlite3"
    event = LiveEvent(
        id="E1",
        kind="log",
        strategy_id="intraday_macd",
        symbol="AAPL",
        created_at=datetime(2026, 6, 23, 9, 30, tzinfo=timezone.utc),
        payload={"message": "风控通过"},
    )

    save_live_event(event, db_path)
    rows = list_live_events(db_path=db_path)

    assert rows == [event]


def test_live_store_lists_newest_first_and_filters_kind(tmp_path):
    db_path = tmp_path / "live.sqlite3"
    record_live_event(
        kind="log",
        strategy_id="intraday_macd",
        payload={"message": "old"},
        created_at=datetime(2026, 6, 23, 9, 30, tzinfo=timezone.utc),
        db_path=db_path,
    )
    newer = record_live_event(
        kind="signal",
        strategy_id="trend_portfolio",
        payload={"symbol": "AAPL"},
        symbol="AAPL",
        created_at=datetime(2026, 6, 23, 9, 31, tzinfo=timezone.utc),
        db_path=db_path,
    )

    assert list_live_events(db_path=db_path)[0].id == newer.id
    assert list_live_events(kind="signal", db_path=db_path) == [newer]
    assert list_live_events(kind="trade", db_path=db_path) == []


def test_live_store_limits_results(tmp_path):
    db_path = tmp_path / "live.sqlite3"
    for index in range(3):
        record_live_event(
            kind="log",
            strategy_id="intraday_macd",
            payload={"index": index},
            created_at=datetime(2026, 6, 23, 9, 30 + index, tzinfo=timezone.utc),
            db_path=db_path,
        )

    rows = list_live_events(limit=2, db_path=db_path)

    assert len(rows) == 2
    assert rows[0].payload["index"] == 2


def test_history_kline_usage_counts_unique_symbols_per_day_and_source(tmp_path):
    db_path = tmp_path / "live.sqlite3"
    requested_at = datetime(2026, 7, 18, 2, 0, tzinfo=timezone.utc)

    record_history_kline_usage("AAPL", "auto", requested_at, db_path)
    record_history_kline_usage("AAPL", "auto", requested_at, db_path)
    record_history_kline_usage("MSFT", "auto", requested_at, db_path)
    record_history_kline_usage("TSLA", "auto:US", requested_at, db_path)
    record_history_kline_usage("00700.HK", "auto:HK", requested_at, db_path)
    record_history_kline_usage("0700.HK", "manual", requested_at, db_path)

    assert count_history_kline_usage(requested_at.date(), "auto", db_path) == 2
    assert count_history_kline_usage(
        requested_at.date(), "auto", db_path, source_prefix=True
    ) == 4
    assert count_history_kline_usage(requested_at.date(), "manual", db_path) == 1


def test_history_kline_daily_budget_uses_and_preserves_opening_balance(tmp_path):
    db_path = tmp_path / "live.sqlite3"
    trading_day = datetime(2026, 7, 18, tzinfo=timezone.utc).date()

    first = get_or_create_history_kline_daily_budget(
        trading_day, opening_remaining=50, reserve=20, window_days=7, db_path=db_path
    )
    refreshed = get_or_create_history_kline_daily_budget(
        trading_day, opening_remaining=10, reserve=20, window_days=7, db_path=db_path
    )

    assert first == {
        "opening_remaining": 50,
        "reserve": 20,
        "daily_auto_limit": 4,
    }
    assert refreshed == first


def test_history_kline_daily_budget_keeps_reserve_out_of_auto_selection(tmp_path):
    db_path = tmp_path / "live.sqlite3"

    reserved = get_or_create_history_kline_daily_budget(
        datetime(2026, 7, 19, tzinfo=timezone.utc).date(),
        opening_remaining=20,
        reserve=20,
        window_days=7,
        db_path=db_path,
    )
    small_balance = get_or_create_history_kline_daily_budget(
        datetime(2026, 7, 20, tzinfo=timezone.utc).date(),
        opening_remaining=25,
        reserve=20,
        window_days=7,
        db_path=db_path,
    )

    assert reserved["daily_auto_limit"] == 0
    assert small_balance["daily_auto_limit"] == 1
