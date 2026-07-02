from __future__ import annotations

import unittest

from app.services.risk import evaluate_intraday_order, fixed_fraction_position_size
from app.strategies.macd_intraday import (
    build_intraday_decision,
    ema,
    histogram_falling,
    histogram_rising,
    histogram_shrinking,
    macd,
)


class StrategyMathTest(unittest.TestCase):
    def test_ema_keeps_length(self) -> None:
        values = [1, 2, 3, 4, 5]
        self.assertEqual(len(ema(values, 3)), len(values))

    def test_macd_returns_points_when_enough_data(self) -> None:
        values = [float(index) for index in range(1, 40)]
        self.assertTrue(macd(values))

    def test_histogram_shrinking_long_side(self) -> None:
        points = macd([40, 39, 38, 37, 36, 35, 34, 33, 32, 31, 31.2, 31.4, 31.7, 32] * 3)
        result = histogram_shrinking(points[-3:], "long", bars=3)
        self.assertIsInstance(result, bool)

    def test_histogram_rising_and_falling(self) -> None:
        rising = macd(_accelerating_up())
        falling = macd(_accelerating_down())
        self.assertTrue(histogram_rising(rising))
        self.assertFalse(histogram_falling(rising))
        self.assertTrue(histogram_falling(falling))
        self.assertFalse(histogram_rising(falling))

    def test_build_intraday_decision_long_when_three_periods_rising(self) -> None:
        rising = _accelerating_up()
        decision = build_intraday_decision(
            closes_15m=rising,
            closes_5m=rising,
            closes_3m=rising,
            side="long",
            within_trade_window=True,
        )
        self.assertEqual(decision.action, "long")
        self.assertEqual(decision.confidence, 1.0)

    def test_build_intraday_decision_short_when_three_periods_falling(self) -> None:
        falling = _accelerating_down()
        decision = build_intraday_decision(
            closes_15m=falling,
            closes_5m=falling,
            closes_3m=falling,
            side="short",
            within_trade_window=True,
        )
        self.assertEqual(decision.action, "short")

    def test_build_intraday_decision_waits_outside_window(self) -> None:
        rising = _accelerating_up()
        decision = build_intraday_decision(
            closes_15m=rising,
            closes_5m=rising,
            closes_3m=rising,
            side="long",
            within_trade_window=False,
        )
        self.assertEqual(decision.action, "wait")
        self.assertIn("不在日内开仓时间窗", decision.reasons)

    def test_risk_blocks_daily_loss(self) -> None:
        decision = evaluate_intraday_order(
            daily_loss_pct=-3.1,
            max_daily_loss_pct=3,
            open_intraday_positions=0,
            max_intraday_positions=3,
            symbol_stopped_today=False,
            is_short=False,
            shortable=True,
            pdt_trades_remaining=3,
        )
        self.assertFalse(decision.allowed)
        self.assertIn("触发单日账户最大亏损", decision.reasons)

    def test_position_size_respects_lot(self) -> None:
        self.assertEqual(fixed_fraction_position_size(100_000, 33, 0.1, lot_size=100), 300)


def _accelerating_up() -> list[float]:
    """先回落再加速上涨，使 MACD 末根柱较前一根抬高。"""
    return [float(x) for x in range(60, 30, -1)] + [30 + x * x * 0.3 for x in range(30)]


def _accelerating_down() -> list[float]:
    """先上涨再加速下跌，使 MACD 末根柱较前一根下降。"""
    return [float(x) for x in range(1, 31)] + [30 - x * x * 0.3 for x in range(30)]


if __name__ == "__main__":
    unittest.main()

