from __future__ import annotations

from dataclasses import dataclass


def enum_value(x: object) -> str:
    value = getattr(x, "value", x)
    return str(value)


def _time_str(value: object) -> str:
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


@dataclass(frozen=True)
class GatewayAccount:
    account_id: str
    balance: float
    available: float
    frozen: float


@dataclass(frozen=True)
class GatewayPosition:
    symbol: str
    direction: str
    volume: float
    price: float
    pnl: float


@dataclass(frozen=True)
class GatewayOrder:
    order_id: str
    symbol: str
    direction: str
    offset: str
    price: float
    volume: float
    traded: float
    status: str


@dataclass(frozen=True)
class GatewayTick:
    symbol: str
    last_price: float
    volume: float
    time: str


def account_from_vnpy(obj: object) -> GatewayAccount:
    balance = float(getattr(obj, "balance", 0.0))
    frozen = float(getattr(obj, "frozen", 0.0))
    return GatewayAccount(
        account_id=str(getattr(obj, "accountid", "")),
        balance=balance,
        available=balance - frozen,
        frozen=frozen,
    )


def position_from_vnpy(obj: object) -> GatewayPosition:
    return GatewayPosition(
        symbol=str(getattr(obj, "symbol", "")),
        direction=enum_value(getattr(obj, "direction", "")),
        volume=float(getattr(obj, "volume", 0.0)),
        price=float(getattr(obj, "price", 0.0)),
        pnl=float(getattr(obj, "pnl", 0.0)),
    )


def order_from_vnpy(obj: object) -> GatewayOrder:
    return GatewayOrder(
        order_id=str(getattr(obj, "orderid", "")),
        symbol=str(getattr(obj, "symbol", "")),
        direction=enum_value(getattr(obj, "direction", "")),
        offset=enum_value(getattr(obj, "offset", "")),
        price=float(getattr(obj, "price", 0.0)),
        volume=float(getattr(obj, "volume", 0.0)),
        traded=float(getattr(obj, "traded", 0.0)),
        status=enum_value(getattr(obj, "status", "")),
    )


def tick_from_vnpy(obj: object) -> GatewayTick:
    return GatewayTick(
        symbol=str(getattr(obj, "symbol", "")),
        last_price=float(getattr(obj, "last_price", 0.0)),
        volume=float(getattr(obj, "volume", 0.0)),
        time=_time_str(getattr(obj, "datetime", "")),
    )
