from __future__ import annotations

from .base import GatewayConnection


class FutuGatewayAdapter:
    name = "futu"

    def __init__(self, trd_env: str = "SIMULATE") -> None:
        self.trd_env = trd_env

    def connect(self) -> GatewayConnection:
        return GatewayConnection(
            name=self.name,
            broker="Futu",
            environment=self.trd_env,
            connected=False,
            detail="等待接入 vnpy_futu 与本地 FutuOpenD",
        )

    def disconnect(self) -> None:
        return None

    def submit_order(self, symbol: str, side: str, quantity: int, price: float) -> str:
        raise NotImplementedError("Futu real order routing is implemented after credentials are configured.")

