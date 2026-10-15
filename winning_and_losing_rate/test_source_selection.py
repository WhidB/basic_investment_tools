from datetime import date
import unittest
from unittest.mock import patch
import backtest


class SourceSelectionTests(unittest.TestCase):
    def test_yahoo(self):
        with patch("builtins.input", side_effect=["1"]), patch("backtest.load_prices", return_value=["prices"]) as load:
            self.assertEqual(backtest.select_price_source("TQQQ", None, date(2024, 1, 3)), ["prices"])
            load.assert_called_once()

    def test_investing_download_flow(self):
        with patch("builtins.input", side_effect=["2", ""]), patch("backtest.webbrowser.open", return_value=True) as browser, patch("backtest.choose_price_file", return_value="history.csv"), patch("backtest.load_csv_prices", return_value=["prices"]) as load:
            self.assertEqual(backtest.select_price_source("TQQQ", None, date(2024, 1, 3)), ["prices"])
            self.assertIn("TQQQ", browser.call_args.args[0])
            self.assertEqual(load.call_args.args[0], "history.csv")

    def test_rate_limit_switch_to_file(self):
        with patch("builtins.input", side_effect=["1", "3", "history.csv"]), patch("backtest.load_prices", side_effect=backtest.PriceRateLimitError("limited")), patch("backtest.load_csv_prices", return_value=["prices"]):
            self.assertEqual(backtest.select_price_source("TQQQ", None, date(2024, 1, 3)), ["prices"])

    def test_file_picker_cancel_returns_to_menu(self):
        with patch("builtins.input", side_effect=["2", "", "0"]), patch("backtest.webbrowser.open", return_value=True), patch("backtest.choose_price_file", return_value=""):
            self.assertIsNone(backtest.select_price_source("TQQQ", None, date(2024, 1, 3)))


if __name__ == "__main__":
    unittest.main()
