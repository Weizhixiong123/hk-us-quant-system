from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


INTRADAY_PARAM_DEFAULTS: dict[str, int | float] = {
    "fast_ema": 12,
    "slow_ema": 26,
    "signal_ema": 9,
    "slow_k_minutes": 15,
    "mid_k_minutes": 5,
    "fast_k_minutes": 3,
    "position_fraction_pct": 10.0,
    "max_positions": 3,
    "max_daily_loss_pct": 3.0,
    "open_after_minutes": 30,
    "close_before_minutes": 90,
    "min_turnover": 5_000_000.0,
    "min_amplitude_pct": 2.0,
    "max_amplitude_pct": 8.0,
    "min_price": 2.0,
    "min_turnover_rate": 0.0,
    "trailing_enabled": 1,
    "trailing_start_pct": 2.0,
    "trailing_stop_pct": 1.0,
    "auto_min_score": 0.65,
    "max_auto_candidates": 40,
    "score_half_life_hours": 4.0,
    "shortable_bonus_pts": 0.05,
}

MA_ATR_PARAM_DEFAULTS: dict[str, int | float] = {
    "slow_k_minutes": 60,
    "mid_k_minutes": 10,
    "fast_k_minutes": 5,
    "slow_fast_ema": 3,
    "slow_slow_ema": 8,
    "mid_fast_ema": 11,
    "mid_slow_ema": 30,
    "fast_fast_ema": 3,
    "fast_slow_ema": 8,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "atr_period": 5,
    "atr_multiplier": 1.2,
    "stop_loss_pct": 1.5,
    "take_profit_pct": 3.0,
    "trailing_enabled": 1,
    "trailing_start_pct": 2.0,
    "trailing_stop_pct": 1.0,
    "position_fraction_pct": 10.0,
    "max_positions": 3,
    "max_daily_loss_pct": 3.0,
    "open_after_minutes": 30,
    "close_before_minutes": 90,
    "min_turnover": 5_000_000.0,
    "min_amplitude_pct": 2.0,
    "max_amplitude_pct": 8.0,
    "min_price": 2.0,
    "min_turnover_rate": 0.0,
    "auto_min_score": 0.65,
    "max_auto_candidates": 40,
    "score_half_life_hours": 4.0,
    "shortable_bonus_pts": 0.05,
}


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
    "intraday_universe": {
        "selection_mode": "auto",
        "manual_symbols": [],
    },
    "intraday_params": INTRADAY_PARAM_DEFAULTS,
    "ma_atr_intraday_params": MA_ATR_PARAM_DEFAULTS,
}

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,23}$")


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
    intraday_params = value.setdefault("intraday_params", {})
    for key, default in INTRADAY_PARAM_DEFAULTS.items():
        intraday_params.setdefault(key, default)
    ma_atr_params = value.setdefault("ma_atr_intraday_params", {})
    for key, default in MA_ATR_PARAM_DEFAULTS.items():
        ma_atr_params.setdefault(key, default)
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

    intraday_universe = settings.setdefault("intraday_universe", {})
    intraday_universe["selection_mode"] = str(
        intraday_universe.get("selection_mode", "auto")
    ).lower()
    intraday_universe["manual_symbols"] = _normalize_manual_symbols(
        intraday_universe.get("manual_symbols")
    )

    intraday_params = settings.setdefault("intraday_params", {})
    integer_keys = {
        "fast_ema",
        "slow_ema",
        "signal_ema",
        "max_positions",
        "open_after_minutes",
        "close_before_minutes",
        "slow_k_minutes",
        "mid_k_minutes",
        "fast_k_minutes",
        "max_auto_candidates",
    }
    for key, default in INTRADAY_PARAM_DEFAULTS.items():
        value = intraday_params.get(key, default)
        if key == "trailing_enabled":
            intraday_params[key] = bool(value)
        else:
            intraday_params[key] = int(value) if key in integer_keys else float(value)

    ma_atr_params = settings.setdefault("ma_atr_intraday_params", {})
    ma_atr_integer_keys = {
        "slow_k_minutes",
        "mid_k_minutes",
        "fast_k_minutes",
        "slow_fast_ema",
        "slow_slow_ema",
        "mid_fast_ema",
        "mid_slow_ema",
        "fast_fast_ema",
        "fast_slow_ema",
        "macd_fast",
        "macd_slow",
        "macd_signal",
        "atr_period",
        "max_positions",
        "open_after_minutes",
        "close_before_minutes",
        "max_auto_candidates",
    }
    for key, default in MA_ATR_PARAM_DEFAULTS.items():
        value = ma_atr_params.get(key, default)
        if key == "trailing_enabled":
            ma_atr_params[key] = bool(value)
        else:
            ma_atr_params[key] = int(value) if key in ma_atr_integer_keys else float(value)

    return settings


def _normalize_manual_symbols(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    symbols: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, Mapping):
            continue
        market = str(item.get("market", "")).strip().upper()
        symbol = _normalize_symbol(str(item.get("symbol", "")), market)
        key = (market, symbol)
        if market not in {"HK", "US"} or not _SYMBOL_PATTERN.fullmatch(symbol) or key in seen:
            continue
        seen.add(key)
        symbols.append(
            {
                "symbol": symbol,
                "name": str(item.get("name", "")).strip() or symbol,
                "market": market,
                "shortable": bool(item.get("shortable", False)),
            }
        )
    return symbols


def _normalize_symbol(value: str, market: str) -> str:
    symbol = value.strip().upper().replace(" ", "")
    if market == "HK":
        if symbol.startswith("HK."):
            symbol = symbol[3:]
        if symbol.endswith(".HK"):
            symbol = symbol[:-3]
        if symbol.isdigit():
            symbol = (symbol.lstrip("0") or "0").zfill(4)
        return f"{symbol}.HK" if symbol else ""
    if market == "US" and symbol.endswith(".US"):
        return symbol[:-3]
    return symbol


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
    tiger = settings["tiger"]
    if tiger["environment"] not in {"sandbox", "live"}:
        raise ValueError("tiger.environment must be sandbox or live")
    if not set(tiger["markets"]).issubset({"HK", "US"}):
        raise ValueError("tiger.markets must contain HK or US")

    intraday_universe = settings["intraday_universe"]
    if intraday_universe["selection_mode"] not in {"auto", "manual"}:
        raise ValueError("intraday_universe.selection_mode must be auto or manual")
    for item in intraday_universe["manual_symbols"]:
        if item["market"] not in {"HK", "US"} or not _SYMBOL_PATTERN.fullmatch(item["symbol"]):
            raise ValueError("manual symbol is invalid")

    intraday = settings["intraday_params"]
    if not 2 <= intraday["fast_ema"] <= 60:
        raise ValueError("MACD 快线周期必须在 2 到 60 之间")
    if not 3 <= intraday["slow_ema"] <= 120:
        raise ValueError("MACD 慢线周期必须在 3 到 120 之间")
    if not 2 <= intraday["signal_ema"] <= 60:
        raise ValueError("MACD 信号线周期必须在 2 到 60 之间")
    if intraday["fast_ema"] >= intraday["slow_ema"]:
        raise ValueError("MACD 快线周期必须小于慢线周期")
    if not 1 <= intraday["slow_k_minutes"] <= 120:
        raise ValueError("大周期 K 线必须在 1 到 120 分钟之间")
    if not 1 <= intraday["mid_k_minutes"] <= 60:
        raise ValueError("中周期 K 线必须在 1 到 60 分钟之间")
    if not 1 <= intraday["fast_k_minutes"] <= 30:
        raise ValueError("小周期 K 线必须在 1 到 30 分钟之间")
    if not (intraday["fast_k_minutes"] < intraday["mid_k_minutes"] < intraday["slow_k_minutes"]):
        raise ValueError("K 线周期必须满足:小周期 < 中周期 < 大周期")
    if not 0 < intraday["position_fraction_pct"] <= 100:
        raise ValueError("单次开仓仓位必须大于 0 且不超过 100%")
    if not 1 <= intraday["max_positions"] <= 20:
        raise ValueError("最大同时持仓必须在 1 到 20 之间")
    if not 0 < intraday["max_daily_loss_pct"] <= 100:
        raise ValueError("单日最大亏损必须大于 0 且不超过 100%")
    if not 0 <= intraday["open_after_minutes"] <= 240 or not 0 <= intraday["close_before_minutes"] <= 240:
        raise ValueError("开盘等待和尾盘停开时间必须在 0 到 240 分钟之间")
    if intraday["min_amplitude_pct"] > intraday["max_amplitude_pct"]:
        raise ValueError("振幅下限不能大于振幅上限")
    if intraday["open_after_minutes"] + intraday["close_before_minutes"] >= 390:
        raise ValueError("开盘等待与收盘前停止时间之和必须小于 390 分钟")
    if not 0 <= intraday["trailing_start_pct"] <= 100 or not 0 <= intraday["trailing_stop_pct"] <= 100:
        raise ValueError("动态止盈参数必须在 0 到 100 之间")
    if min(
        intraday["min_turnover"],
        intraday["min_amplitude_pct"],
        intraday["max_amplitude_pct"],
        intraday["min_price"],
        intraday["min_turnover_rate"],
    ) < 0:
        raise ValueError("盘前筛选参数不能小于 0")
    if not 0 <= intraday.get("auto_min_score", 0.65) <= 1:
        raise ValueError("自动选股评分门槛必须在 0 到 1 之间")
    if not 1 <= intraday.get("max_auto_candidates", 40) <= 1000:
        raise ValueError("自动候选数量上限必须在 1 到 1000 之间")
