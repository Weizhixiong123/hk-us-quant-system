import pytest

from quant.live.position_manager import (
    evaluate_portfolio_count,
    plan_intraday_entry,
    plan_portfolio_entry,
)


def test_intraday_entry_uses_ten_percent_and_lot_size():
    plan = plan_intraday_entry(
        symbol="AAPL",
        total_equity=100_000,
        last_price=33,
        current_symbols=[],
        stopped_symbols_today=[],
        position_fraction_pct=10,
        lot_size=100,
    )

    assert plan.allowed is True
    assert plan.quantity == 300
    assert plan.order_value == 9_900
    assert plan.target_value == 10_000


def test_intraday_entry_blocks_duplicate_max_positions_and_stop_loss_reentry():
    plan = plan_intraday_entry(
        symbol="AAPL",
        total_equity=100_000,
        last_price=100,
        current_symbols=["AAPL", "MSFT", "NVDA"],
        stopped_symbols_today=["AAPL"],
        max_positions=3,
    )

    assert plan.allowed is False
    assert plan.quantity == 0
    assert "日内不重复加仓同一标的" in plan.reasons
    assert "日内同时持仓数量已达上限" in plan.reasons
    assert "该标的当日已止损，禁止再开仓" in plan.reasons


def test_portfolio_first_entry_uses_sixty_percent_of_fifteen_percent_cap():
    plan = plan_portfolio_entry(
        symbol="00700.HK",
        total_equity=1_000_000,
        last_price=100,
        current_position_values={},
        stage="first",
        single_position_cap_pct=15,
        first_entry_fraction=0.6,
        lot_size=100,
    )

    assert plan.allowed is True
    assert plan.quantity == 900
    assert plan.order_value == 90_000
    assert plan.target_value == 90_000


def test_portfolio_first_entry_blocks_when_position_count_reaches_max():
    current_positions = {f"SYM{i}": 100_000 for i in range(8)}

    plan = plan_portfolio_entry(
        symbol="AAPL",
        total_equity=1_000_000,
        last_price=100,
        current_position_values=current_positions,
        stage="first",
        target_positions_max=8,
    )

    assert plan.allowed is False
    assert "中长线持仓数量已达上限" in plan.reasons


def test_portfolio_add_entry_requires_pullback_and_tops_up_to_cap():
    blocked = plan_portfolio_entry(
        symbol="00700.HK",
        total_equity=1_000_000,
        last_price=100,
        current_position_values={"00700.HK": 90_000},
        stage="add",
        pullback_confirmed=False,
    )
    assert blocked.allowed is False
    assert "回踩企稳未确认，暂不补仓" in blocked.reasons

    allowed = plan_portfolio_entry(
        symbol="00700.HK",
        total_equity=1_000_000,
        last_price=100,
        current_position_values={"00700.HK": 90_000},
        stage="add",
        pullback_confirmed=True,
        single_position_cap_pct=15,
        lot_size=100,
    )

    assert allowed.allowed is True
    assert allowed.quantity == 600
    assert allowed.order_value == 60_000
    assert allowed.target_value == 150_000


def test_portfolio_add_entry_blocks_when_already_at_cap():
    plan = plan_portfolio_entry(
        symbol="00700.HK",
        total_equity=1_000_000,
        last_price=100,
        current_position_values={"00700.HK": 150_000},
        stage="add",
        pullback_confirmed=True,
    )

    assert plan.allowed is False
    assert "该标的仓位已达到上限" in plan.reasons


def test_portfolio_count_status():
    assert evaluate_portfolio_count(4).status == "under_target"
    assert evaluate_portfolio_count(5).status == "within_target"
    assert evaluate_portfolio_count(8).status == "within_target"
    assert evaluate_portfolio_count(9).status == "over_target"


def test_portfolio_entry_rejects_unknown_stage():
    with pytest.raises(ValueError):
        plan_portfolio_entry(
            symbol="AAPL",
            total_equity=1_000_000,
            last_price=100,
            current_position_values={},
            stage="unknown",
        )
