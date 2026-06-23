from __future__ import annotations

from datetime import datetime, timezone

from quant.live.store import LiveEvent, list_live_events, record_live_event, save_live_event


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
