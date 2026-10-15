import unittest
from datetime import date, timedelta
from backtest import calculate, summary, calculate_excluding, split_excluded_period


def prices(values):
    return [(date(2024, 1, 1) + timedelta(days=i), p, p, p, p) for i, p in enumerate(values)]


class BacktestTests(unittest.TestCase):
    def test_exclusion_does_not_bridge_position(self):
        data = prices([100, 101, 120, 130, 143])
        trades = calculate_excluding(data, 10, 5, date(2024, 1, 3), date(2024, 1, 3))
        self.assertEqual([t.result for t in trades], ["미청산", "승리"])
        self.assertEqual(trades[0].last_date, date(2024, 1, 2))
        self.assertEqual(trades[1].entry_date, date(2024, 1, 4))
        self.assertEqual(trades[1].entry_close, 130)
        self.assertEqual(summary(trades)["win_rate"], 100)

    def test_exclusion_boundaries_and_empty(self):
        data = prices([100, 101, 102, 103, 104])
        segments = split_excluded_period(data, date(2024, 1, 2), date(2024, 1, 4))
        self.assertEqual([row[0] for segment in segments for row in segment],
                         [date(2024, 1, 1), date(2024, 1, 5)])
        with self.assertRaises(ValueError):
            split_excluded_period(data, date(2024, 1, 1), date(2024, 1, 5))
        with self.assertRaises(ValueError):
            split_excluded_period(data, date(2024, 1, 5), date(2024, 1, 1))

    def test_exclusion_outside_history_preserves_results(self):
        data = prices([100, 111, 100, 94])
        trades = calculate_excluding(data, 10, 5, date(2023, 1, 1), date(2023, 1, 5))
        self.assertEqual(trades, calculate(data, 10, 5))

    def test_sequential_reentry_and_open(self):
        trades = calculate(prices([100, 111, 100, 94, 100]), 10, 5)
        self.assertEqual([t.result for t in trades], ["승리", "패배", "미청산"])
        self.assertEqual(summary(trades), dict(wins=1, losses=1, open=1, win_rate=50, loss_rate=50))

    def test_daily_overlapping_entries(self):
        trades = calculate(prices([100, 100, 112]), 10, 5, "daily")
        self.assertEqual([t.result for t in trades], ["승리", "승리", "미청산"])

    def test_exact_loss_and_first_threshold(self):
        trades = calculate(prices([100, 95, 150]), 10, 5)
        self.assertEqual(trades[0].result, "패배")
        self.assertEqual(trades[0].last_price, 95)

    def test_intraday_thresholds_and_ambiguous_bar(self):
        for bar, result, fill in [
            ((100, 112, 99, 101), "승리", 110),
            ((100, 104, 94, 101), "패배", 95),
            ((100, 112, 94, 101), "패배", 95),
            ((115, 120, 90, 100), "승리", 115),
            ((90, 120, 89, 100), "패배", 90),
        ]:
            with self.subTest(bar=bar):
                data = prices([100]) + [(date(2024, 1, 2), *bar)]
                trade = calculate(data, 10, 5)[0]
                self.assertEqual(trade.result, result)
                self.assertAlmostEqual(trade.last_price, fill)

    def test_entry_day_range_is_not_used(self):
        data = [(date(2024, 1, 1), 100, 120, 80, 100)]
        self.assertEqual(calculate(data, 10, 5)[0].result, "미청산")

    def test_invalid_ohlc_range(self):
        with self.assertRaises(ValueError):
            calculate([(date(2024, 1, 1), 100, 99, 90, 100)], 10, 5)

    def test_no_closed_trades(self):
        self.assertIsNone(summary(calculate(prices([100, 101]), 10, 5))["win_rate"])
        self.assertEqual(calculate([], 10, 5), [])

    def test_invalid_input(self):
        for gain, loss in [(0, 5), (10, 100), (float("nan"), 5)]:
            with self.assertRaises(ValueError):
                calculate(prices([100]), gain, loss)
        with self.assertRaises(ValueError):
            calculate(prices([100, -1]), 10, 5)


if __name__ == "__main__":
    unittest.main()
