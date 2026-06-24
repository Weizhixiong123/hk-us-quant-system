from __future__ import annotations

from datetime import date

from quant.live.risk import PdtTracker, evaluate_live_order_risk


def test_live_risk_blocks_open_when_gateway_disconnected():
    decision = evaluate_live_order_risk(
        symbol="AAPL",
        market="US",
        purpose="open",
        gateway_connected=False,
        daily_loss_pct=0,
        stopped_symbols_today=[],
    )

    assert decision.allowed is False
    assert "网关未连接，暂停下单" in decision.reasons


def test_live_risk_blocks_open_on_daily_loss_stopped_symbol_pdt_and_shortable():
    decision = evaluate_live_order_risk(
        symbol="AAPL",
        market="US",
        purpose="open",
        gateway_connected=True,
        daily_loss_pct=-3.1,
        stopped_symbols_today=["AAPL"],
        pdt_trades_remaining=0,
        is_short=True,
        shortable=False,
    )

    assert decision.allowed is False
    assert "触发单日账户最大亏损" in decision.reasons
    assert "该标的当日已止损，禁止再开仓" in decision.reasons
    assert "美股 PDT 日内交易额度不足" in decision.reasons
    assert "标的不满足可做空校验" in decision.reasons


def test_live_risk_allows_close_under_daily_loss_when_gateway_connected():
    decision = evaluate_live_order_risk(
        symbol="AAPL",
        market="US",
        purpose="close",
        gateway_connected=True,
        daily_loss_pct=-4,
        stopped_symbols_today=["AAPL"],
        pdt_trades_remaining=0,
    )

    assert decision.allowed is True
    assert decision.reasons == ("实盘风控通过",)


def test_live_risk_blocks_after_consecutive_order_failures():
    decision = evaluate_live_order_risk(
        symbol="AAPL",
        market="US",
        purpose="open",
        gateway_connected=True,
        daily_loss_pct=0,
        stopped_symbols_today=[],
        consecutive_order_failures=3,
        max_order_failures=3,
    )

    assert decision.allowed is False
    assert "连续下单失败次数过多，暂停自动下单" in decision.reasons


def test_pdt_tracker_counts_rolling_five_business_days():
    tracker = PdtTracker(max_day_trades=3)
    tracker.record_day_trade(date(2026, 6, 22))
    tracker.record_day_trade(date(2026, 6, 23))
    tracker.record_day_trade(date(2026, 6, 24))

    assert tracker.remaining(date(2026, 6, 25)) == 0
    assert tracker.remaining(date(2026, 6, 30)) == 2


def test_live_risk_blocks_open_when_account_halted():
    from quant.live.risk import evaluate_live_order_risk

    decision = evaluate_live_order_risk(
        symbol="AAPL",
        market="US",
        purpose="open",
        gateway_connected=True,
        daily_loss_pct=0.0,
        stopped_symbols_today=(),
        account_halted=True,
    )
    assert decision.allowed is False
    assert any("熔断" in reason for reason in decision.reasons)


def test_live_risk_halt_does_not_block_close():
    from quant.live.risk import evaluate_live_order_risk

    decision = evaluate_live_order_risk(
        symbol="AAPL",
        market="US",
        purpose="close",
        gateway_connected=True,
        daily_loss_pct=0.0,
        stopped_symbols_today=(),
        account_halted=True,
    )
    assert decision.allowed is True
