import json
from pathlib import Path
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from indicators import calculate, calendar_start, validate
import storage


def config(kind='RSI', period=14, threshold=30):
    return dict(kind=kind, symbol='TQQQ', period=period, threshold=threshold, operator='<=')


def rows(values):
    return [dict(date=f'2026-01-{i+1:02d}', close=v) for i, v in enumerate(values)]


class Calculations(unittest.TestCase):
    def test_fixed_dates_and_since_keep_current_price_separate(self):
        c = dict(kind='Z-score', symbol='TQQQ', period_mode='dates',
                 start_date='2017-10-15', end_date='2020-12-30', threshold=2.0, operator='<=')
        data = [dict(date=d, close=v) for d,v in [('2017-10-13',1),
                ('2017-10-16',10), ('2020-12-30',12), ('2026-09-30',20)]]
        result = calculate(c, data)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['mean'], 11)
        self.assertEqual(result['price'], 20)
        self.assertEqual(result['requested_end'], '2020-12-30')
        c.update(period_mode='since', start_date='2018-05-09')
        result = calculate(c, data, 21)
        self.assertEqual(result['mean'], 16)
        self.assertEqual(result['price'], 21)
        c.update(period_mode='dates', start_date='2021-01-01')
        with self.assertRaisesRegex(ValueError, '시작일'):
            validate(c)

    def test_rolling_rsi_uses_only_each_dates_past_window(self):
        c = config(period=2, threshold=50)
        observations = rows([10, 12, 11, 14, 12])
        result = calculate(c, observations)
        self.assertEqual([p['date'] for p in result['rsi_history']],
                         [r['date'] for r in observations[-3:]])
        expected = [100 * 2/3, 75, 60]
        for point, value in zip(result['rsi_history'], expected):
            self.assertAlmostEqual(point['rsi'], value)
        self.assertEqual(result['rsi_history'][-1]['rsi'], result['value'])
        short = calculate(c, observations[:3])
        self.assertEqual(len(short['rsi_history']), 1)
        self.assertEqual(short['rsi_history'][0], result['rsi_history'][0])

    def test_calendar_window_leap_year_and_boundaries(self):
        c = dict(kind='Z-score', symbol='TQQQ', period_mode='calendar',
                 years=0, months=1, days=0, threshold=2.0, operator='<=')
        self.assertEqual(calendar_start(c, date(2024,3,31)), date(2024,2,29))
        c.update(years=1, months=0)
        self.assertEqual(calendar_start(c, date(2024,2,29)), date(2023,2,28))
        c.update(years=0, days=3)
        result = calculate(c, [dict(date=d, close=v) for d,v in
            [('2026-09-24',1), ('2026-09-25',10), ('2026-09-28',12)]])
        self.assertEqual(result['requested_start'], '2026-09-25')
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['mean'], 11)
        c['days'] = 0
        with self.assertRaises(ValueError):
            validate(c)
        c['days'] = 1
        with self.assertRaises(ValueError):
            calculate(c, [dict(date='2026-09-28', close=12)])

    def test_rsi_rising_falling_flat(self):
        for values, expected in [(range(1, 16), 100), (range(15, 0, -1), 0), ([10]*15, 50)]:
            self.assertEqual(calculate(config(), rows(values))['value'], expected)

    def test_rsi_exact_window_and_inclusive_threshold(self):
        result = calculate(config(period=2, threshold=50), rows([999, 10, 11, 10]))
        self.assertEqual(result['count'], 3)
        self.assertEqual(result['value'], 50)
        self.assertTrue(result['matched'])

    def test_insufficient(self):
        with self.assertRaises(ValueError):
            calculate(config(), rows([10]*14))

    def test_zscore_population_std_and_boundaries(self):
        c = config('Z-score', 2, 1)
        result = calculate(c, rows([99, 10, 12]), 12)
        self.assertEqual((result['mean'], result['std'], result['value']), (11, 1, 1))
        self.assertTrue(result['matched'])
        self.assertFalse(calculate(c, rows([10, 12]), 9)['matched'])
        self.assertIsNone(calculate(c, rows([10, 10]), 11)['value'])

    def test_storage_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.sqlite3'
            c = config()
            saved = calculate(c, rows(range(1, 16)))
            rid = storage.save('테스트', c, saved, path=path)
            self.assertEqual(json.loads(storage.list_records(path)[0]['snapshot']), saved)
            c['threshold'] = 40
            storage.save('수정', c, None, rid, path)
            result = storage.list_records(path)
            self.assertEqual(len(result), 1)
            self.assertEqual(json.loads(result[0]['config'])['threshold'], 40)
            self.assertIsNone(result[0]['snapshot'])
            storage.delete(rid, path)
            self.assertEqual(storage.list_records(path), [])

    def test_holiday_weekend_intraday_and_early_close(self):
        import pandas as pd
        from market_data import completed_closes
        history = pd.DataFrame({'Close': [10, 11, 12, 13, 14]},
            index=pd.to_datetime(['2026-07-02','2026-07-03','2026-07-04','2026-07-05','2026-07-06']))
        before = datetime(2026, 7, 6, 19, 59, tzinfo=timezone.utc)
        self.assertEqual([r['date'] for r in completed_closes(history, before)[0]], ['2026-07-02'])
        after = datetime(2026, 7, 6, 20, 1, tzinfo=timezone.utc)
        self.assertEqual(len(completed_closes(history, after)[0]), 2)
        early = pd.DataFrame({'Close': [10]}, index=pd.to_datetime(['2026-11-27']))
        self.assertEqual(len(completed_closes(early, datetime(2026,11,27,18,1,tzinfo=timezone.utc))[0]), 1)


if __name__ == '__main__':
    unittest.main()
