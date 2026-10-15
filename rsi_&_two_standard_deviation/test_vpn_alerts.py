import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from notifications import put_rule, rules, check_rule, canonical
from startup_notify import run_checks
from test_notifications import cfg, market, Stop

class VpnAlertTests(unittest.TestCase):
    def test_custom_threshold_persisted_and_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'alerts.sqlite3'
            for n, result_word in [(1.25,'외'),(3.75,'내')]:
                c=cfg('Z-score'); c['threshold']=n
                put_rule('custom',c,path=path)
                r=rules(path)[-1]
                self.assertEqual(r['config']['threshold'],n)
                with patch('notifications.fetch',return_value=market()):
                    text=check_rule(r)
                self.assertIn(f'{n:g}표준편차 {result_word}에',text)
                self.assertIn(f'±{n:g}σ',text)

    def test_legacy_internet_and_vpn_can_coexist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'alerts.sqlite3'
            original=put_rule('old',cfg(),path=path)
            internet=put_rule('internet',{**cfg(),'alert_connection':'internet'},path=path)
            self.assertEqual(original,internet)
            vpn=put_rule('vpn',{**cfg(),'alert_connection':'vpn'},path=path)
            self.assertNotEqual(original,vpn)
            self.assertEqual(len(rules(path)),2)
            self.assertEqual(rules(path)[-1]['config']['alert_connection'],'vpn')
            with self.assertRaises(ValueError):
                canonical({**cfg(),'alert_connection':'invalid'})

    def test_vpn_wait_is_silent_until_data_accessible(self):
        current=[dict(id=1,config={**cfg(),'alert_connection':'vpn'})]
        stop=Stop()
        events=[]
        def offline(_): raise ValueError('주가 서버 연결 실패')
        run_checks(lambda *e:events.append(e),stop,loader=lambda:current,checker=offline,
                   clock=lambda:stop.elapsed,persist=lambda _:self.fail('No automatic report while VPN offline'))
        self.assertEqual(events,[])
        self.assertEqual(stop.waits,[30]*6)

    def test_mixed_modes_internet_is_not_blocked_by_vpn(self):
        current=[dict(id=1,config=cfg()),dict(id=2,config={**cfg('Z-score'),'alert_connection':'vpn'})]
        attempts=[]
        def checker(rule):
            attempts.append(rule['id'])
            if rule['id']==2 and attempts.count(2)<3: raise ValueError('VPN 연결 전')
            return 'SUCCESS '+str(rule['id'])
        stop=Stop(); events=[]
        run_checks(lambda *e:events.append(e),stop,loader=lambda:current,checker=checker,
                   clock=lambda:stop.elapsed,persist=lambda _:None)
        self.assertEqual(attempts,[1,2,2,2])
        self.assertEqual(len(events),2)
        self.assertIn('SUCCESS 1',events[0][0])
        self.assertNotIn('SUCCESS 2',events[0][0])
        self.assertIn('SUCCESS 2',events[1][0])
        self.assertTrue(events[1][3]) # alert again when VPN finishes
        self.assertTrue(events[1][1])

    def test_internet_errors_still_report_and_manual_vpn_check_reports(self):
        def offline(_): raise ValueError('서버 연결 실패')
        for mode,once in [('internet',False),('vpn',True)]:
            stop=Stop(); events=[]
            current=[dict(id=1,config={**cfg(),'alert_connection':mode})]
            run_checks(lambda *e:events.append(e),stop,once=once,loader=lambda:current,checker=offline,
                       clock=lambda:stop.elapsed,persist=lambda _:None)
            self.assertTrue(events)
            self.assertIn('서버 연결 실패',events[0][0])

if __name__=='__main__': unittest.main()

