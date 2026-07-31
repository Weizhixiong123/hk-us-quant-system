from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping
from uuid import uuid4


LiveEventKind = Literal["log", "signal", "selection", "trade", "position"]
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "live.sqlite3"
DbPath = str | os.PathLike[str]


def live_db_path_for_mode(settings: Mapping[str, Any]) -> Path:
    """按运行模式返回独立的数据库文件,实现干跑/模拟盘/实盘物理隔离。"""
    runtime = settings.get("runtime", {})
    if bool(runtime.get("dry_run", True)):
        tag = "dry_run"
    else:
        broker = str(runtime.get("broker", "futu")).lower()
        if broker == "tiger":
            env = str(settings.get("tiger", {}).get("environment", "sandbox")).lower()
        else:
            env = str(settings.get("futu", {}).get("trd_env", "SIMULATE")).lower()
        tag = f"{broker}-{env}"
    return _default_db_path().parent / f"live-{tag}.sqlite3"


@dataclass(frozen=True)
class LiveEvent:
    id: str
    kind: LiveEventKind
    strategy_id: str
    created_at: datetime
    payload: dict[str, Any]
    symbol: str | None = None


def record_live_event(
    kind: LiveEventKind,
    strategy_id: str,
    payload: Mapping[str, Any],
    symbol: str | None = None,
    created_at: datetime | None = None,
    db_path: DbPath | None = None,
) -> LiveEvent:
    event = LiveEvent(
        id=f"LIVE-{uuid4().hex[:10].upper()}",
        kind=kind,
        strategy_id=strategy_id,
        created_at=created_at or datetime.now(timezone.utc),
        payload=dict(payload),
        symbol=symbol,
    )
    return save_live_event(event, db_path)


def save_live_event(event: LiveEvent, db_path: DbPath | None = None) -> LiveEvent:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _event_payload(event)

    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT OR REPLACE INTO live_events (
                id,
                created_at,
                kind,
                strategy_id,
                symbol,
                payload
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                payload["created_at"],
                event.kind,
                event.strategy_id,
                event.symbol,
                json.dumps(payload, ensure_ascii=False),
            ),
        )

    return event


def list_live_events(
    kind: LiveEventKind | None = None,
    limit: int = 50,
    db_path: DbPath | None = None,
) -> list[LiveEvent]:
    path = _resolve_db_path(db_path)
    if not path.exists():
        return []

    safe_limit = max(1, min(limit, 100))
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        if kind is None:
            rows = connection.execute(
                """
                SELECT payload
                FROM live_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT payload
                FROM live_events
                WHERE kind = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (kind, safe_limit),
            ).fetchall()

    return [_event_from_payload(json.loads(row[0])) for row in rows]


def load_account_daily_baseline(
    account_key: str,
    day: date,
    db_path: DbPath | None = None,
) -> float | None:
    path = _resolve_db_path(db_path)
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT equity
            FROM account_daily_baselines
            WHERE account_key = ? AND trading_day = ?
            """,
            (account_key, day.isoformat()),
        ).fetchone()
    return float(row[0]) if row else None


def save_account_daily_baseline(
    account_key: str,
    day: date,
    equity: float,
    db_path: DbPath | None = None,
) -> float:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO account_daily_baselines (account_key, trading_day, equity)
            VALUES (?, ?, ?)
            """,
            (account_key, day.isoformat(), float(equity)),
        )
        row = connection.execute(
            """
            SELECT equity
            FROM account_daily_baselines
            WHERE account_key = ? AND trading_day = ?
            """,
            (account_key, day.isoformat()),
        ).fetchone()
    return float(row[0])


def save_position_risk_setting(
    market: str,
    symbol: str,
    stop_loss_pct: float,
    take_profit_r: float,
    active: bool,
    db_path: DbPath | None = None,
) -> dict[str, Any]:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized_market = market.strip().upper()
    normalized_symbol = symbol.strip().upper()
    updated_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO position_risk_settings (
                market, symbol, stop_loss_pct, take_profit_r, active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(market, symbol) DO UPDATE SET
                stop_loss_pct = excluded.stop_loss_pct,
                take_profit_r = excluded.take_profit_r,
                active = excluded.active,
                updated_at = excluded.updated_at
            """,
            (
                normalized_market,
                normalized_symbol,
                float(stop_loss_pct),
                float(take_profit_r),
                int(active),
                updated_at,
            ),
        )
    return {
        "market": normalized_market,
        "symbol": normalized_symbol,
        "stop_loss_pct": float(stop_loss_pct),
        "take_profit_r": float(take_profit_r),
        "active": bool(active),
        "updated_at": updated_at,
    }


def load_position_risk_setting(
    market: str,
    symbol: str,
    db_path: DbPath | None = None,
) -> dict[str, Any] | None:
    path = _resolve_db_path(db_path)
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT market, symbol, stop_loss_pct, take_profit_r, active, updated_at
            FROM position_risk_settings
            WHERE market = ? AND symbol = ?
            """,
            (market.strip().upper(), symbol.strip().upper()),
        ).fetchone()
    if row is None:
        return None
    return {
        "market": str(row[0]),
        "symbol": str(row[1]),
        "stop_loss_pct": float(row[2]),
        "take_profit_r": float(row[3]),
        "active": bool(row[4]),
        "updated_at": str(row[5]),
    }


def delete_position_risk_setting(
    market: str,
    symbol: str,
    db_path: DbPath | None = None,
) -> None:
    path = _resolve_db_path(db_path)
    if not path.exists():
        return
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        connection.execute(
            "DELETE FROM position_risk_settings WHERE market = ? AND symbol = ?",
            (market.strip().upper(), symbol.strip().upper()),
        )


def record_history_kline_usage(
    symbol: str,
    source: str,
    requested_at: datetime | None = None,
    db_path: DbPath | None = None,
) -> None:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    at = requested_at or datetime.now(timezone.utc)
    local_day = at.astimezone().date() if at.tzinfo is not None else at.date()
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO history_kline_usage (
                trading_day, symbol, source, requested_at
            ) VALUES (?, ?, ?, ?)
            """,
            (local_day.isoformat(), symbol.strip().upper(), source, at.isoformat()),
        )


def count_history_kline_usage(
    trading_day: date,
    source: str,
    db_path: DbPath | None = None,
    *,
    source_prefix: bool = False,
) -> int:
    path = _resolve_db_path(db_path)
    if not path.exists():
        return 0
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        operator = "LIKE" if source_prefix else "="
        source_value = f"{source}%" if source_prefix else source
        row = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM history_kline_usage
            WHERE trading_day = ? AND source {operator} ?
            """,
            (trading_day.isoformat(), source_value),
        ).fetchone()
    return int(row[0]) if row else 0


def get_or_create_history_kline_daily_budget(
    trading_day: date,
    opening_remaining: int,
    reserve: int,
    window_days: int,
    db_path: DbPath | None = None,
) -> dict[str, int]:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT opening_remaining, reserve, daily_auto_limit
            FROM history_kline_daily_budget
            WHERE trading_day = ?
            """,
            (trading_day.isoformat(),),
        ).fetchone()
        if row is None:
            auto_capacity = max(int(opening_remaining) - int(reserve), 0)
            daily_limit = (
                max(auto_capacity // max(int(window_days), 1), 1)
                if auto_capacity > 0
                else 0
            )
            connection.execute(
                """
                INSERT INTO history_kline_daily_budget (
                    trading_day, opening_remaining, reserve, daily_auto_limit
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    trading_day.isoformat(),
                    int(opening_remaining),
                    int(reserve),
                    daily_limit,
                ),
            )
            row = (int(opening_remaining), int(reserve), daily_limit)
    return {
        "opening_remaining": int(row[0]),
        "reserve": int(row[1]),
        "daily_auto_limit": int(row[2]),
    }


def save_history_kline_quota_status(
    status: Mapping[str, Any],
    db_path: DbPath | None = None,
) -> None:
    path = _resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO history_kline_quota_status (id, payload)
            VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
            """,
            (json.dumps(dict(status), ensure_ascii=False),),
        )


def load_history_kline_quota_status(db_path: DbPath | None = None) -> dict[str, Any] | None:
    path = _resolve_db_path(db_path)
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT payload FROM history_kline_quota_status WHERE id = 1"
        ).fetchone()
    return dict(json.loads(row[0])) if row else None


def _resolve_db_path(db_path: DbPath | None) -> Path:
    if db_path is not None:
        return Path(db_path)

    return _default_db_path()


def _default_db_path() -> Path:
    env_path = os.getenv("LIVE_DB_PATH")
    return Path(env_path) if env_path else DEFAULT_DB_PATH


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS live_events (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            symbol TEXT,
            payload TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_live_events_created_at
        ON live_events(created_at DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_live_events_kind_created_at
        ON live_events(kind, created_at DESC)
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS account_daily_baselines (
            account_key TEXT NOT NULL,
            trading_day TEXT NOT NULL,
            equity REAL NOT NULL,
            PRIMARY KEY (account_key, trading_day)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS position_risk_settings (
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            stop_loss_pct REAL NOT NULL,
            take_profit_r REAL NOT NULL,
            active INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (market, symbol)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS history_kline_usage (
            trading_day TEXT NOT NULL,
            symbol TEXT NOT NULL,
            source TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            PRIMARY KEY (trading_day, symbol)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS history_kline_quota_status (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            payload TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS history_kline_daily_budget (
            trading_day TEXT PRIMARY KEY,
            opening_remaining INTEGER NOT NULL,
            reserve INTEGER NOT NULL,
            daily_auto_limit INTEGER NOT NULL
        )
        """
    )


def _event_payload(event: LiveEvent) -> dict[str, Any]:
    payload = asdict(event)
    payload["created_at"] = event.created_at.isoformat()
    return payload


def _event_from_payload(payload: Mapping[str, Any]) -> LiveEvent:
    return LiveEvent(
        id=str(payload["id"]),
        kind=payload["kind"],
        strategy_id=str(payload["strategy_id"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        payload=dict(payload["payload"]),
        symbol=payload.get("symbol"),
    )
