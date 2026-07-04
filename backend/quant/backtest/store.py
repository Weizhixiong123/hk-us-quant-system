from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from app.models.schemas import BacktestResult

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "backtests.sqlite3"
DbPath = str | os.PathLike[str]


def save_backtest_result(
    result: BacktestResult,
    db_path: DbPath | None = None,
) -> BacktestResult:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = result.model_dump(mode="json")

    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT OR REPLACE INTO backtest_results (
                id,
                created_at,
                strategy_id,
                market,
                start_date,
                end_date,
                total_return_pct,
                max_drawdown_pct,
                sharpe,
                win_rate_pct,
                trades,
                payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.id,
                payload["created_at"],
                result.strategy_id,
                result.market,
                result.start_date,
                result.end_date,
                result.total_return_pct,
                result.max_drawdown_pct,
                result.sharpe,
                result.win_rate_pct,
                result.trades,
                json.dumps(payload, ensure_ascii=False),
            ),
        )

    return result


def list_backtest_results(
    limit: int = 20,
    db_path: DbPath | None = None,
) -> list[BacktestResult]:
    path = _resolve_db_path(db_path)
    if not path.exists():
        return []

    safe_limit = max(1, min(limit, 100))
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT payload
            FROM backtest_results
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    return [BacktestResult.model_validate(json.loads(row[0])) for row in rows]


def get_backtest_result(
    result_id: str,
    db_path: DbPath | None = None,
) -> BacktestResult | None:
    path = _resolve_db_path(db_path)
    if not path.exists():
        return None

    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT payload
            FROM backtest_results
            WHERE id = ?
            """,
            (result_id,),
        ).fetchone()

    if row is None:
        return None
    return BacktestResult.model_validate(json.loads(row[0]))


def _resolve_db_path(db_path: DbPath | None) -> Path:
    if db_path is not None:
        return Path(db_path)

    env_path = os.getenv("BACKTEST_DB_PATH")
    if env_path:
        return Path(env_path)

    return DEFAULT_DB_PATH


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS backtest_results (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            market TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            total_return_pct REAL NOT NULL,
            max_drawdown_pct REAL NOT NULL,
            sharpe REAL NOT NULL,
            win_rate_pct REAL NOT NULL,
            trades INTEGER NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_backtest_results_created_at
        ON backtest_results(created_at DESC)
        """
    )

