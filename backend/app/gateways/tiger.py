from __future__ import annotations

from .base import GatewayConnection


class TigerGatewayAdapter:
    name = "tiger"

    def __init__(self, account: str = "paper") -> None:
        self.account = account

    def connect(self) -> GatewayConnection:
        return GatewayConnection(
            name=self.name,
            broker="Tiger",
            environment=self.account,
            connected=False,
            detail="等待接入 vnpy_tiger 与 tigeropen 凭证",
        )

    def disconnect(self) -> None:
        return None

    def submit_order(self, symbol: str, side: str, quantity: int, price: float) -> str:
        raise NotImplementedError("Tiger real order routing is implemented after credentials are configured.")

