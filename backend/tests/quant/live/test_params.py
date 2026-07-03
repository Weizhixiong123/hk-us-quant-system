from __future__ import annotations

import pytest

from quant.live.params import IntradayParams, LiveParams, PortfolioParams


def test_defaults_match_strategy_function_defaults():
    intraday = IntradayParams()
    assert (intraday.fast_ema, intraday.slow_ema, intraday.signal_ema) == (12, 26, 9)
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


def test_update_intraday_macd_params_and_rejects_invalid_periods():
    params = LiveParams()
    params.update("intraday_macd", {"fast_ema": 8, "slow_ema": 21, "signal_ema": 5})

    assert (params.intraday.fast_ema, params.intraday.slow_ema, params.intraday.signal_ema) == (8, 21, 5)

    with pytest.raises(ValueError, match="快线周期必须小于慢线周期"):
        params.update("intraday_macd", {"fast_ema": 30})

    assert params.intraday.fast_ema == 8


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
