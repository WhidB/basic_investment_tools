import unittest
from unittest.mock import patch
from notifications import check_rule
from test_notifications import cfg, market, Stop
from startup_notify import run_checks

class FormatTests(unittest.TestCase):
    def test_rsi_fields_only(self):
        with patch('notifications.fetch',return_value=market()):
            text=check_rule(dict(id=1,config=cfg()))
        self.assertEqual([line.split(':')[0] for line in text.splitlines()[1:]],
                         ['현재 RSI','사용 종가','최근 확정 종가'])
        self.assertNotIn('조회 시각',text)
        self.assertNotIn('단순 평균',text)

    def test_zscore_fields_and_historical_range_close(self):
        c=cfg('Z-score')
        c.update(period_mode='dates',start_date='2026-07-14',end_date='2026-08-14',threshold=1.25)
        with patch('notifications.fetch',return_value=market()):
            text=check_rule(dict(id=1,config=c))
        self.assertEqual([line.split(':')[0] for line in text.splitlines()[1:]],
                         ['현재 위치','해석','사용 종가','최신 확정 종가','평균','범위'])
        self.assertIn('최신 확정 종가: $12.00 (2026-10-14)',text)
        self.assertIn('평균: $10.50',text)
        self.assertIn('1.25표준편차 외',text)

    def test_flat_prices_have_no_fake_position(self):
        m=market()
        for row in m['observations']: row['close']=10
        with patch('notifications.fetch',return_value=m):
            text=check_rule(dict(id=1,config=cfg('Z-score')))
        self.assertIn('현재 위치: 계산 불가',text)
        self.assertIn('표준편차가 0',text)

    def test_no_success_boilerplate(self):
        r=dict(id=1,config=cfg())
        events=[]
        run_checks(lambda *v:events.append(v),Stop(),once=True,loader=lambda:[r],
                   checker=lambda r:'compact report',persist=lambda _:None)
        self.assertEqual(events[0][0],'compact report')

if __name__=='__main__': unittest.main()

