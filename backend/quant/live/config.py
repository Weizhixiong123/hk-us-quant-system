from __future__ import annotations

import os
from dataclasses import dataclass

from quant.live.settings import load_live_settings

_VALID_TRD_ENV = {"SIMULATE", "REAL"}
_VALID_TIGER_ENV = {"sandbox", "live"}
_REAL_TRADING_CONFIRM = "I_UNDERSTAND_REAL_MONEY_RISK"
_TIGER_LIVE_TRADING_CONFIRM = "I_UNDERSTAND_TIGER_REAL_MONEY_RISK"


@dataclass(frozen=True)
class FutuGatewayConfig:
    host: str
    port: int
    trd_env: str
    market: str
    paper: bool
    real_trading_confirmed: bool


@dataclass(frozen=True)
class TigerGatewayConfig:
    tiger_id: str
    account: str
    private_key: str
    private_key_path: str
    tiger_public_key_path: str
    environment: str
    language: str
    max_contracts: int
    use_preset_contracts: bool
    market: str
    paper: bool
    live_trading_confirmed: bool


def load_futu_config() -> FutuGatewayConfig:
    settings = load_live_settings().get("futu", {})
    trd_env = os.getenv("FUTU_TRD_ENV", str(settings.get("trd_env", "SIMULATE"))).upper()
    if trd_env not in _VALID_TRD_ENV:
        raise ValueError(f"FUTU_TRD_ENV must be one of {_VALID_TRD_ENV}, got {trd_env}")

    real_confirmed = _confirmation_from_env(
        "FUTU_REAL_TRADING_CONFIRM",
        _REAL_TRADING_CONFIRM,
        bool(settings.get("real_trading_confirmed", False)),
    )
    if trd_env == "REAL" and not real_confirmed:
        raise ValueError(
            "FUTU_TRD_ENV=REAL requires "
            f"FUTU_REAL_TRADING_CONFIRM={_REAL_TRADING_CONFIRM}"
        )

    return FutuGatewayConfig(
        host=os.getenv("FUTU_HOST", str(settings.get("host", "127.0.0.1"))),
        port=int(os.getenv("FUTU_PORT", str(settings.get("port", "11111")))),
        trd_env=trd_env,
        market=os.getenv("FUTU_MARKET", str(settings.get("market", "HK"))).upper(),
        paper=trd_env == "SIMULATE",
        real_trading_confirmed=real_confirmed,
    )


def load_tiger_config() -> TigerGatewayConfig:
    settings = load_live_settings().get("tiger", {})
    environment = os.getenv(
        "TIGER_ENVIRONMENT",
        str(settings.get("environment", "sandbox")),
    ).lower()
    if environment not in _VALID_TIGER_ENV:
        raise ValueError(
            f"TIGER_ENVIRONMENT must be one of {_VALID_TIGER_ENV}, got {environment}"
        )

    live_confirmed = _confirmation_from_env(
        "TIGER_LIVE_TRADING_CONFIRM",
        _TIGER_LIVE_TRADING_CONFIRM,
        bool(settings.get("live_trading_confirmed", False)),
    )
    if environment == "live" and not live_confirmed:
        raise ValueError(
            "TIGER_ENVIRONMENT=live requires "
            f"TIGER_LIVE_TRADING_CONFIRM={_TIGER_LIVE_TRADING_CONFIRM}"
        )

    return TigerGatewayConfig(
        tiger_id=os.getenv("TIGER_ID", str(settings.get("tiger_id", ""))),
        account=os.getenv("TIGER_ACCOUNT", str(settings.get("account", ""))),
        private_key=os.getenv(
            "TIGER_PRIVATE_KEY",
            str(settings.get("private_key", "")),
        ).replace("\\n", "\n"),
        private_key_path=os.getenv(
            "TIGER_PRIVATE_KEY_PATH",
            str(settings.get("private_key_path", "")),
        ),
        tiger_public_key_path=os.getenv(
            "TIGER_PUBLIC_KEY_PATH",
            str(settings.get("tiger_public_key_path", "")),
        ),
        environment=environment,
        language=os.getenv("TIGER_LANGUAGE", str(settings.get("language", "zh_CN"))),
        max_contracts=int(
            os.getenv("TIGER_MAX_CONTRACTS", str(settings.get("max_contracts", "100")))
        ),
        use_preset_contracts=_env_bool(
            "TIGER_USE_PRESET_CONTRACTS",
            bool(settings.get("use_preset_contracts", False)),
        ),
        market=os.getenv("TIGER_MARKET", str(settings.get("market", "US"))).upper(),
        paper=environment == "sandbox",
        live_trading_confirmed=live_confirmed,
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _confirmation_from_env(name: str, expected: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value == expected
