from __future__ import annotations

from dataclasses import dataclass, field

from quant.live.executor import (
    execute_exit_order,
    execute_intraday_entry,
    execute_portfolio_entry,
)


@dataclass
class FakeGateway:
    fail: bool = False
    orders: list[dict[str, object]] = field(default_factory=list)

    def send_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        price: float,
        volume: float,
        exchange: str | None = None,
    ) -> str:
        if self.fail:
            raise RuntimeError("broker down")
        self.orders.append(
            {
                "symbol": symbol,
                "direction": direction,
                "offset": offset,
                "price": price,
                "volume": volume,
                "exchange": exchange,
            }
        )
        return "ORD1"


def test_intraday_entry_submits_when_position_and_risk_pass():
    gateway = FakeGateway()

    result = execute_intraday_entry(
        gateway=gateway,
        symbol="AAPL",
        price=33,
        total_equity=100_000,
        current_symbols=[],
        stopped_symbols_today=[],
        daily_loss_pct=-0.2,
        position_fraction_pct=10,
        lot_size=100,
        exchange="NASDAQ",
    )

    assert result.submitted is True
    assert result.order_id == "ORD1"
    assert result.quantity == 300
    assert gateway.orders == [
        {
            "symbol": "AAPL",
            "direction": "多",
            "offset": "开",
            "price": 33,
            "volume": 300,
            "exchange": "NASDAQ",
        }
    ]


def test_intraday_entry_blocks_duplicate_max_stopped_and_daily_loss():
    gateway = FakeGateway()

    result = execute_intraday_entry(
        gateway=gateway,
        symbol="AAPL",
        price=100,
        total_equity=100_000,
        current_symbols=["AAPL", "MSFT", "NVDA"],
        stopped_symbols_today=["AAPL"],
        daily_loss_pct=-3.2,
        max_positions=3,
    )

    assert result.submitted is False
    assert gateway.orders == []
    assert "日内不重复加仓同一标的" in result.reasons
    assert "日内同时持仓数量已达上限" in result.reasons
    assert "该标的当日已止损，禁止再开仓" in result.reasons
    assert "触发单日账户最大亏损" in result.reasons


def test_intraday_entry_handles_gateway_failure():
    result = execute_intraday_entry(
        gateway=FakeGateway(fail=True),
        symbol="AAPL",
        price=33,
        total_equity=100_000,
        current_symbols=[],
        stopped_symbols_today=[],
        daily_loss_pct=0,
        lot_size=100,
    )

    assert result.submitted is False
    assert result.quantity == 300
    assert result.order_id is None
    assert result.reasons == ("下单失败：broker down",)


def test_intraday_limit_ignores_positions_owned_by_other_strategies():
    gateway = FakeGateway()

    result = execute_intraday_entry(
        gateway=gateway,
        symbol="TSLA",
        price=100,
        total_equity=100_000,
        current_symbols=["AAPL", "MSFT", "NVDA"],
        intraday_symbols=["AAPL"],
        stopped_symbols_today=[],
        daily_loss_pct=0,
        max_positions=3,
    )

    assert result.submitted is True
    assert result.quantity == 100


def test_exit_order_closes_long_position_with_short_close():
    gateway = FakeGateway()

    result = execute_exit_order(
        gateway=gateway,
        symbol="AAPL",
        price=101,
        quantity=200,
        side="long",
        reason="止盈清仓",
    )

    assert result.submitted is True
    assert result.quantity == 200
    assert gateway.orders == [
        {
            "symbol": "AAPL",
            "direction": "空",
            "offset": "平",
            "price": 101,
            "volume": 200,
            "exchange": None,
        }
    ]


def test_exit_order_blocks_zero_quantity():
    result = execute_exit_order(
        gateway=FakeGateway(),
        symbol="AAPL",
        price=101,
        quantity=0,
        side="long",
        reason="尾盘清仓",
    )

    assert result.submitted is False
    assert result.reasons == ("平仓数量为 0",)


def test_portfolio_first_entry_submits_sixty_percent_of_cap():
    gateway = FakeGateway()

    result = execute_portfolio_entry(
        gateway=gateway,
        symbol="00700.HK",
        price=100,
        total_equity=1_000_000,
        current_position_values={},
        stage="first",
        single_position_cap_pct=15,
        first_entry_fraction_pct=60,
        lot_size=100,
    )

    assert result.submitted is True
    assert result.quantity == 900
    assert gateway.orders[0]["symbol"] == "00700.HK"
    assert gateway.orders[0]["direction"] == "多"
    assert gateway.orders[0]["volume"] == 900


def test_portfolio_add_entry_requires_pullback_then_submits_top_up():
    blocked = execute_portfolio_entry(
        gateway=FakeGateway(),
        symbol="00700.HK",
        price=100,
        total_equity=1_000_000,
        current_position_values={"00700.HK": 90_000},
        stage="add",
        pullback_confirmed=False,
    )
    assert blocked.submitted is False
    assert "回踩企稳未确认，暂不补仓" in blocked.reasons

    gateway = FakeGateway()
    allowed = execute_portfolio_entry(
        gateway=gateway,
        symbol="00700.HK",
        price=100,
        total_equity=1_000_000,
        current_position_values={"00700.HK": 90_000},
        stage="add",
        pullback_confirmed=True,
        single_position_cap_pct=15,
        lot_size=100,
    )

    assert allowed.submitted is True
    assert allowed.quantity == 600
    assert gateway.orders[0]["volume"] == 600
