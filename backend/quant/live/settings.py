from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SETTINGS: dict[str, Any] = {
    "runtime": {
        "enabled": False,
        "dry_run": True,
        "broker": "futu",
        "poll_interval_seconds": 2.0,
        "default_equity": 1_000_000.0,
    },
    "futu": {
        "host": "127.0.0.1",
        "port": 11111,
        "trd_env": "SIMULATE",
        "market": "HK",
        "markets": ["HK", "US"],
        "real_trading_confirmed": False,
    },
    "tiger": {
        "tiger_id": "",
        "account": "",
        "private_key": "",
        "private_key_path": "",
        "tiger_public_key_path": "",
        "environment": "sandbox",
        "language": "zh_CN",
        "max_contracts": 100,
        "use_preset_contracts": False,
        "market": "US",
        "markets": ["US"],
        "live_trading_confirmed": False,
    },
    "safety": {
        "operator_note": "",
    },
}


def default_settings_path() -> Path:
    env_path = os.getenv("LIVE_SETTINGS_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[2] / "data" / "live-settings.json"


def load_live_settings(path: Path | None = None) -> dict[str, Any]:
    settings = deepcopy(DEFAULT_SETTINGS)
    settings_path = path or default_settings_path()
    if not settings_path.exists():
        return settings

    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings

    if isinstance(raw, Mapping):
        _deep_update(settings, raw)
    return _normalized_settings(settings)


def save_live_settings(
    update: Mapping[str, Any],
    path: Path | None = None,
) -> dict[str, Any]:
    settings = load_live_settings(path)
    update_dict = deepcopy(dict(update))
    _apply_private_key_clear(settings, update_dict)
    _deep_update(settings, update_dict)
    settings = _normalized_settings(settings)
    _validate(settings)

    settings_path = path or default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return settings


def public_live_settings(settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value = deepcopy(dict(settings)) if settings is not None else load_live_settings()
    tiger = value.setdefault("tiger", {})
    tiger["private_key_configured"] = bool(tiger.get("private_key"))
    tiger.pop("private_key", None)
    value["saved_at"] = datetime.now(timezone.utc).isoformat()
    value["restart_required"] = True
    return value


def _apply_private_key_clear(settings: dict[str, Any], update: dict[str, Any]) -> None:
    tiger_update = update.get("tiger")
    if not isinstance(tiger_update, dict):
        return
    if tiger_update.pop("clear_private_key", False):
        settings.setdefault("tiger", {})["private_key"] = ""


def _deep_update(target: dict[str, Any], update: Mapping[str, Any]) -> None:
    for key, value in update.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _normalized_settings(settings: dict[str, Any]) -> dict[str, Any]:
    runtime = settings.setdefault("runtime", {})
    runtime["broker"] = str(runtime.get("broker", "futu")).lower()
    runtime["enabled"] = bool(runtime.get("enabled", False))
    runtime["dry_run"] = bool(runtime.get("dry_run", True))
    runtime["poll_interval_seconds"] = float(runtime.get("poll_interval_seconds", 2.0))
    runtime["default_equity"] = float(runtime.get("default_equity", 1_000_000.0))

    futu = settings.setdefault("futu", {})
    futu["host"] = str(futu.get("host", "127.0.0.1"))
    futu["port"] = int(futu.get("port", 11111))
    futu["trd_env"] = str(futu.get("trd_env", "SIMULATE")).upper()
    futu["markets"] = _normalize_markets(futu.get("markets"), futu.get("market", "HK"))
    futu["market"] = futu["markets"][0]
    futu["real_trading_confirmed"] = bool(futu.get("real_trading_confirmed", False))

    tiger = settings.setdefault("tiger", {})
    tiger["tiger_id"] = str(tiger.get("tiger_id", ""))
    tiger["account"] = str(tiger.get("account", ""))
    tiger["private_key"] = str(tiger.get("private_key", ""))
    tiger["private_key_path"] = str(tiger.get("private_key_path", ""))
    tiger["tiger_public_key_path"] = str(tiger.get("tiger_public_key_path", ""))
    tiger["environment"] = str(tiger.get("environment", "sandbox")).lower()
    tiger["language"] = str(tiger.get("language", "zh_CN"))
    tiger["max_contracts"] = int(tiger.get("max_contracts", 100))
    tiger["use_preset_contracts"] = bool(tiger.get("use_preset_contracts", False))
    tiger["markets"] = _normalize_markets(tiger.get("markets"), tiger.get("market", "US"))
    tiger["market"] = tiger["markets"][0]
    tiger["live_trading_confirmed"] = bool(tiger.get("live_trading_confirmed", False))

    safety = settings.setdefault("safety", {})
    safety.pop("pause_new_orders", None)
    safety.pop("close_only", None)
    safety["operator_note"] = str(safety.get("operator_note", ""))
    return settings


def _normalize_markets(value: Any, fallback: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else [fallback]
    markets: list[str] = []
    for item in raw_items:
        market = str(item).upper()
        if market in {"HK", "US"} and market not in markets:
            markets.append(market)
    return markets or ["HK"]


def _validate(settings: Mapping[str, Any]) -> None:
    runtime = settings["runtime"]
    if runtime["broker"] not in {"futu", "tiger"}:
        raise ValueError("runtime.broker must be futu or tiger")
    if runtime["poll_interval_seconds"] <= 0:
        raise ValueError("runtime.poll_interval_seconds must be positive")
    if runtime["default_equity"] <= 0:
        raise ValueError("runtime.default_equity must be positive")

    futu = settings["futu"]
    if futu["trd_env"] not in {"SIMULATE", "REAL"}:
        raise ValueError("futu.trd_env must be SIMULATE or REAL")
    if not set(futu["markets"]).issubset({"HK", "US"}):
        raise ValueError("futu.markets must contain HK or US")
    if futu["trd_env"] == "REAL" and not futu["real_trading_confirmed"]:
        raise ValueError("futu REAL mode requires real trading confirmation")

    tiger = settings["tiger"]
    if tiger["environment"] not in {"sandbox", "live"}:
        raise ValueError("tiger.environment must be sandbox or live")
    if not set(tiger["markets"]).issubset({"HK", "US"}):
        raise ValueError("tiger.markets must contain HK or US")
    if tiger["environment"] == "live" and not tiger["live_trading_confirmed"]:
        raise ValueError("tiger live mode requires live trading confirmation")
