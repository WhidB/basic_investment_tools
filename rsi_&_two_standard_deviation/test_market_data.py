from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from market_data import fetch


class MarketData(unittest.TestCase):
    def test_rate_limit_is_not_retried(self):
        with patch('market_data.requests.get', return_value=Mock(status_code=429)) as get:
            with self.assertRaisesRegex(ValueError, '5분'):
                fetch(dict(kind='RSI', symbol='TQQQ', period=14))
            self.assertEqual(get.call_count, 1)

    def test_chart_filters_open_day_and_reuses_regular_quote(self):
        times = [int(datetime(2026, 9, day, 13, 30, tzinfo=timezone.utc).timestamp()) for day in (25, 28)]
        now = datetime(2026, 9, 28, 18, 0, tzinfo=timezone.utc)
        payload = {'chart': {'result': [{'meta': dict(currency='USD', exchangeTimezoneName='America/New_York',
            regularMarketPrice=12.5, regularMarketTime=int(now.timestamp())), 'timestamp': times,
            'indicators': {'quote': [{'close': [10.0, 12.0]}]}}], 'error': None}}
        response = Mock(status_code=200)
        response.json.return_value = payload
        with patch('market_data.requests.get', return_value=response) as get, patch('market_data.datetime') as clock:
            clock.now.return_value = now
            clock.combine = datetime.combine
            clock.min = datetime.min
            clock.fromtimestamp = datetime.fromtimestamp
            result = fetch(dict(kind='Z-score', symbol='TQQQ', period_mode='calendar', years=1, months=0, days=0))
        self.assertEqual(result['observations'], [{'date': '2026-09-25', 'close': 10.0}])
        self.assertEqual(result['quote']['price'], 12.5)
        self.assertFalse(result['stale'])
        self.assertEqual(get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
