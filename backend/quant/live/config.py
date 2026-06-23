from __future__ import annotations

import os
from dataclasses import dataclass

_VALID_TRD_ENV = {"SIMULATE", "REAL"}
_REAL_TRADING_CONFIRM = "I_UNDERSTAND_REAL_MONEY_RISK"


@dataclass(frozen=True)
class FutuGatewayConfig:
    host: str
    port: int
    trd_env: str
    market: str
    paper: bool
    real_trading_confirmed: bool


def load_futu_config() -> FutuGatewayConfig:
    trd_env = os.getenv("FUTU_TRD_ENV", "SIMULATE").upper()
    if trd_env not in _VALID_TRD_ENV:
        raise ValueError(f"FUTU_TRD_ENV must be one of {_VALID_TRD_ENV}, got {trd_env}")

    real_confirmed = os.getenv("FUTU_REAL_TRADING_CONFIRM") == _REAL_TRADING_CONFIRM
    if trd_env == "REAL" and not real_confirmed:
        raise ValueError(
            "FUTU_TRD_ENV=REAL requires "
            f"FUTU_REAL_TRADING_CONFIRM={_REAL_TRADING_CONFIRM}"
        )

    return FutuGatewayConfig(
        host=os.getenv("FUTU_HOST", "127.0.0.1"),
        port=int(os.getenv("FUTU_PORT", "11111")),
        trd_env=trd_env,
        market=os.getenv("FUTU_MARKET", "HK"),
        paper=trd_env == "SIMULATE",
        real_trading_confirmed=real_confirmed,
    )
