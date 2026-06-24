from __future__ import annotations

from quant.live.params import IntradayParams, LiveParams, PortfolioParams


def test_defaults_match_strategy_function_defaults():
    intraday = IntradayParams()
    assert intraday.stop_loss_pct == 1.5
    assert intraday.take_profit_2_pct == 3.5
    assert intraday.position_fraction_pct == 10.0
    assert intraday.max_positions == 3
    portfolio = PortfolioParams()
    assert portfolio.single_position_cap_pct == 15.0
    assert portfolio.rebalance_months == 6


def test_update_intraday_params():
    params = LiveParams()
    params.update("intraday_macd", {"stop_loss_pct": 2.0, "max_positions": 5})
    assert params.intraday.stop_loss_pct == 2.0
    assert params.intraday.max_positions == 5
    assert params.intraday.take_profit_1_pct == 2.0  # 未改动保持默认


def test_update_ignores_unknown_keys():
    params = LiveParams()
    params.update("intraday_macd", {"bogus": 9, "stop_loss_pct": 1.0})
    assert params.intraday.stop_loss_pct == 1.0
    assert not hasattr(params.intraday, "bogus")


def test_update_portfolio_params():
    params = LiveParams()
    params.update("trend_portfolio", {"take_profit_pct": 25.0})
    assert params.portfolio.take_profit_pct == 25.0


def test_update_unknown_strategy_is_noop():
    params = LiveParams()
    params.update("nope", {"stop_loss_pct": 99})
    assert params.intraday.stop_loss_pct == 1.5
