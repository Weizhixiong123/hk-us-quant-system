from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GatewayConnection:
    name: str
    broker: str
    environment: str
    connected: bool
    detail: str


class BrokerGateway(Protocol):
    name: str

    def connect(self) -> GatewayConnection:
        ...

    def disconnect(self) -> None:
        ...

    def submit_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
    ) -> str:
        ...

