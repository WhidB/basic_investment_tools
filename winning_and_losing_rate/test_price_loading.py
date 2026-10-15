from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from yfinance.exceptions import YFRateLimitError
import backtest


class PriceLoadingTests(unittest.TestCase):
    def test_investing_english_and_korean_csv(self):
        files = [
            ('Date,Price,Open,High,Low,Vol.,Change %\n"01/03/2024","1,100.00","1,000.00","1,120.00",990,1M,10%\n01/02/2024,1000,1000,1001,999,1M,0%\n', "utf-8-sig"),
            ('날짜,종가,시가,고가,저가,거래량,변동 %\n2024년 1월 3일,1100,1000,1120,990,1M,10%\n2024-01-02,1000,1000,1001,999,1M,0%\n', "cp949"),
        ]
        with TemporaryDirectory() as folder:
            path = Path(folder) / "history.csv"
            for content, encoding in files:
                with self.subTest(encoding=encoding):
                    path.write_bytes(content.encode(encoding))
                    prices = backtest.load_csv_prices(str(path), "TQQQ", None, date(2024, 1, 3))
                    self.assertEqual(prices[0][4], 1000)
                    self.assertEqual(prices[1][4], 1100)
                    self.assertEqual(backtest.calculate(prices, 10, 5)[0].result, "승리")

    def test_price_date_and_number_formats(self):
        for value in ("2024. 1. 2.", "2024/01/02", "01/02/2024", "Jan 02, 2024"):
            self.assertEqual(backtest.parse_price_date(value), date(2024, 1, 2))
        self.assertEqual(backtest.parse_price_number("1,234.56"), 1234.56)
        with self.assertRaises(ValueError):
            backtest.parse_price_number("12,34")

    def test_cache_reuses_validated_etf_without_network(self):
        stock = Mock()
        stock.history.return_value = pd.DataFrame(
            {"Open": [100.0], "High": [105.0], "Low": [95.0], "Close": [101.0]},
            index=pd.to_datetime(["2024-01-02"]),
        )
        stock.get_history_metadata.return_value = {"instrumentType": "ETF", "exchangeName": "PCX"}
        with TemporaryDirectory() as folder, patch.object(backtest, "CACHE_DIR", Path(folder)), patch("yfinance.Ticker", return_value=stock) as ticker:
            first = backtest.load_prices("SOXL", None, date(2024, 1, 3))
            second = backtest.load_prices("soxl", None, date(2024, 1, 3))
            self.assertEqual(first, second)
            self.assertEqual(ticker.call_count, 1)
            stock.get_info.assert_not_called()
            self.assertNotIn("raise_errors", stock.history.call_args.kwargs)

    def test_csv_reverse_dates_and_period_filter(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "SOXL.csv"
            path.write_text("Date,Open,High,Low,Close,Symbol\n2024-01-03,100,112,99,101,SOXL\n2024-01-02,100,101,99,100,SOXL\n", encoding="utf-8")
            prices = backtest.load_csv_prices(str(path), "SOXL", None, date(2024, 1, 3))
            self.assertEqual([row[0] for row in prices], [date(2024, 1, 2), date(2024, 1, 3)])
            self.assertEqual(backtest.calculate(prices, 10, 4)[0].result, "승리")
            self.assertEqual(len(backtest.load_csv_prices(str(path), "SOXL", date(2024, 1, 3), date(2024, 1, 3))), 1)

    def test_csv_invalid_and_wrong_symbol(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "prices.csv"
            for content in (
                "Date,Close\n2024-01-02,100\n",
                "Date,Open,High,Low,Close,Symbol\n2024-01-02,100,101,99,100,QQQ\n",
                "Date,Open,High,Low,Close\n2024-01-02,100,99,90,100\n",
            ):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    backtest.load_csv_prices(str(path), "SOXL", None, date(2024, 1, 3))

    def test_rate_limit_recovers(self):
        operation = Mock(side_effect=[YFRateLimitError(), "success"])
        with patch("backtest.time.sleep") as sleep:
            self.assertEqual(backtest.retry_rate_limit(operation), "success")
            sleep.assert_called_once_with(10)

    def test_rate_limit_has_bounded_retries(self):
        operation = Mock(side_effect=YFRateLimitError())
        with patch("backtest.time.sleep") as sleep:
            with self.assertRaisesRegex(ValueError, "요청 제한"):
                backtest.retry_rate_limit(operation)
            self.assertEqual(operation.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [10, 30])

    def test_other_errors_are_not_retried(self):
        operation = Mock(side_effect=ValueError("invalid ticker"))
        with patch("backtest.time.sleep") as sleep:
            with self.assertRaises(ValueError):
                backtest.retry_rate_limit(operation)
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
