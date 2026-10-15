import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from notifications import put_rule, rules, drop_rule, check_rule, collect_cycle, save_report, last_report
from startup_notify import run_checks
from native_core import evaluate

def cfg(kind='RSI'):
    if kind=='RSI':
        return dict(kind=kind,symbol='SOXL',period=2,threshold=30.0,operator='<=')
    return dict(kind=kind,symbol='TQQQ',period_mode='calendar',years=0,months=3,days=0,threshold=2.0,operator='<=')

def market():
    return dict(observations=[dict(date=d,close=v) for d,v in
        [('2026-06-01',1),('2026-07-14',10),('2026-08-14',11),('2026-09-14',9),('2026-10-14',12)]],
        quote=dict(price=999,time='live',source='live'),fetched_at='2026-10-15T00:00:00Z',
        stale=False,expected_date='2026-10-14')

class Stop:
    def __init__(self): self.elapsed=0; self.waits=[]
    def is_set(self): return False
    def wait(self,delay):
        self.elapsed+=delay
        self.waits.append(delay)
        return len(self.waits)>5

class AlertTests(unittest.TestCase):
    def test_persistence_deduplicate_update_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'alerts.sqlite3'
            a=put_rule('SOXL',cfg(),path=path)
            self.assertEqual(a,put_rule('rename',cfg(),path=path))
            b=put_rule('TQQQ',cfg('Z-score'),path=path)
            self.assertEqual(len(rules(path)),2)
            c=cfg(); c['period']=14
            put_rule('RSI14',c,a,path)
            self.assertEqual(rules(path)[0]['config']['period'],14)
            drop_rule(a,path); drop_rule(b,path)
            self.assertEqual(rules(path),[])
            save_report('report',path)
            self.assertEqual(last_report(path),'report')

    def test_latest_close_not_live_and_relative_rolls(self):
        r=dict(id=1,name='t',config=cfg('Z-score'))
        with patch('notifications.fetch',return_value=market()), patch('notifications.evaluate',wraps=evaluate) as calc:
            text=check_rule(r)
            self.assertEqual(calc.call_args.args[1]['quote']['price'],12)
            self.assertIn('최신 확정 종가: $12.00',text)
            self.assertIn('2026-07-14',text)
        m=market()
        m['observations'].append(dict(date='2026-11-14',close=13))
        m['expected_date']='2026-11-14'
        with patch('notifications.fetch',return_value=m):
            self.assertIn('사용 종가: 2026-08-14',check_rule(r))

    def test_stale_is_retryable(self):
        m=market(); m['stale']=True
        with patch('notifications.fetch',return_value=m):
            with self.assertRaisesRegex(ValueError,'아직'):
                check_rule(dict(id=1,config=cfg()))

    def test_partial_failure_retries_only_failed_item(self):
        current=[dict(id=1,config=cfg()),dict(id=2,config=cfg('Z-score'))]
        attempts=[]
        def checker(rule):
            attempts.append(rule['id'])
            if rule['id']==2 and attempts.count(2)==1:
                raise ValueError('인터넷 연결 실패')
            return 'OK '+str(rule['id'])
        emitted=[]
        stop=Stop()
        run_checks(lambda *v:emitted.append(v),stop,loader=lambda:current,checker=checker,
                   clock=lambda:stop.elapsed,persist=lambda _:None)
        self.assertEqual(attempts,[1,2,2])
        self.assertEqual(stop.waits,[30])
        self.assertTrue(emitted[-1][1])

    def test_no_duplicate_completed_rule_and_rule_update(self):
        r=dict(id=1,config=cfg())
        success,errors=collect_cycle([r],{},checker=lambda _:'OK')
        with patch('notifications.check_rule',side_effect=AssertionError):
            again,_=collect_cycle([r],success,checker=lambda _:self.fail('Already complete'))
        changed=dict(r,config={**cfg(),'period':14})
        new,_=collect_cycle([changed],again,checker=lambda _:'UPDATED')
        self.assertEqual(list(new.values()),['UPDATED'])

    def test_once_no_retry_and_rate_limit_backoff(self):
        stop=Stop()
        current=[dict(id=1,config=cfg())]
        def checker(_): raise ValueError('요청 제한')
        emitted=[]
        run_checks(lambda *v:emitted.append(v),stop,once=True,loader=lambda:current,
                   checker=checker,persist=lambda _:None)
        self.assertFalse(stop.waits)
        self.assertTrue(emitted[-1][1])
        stop=Stop()
        def recovering(_):
            if not stop.waits: raise ValueError('요청 제한')
            return 'OK'
        run_checks(lambda *v:None,stop,loader=lambda:current,checker=recovering,
                   clock=lambda:stop.elapsed,persist=lambda _:None)
        self.assertEqual(stop.waits,[300])

    def test_removed_rule_not_displayed_after_fetch(self):
        r=dict(id=1,config=cfg())
        current=[r]
        def checker(_):
            current.clear()
            return 'REMOVED'
        emitted=[]
        run_checks(lambda *v:emitted.append(v),Stop(),loader=lambda:list(current),
                   checker=checker,persist=lambda _:None)
        self.assertTrue(all('REMOVED' not in v[0] for v in emitted))

if __name__=='__main__': unittest.main()

