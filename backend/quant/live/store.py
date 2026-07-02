from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
