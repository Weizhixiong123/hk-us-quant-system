from datetime import datetime, timedelta, timezone

from app.models.schemas import BacktestResult, EquityPoint
from quant.backtest.store import list_backtest_results, save_backtest_result


def _result(result_id: str, created_at: datetime) -> BacktestResult:
    return BacktestResult(
        id=result_id,
        strategy_id="trend_portfolio",
        market="US",
        start_date="2024-01-01",
        end_date="2024-05-01",
        created_at=created_at,
        total_return_pct=12.5,
        max_drawdown_pct=3.2,
        sharpe=1.4,
        win_rate_pct=55.0,
        trades=4,
        equity_curve=[
            EquityPoint(time="2024-01-01T00:00:00", equity=100_000, drawdown_pct=0.0),
            EquityPoint(time="2024-01-02T00:00:00", equity=112_500, drawdown_pct=0.0),
        ],
        notes=["测试报告"],
    )


def test_backtest_store_round_trips_result(tmp_path):
    db_path = tmp_path / "backtests.sqlite3"
    result = _result("BT-STORE1", datetime(2026, 6, 22, tzinfo=timezone.utc))

    save_backtest_result(result, db_path=db_path)
    rows = list_backtest_results(db_path=db_path)

    assert len(rows) == 1
    assert rows[0].id == "BT-STORE1"
    assert rows[0].equity_curve[1].equity == 112_500
    assert rows[0].notes == ["测试报告"]


def test_backtest_store_orders_newest_first_and_limits(tmp_path):
    db_path = tmp_path / "backtests.sqlite3"
    created_at = datetime(2026, 6, 22, tzinfo=timezone.utc)
    save_backtest_result(_result("BT-OLD", created_at - timedelta(days=1)), db_path=db_path)
    save_backtest_result(_result("BT-NEW", created_at), db_path=db_path)

    rows = list_backtest_results(limit=1, db_path=db_path)

    assert [row.id for row in rows] == ["BT-NEW"]

