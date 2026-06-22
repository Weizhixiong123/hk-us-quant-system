from __future__ import annotations

import unittest

from app.services.risk import evaluate_intraday_order, fixed_fraction_position_size
from app.strategies.macd_intraday import ema, histogram_shrinking, macd


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


if __name__ == "__main__":
    unittest.main()

