import unittest
from unittest.mock import patch
from native_core import evaluate, prepare, describe

class NativeTests(unittest.TestCase):
    def market(self):
        return dict(observations=[dict(date=d,close=v) for d,v in
            [('2018-05-09',10),('2019-01-02',12),('2020-01-02',100),('2026-10-14',20)]],
            quote=dict(price=22,time='2026-10-14',source='test'),fetched_at='test',
            stale=False,expected_date='2026-10-14')
    def config(self, mode):
        return dict(kind='Z-score',symbol='TQQQ',period_mode=mode,threshold=2.0,operator='<=')
    def test_listing_exclusion_current_price(self):
        c=self.config('exclude')
        c.update(exclude_start='2020-01-01',exclude_end='2026-10-14')
        s=evaluate(c,self.market())
        self.assertEqual(s['result']['mean'],11)
        self.assertEqual(s['result']['price'],22)
        self.assertEqual(s['result']['excluded_count'],2)
        self.assertIn('외에',describe(s))
    def test_all_five_modes(self):
        for mode in ('dates','since','listing','exclude','calendar'):
            c=self.config(mode)
            c.update(start_date='2018-05-09',end_date='2019-01-02',exclude_start='2020-01-01',
                     exclude_end='2020-12-31',years=10,months=0,days=0)
            self.assertGreaterEqual(evaluate(c,self.market())['result']['count'],2)
    def test_reversed_exclusion(self):
        c=self.config('exclude')
        c.update(exclude_start='2021-01-01',exclude_end='2020-01-01')
        with self.assertRaises(ValueError): prepare(c)
    def test_trading_seven_offsets_means_eight_closes(self):
        c=self.config('trading')
        c.update(trade_years=0, trade_months=0, trade_days=7)
        m=self.market()
        dates=['2026-10-02','2026-10-05','2026-10-06','2026-10-07','2026-10-08','2026-10-09','2026-10-12','2026-10-13','2026-10-14']
        m['observations']=[dict(date=d,close=10+i) for i,d in enumerate(dates)]
        r=evaluate(c,m)['result']
        self.assertEqual((r['count'],r['start'],r['end']),(8,'2026-10-05','2026-10-14'))
        self.assertEqual(r['price'],22)
        c.update(trade_years=1,trade_months=2,trade_days=3)
        self.assertEqual(prepare(c)['period'],298)
        c.update(trade_years=0,trade_months=0,trade_days=0)
        with self.assertRaises(ValueError): prepare(c)
        c['trade_days']=10
        with self.assertRaises(ValueError): evaluate(c,m)

    def test_empty_exclusion(self):
        c=self.config('exclude')
        c.update(exclude_start='1900-01-01',exclude_end='2099-01-01')
        with self.assertRaises(ValueError): evaluate(c,self.market())
if __name__=='__main__': unittest.main()

