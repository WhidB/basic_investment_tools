from functools import partial
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import streamlit as st
import storage


class AppFlow(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()

    def test_analyze_save_load_update_delete_and_switch(self):
        data = dict(observations=[dict(date=f'2026-01-{i+1:02d}', close=float(i+10)) for i in range(20)],
                    quote=dict(price=29.0, time='2026-01-20', source='test'),
                    fetched_at='2026-01-20T22:00:00+00:00', stale=False, expected_date='2026-01-20')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ui.sqlite3'
            with patch('storage.list_records', partial(storage.list_records, path=path)), \
                 patch('storage.save', partial(storage.save, path=path)), \
                 patch('storage.delete', partial(storage.delete, path=path)), \
                 patch('market_data.fetch', return_value=data) as fetch_mock:
                at = AppTest.from_file('app.py', default_timeout=20).run()
                self.assertFalse(at.exception)
                at.button(key='analyze').click().run()
                self.assertFalse(at.exception)
                self.assertEqual(at.metric[0].value, '100.00')
                self.assertEqual(len(at.get('vega_lite_chart')), 2)
                self.assertIn('RSI 14 변화', [h.value for h in at.subheader])
                at.button(key='analyze').click().run()
                self.assertEqual(fetch_mock.call_count, 1)
                at.button(key='save').click().run()
                self.assertFalse(at.exception)
                at.number_input(key='period').set_value(5).run()
                at.button(key='load').click().run()
                self.assertEqual(at.number_input(key='period').value, 14)
                self.assertEqual(len(at.get('vega_lite_chart')), 2)
                at.number_input(key='rsi_threshold').set_value(40.0).run()
                at.button(key='update').click().run()
                self.assertFalse(at.exception)
                self.assertEqual(len(storage.list_records()), 1)
                with patch('market_data.fetch', side_effect=ValueError('데이터 조회 실패')):
                    st.cache_data.clear()
                    at.button(key='analyze').click().run()
                    self.assertFalse(at.exception)
                    self.assertTrue(at.error)
                    self.assertEqual(len(at.metric), 0)
                st.cache_data.clear()
                at.session_state['kind'] = 'Z-score'
                at.run()
                at.number_input(key='years').set_value(1)
                at.number_input(key='months').set_value(2)
                at.number_input(key='days').set_value(3).run()
                at.button(key='analyze').click().run()
                self.assertFalse(at.exception)
                self.assertIn('Z-score', [m.label for m in at.metric])
                self.assertEqual(len(at.get('vega_lite_chart')), 1)
                at.selectbox(key='z_period_mode').select('dates').run()
                from datetime import date
                at.date_input(key='start_date').set_value(date(2026,1,2))
                at.date_input(key='end_date').set_value(date(2026,1,10)).run()
                at.button(key='analyze').click().run()
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state.snapshot['result']['count'], 9)
                at.button(key='save').click().run()
                fixed = storage.list_records()[0]
                at.selectbox(key='z_period_mode').select('since').run()
                at.button(key='analyze').click().run()
                self.assertFalse(at.exception)
                self.assertEqual(at.session_state.snapshot['result']['count'], 19)
                at.selectbox(key='saved_record').select(fixed['id']).run()
                at.button(key='load').click().run()
                self.assertEqual(at.selectbox(key='z_period_mode').value, 'dates')
                self.assertEqual(at.date_input(key='end_date').value, date(2026,1,10))
                at.button(key='delete').click().run()
                at.selectbox(key='z_period_mode').select('calendar').run()
                at.number_input(key='months').set_value(2)
                at.number_input(key='days').set_value(3).run()
                at.button(key='analyze').click().run()
                at.button(key='save').click().run()
                self.assertEqual(len(storage.list_records()), 2)
                new_record = storage.list_records()[0]
                at.selectbox(key='saved_record').select(new_record['id']).run()
                at.button(key='load').click().run()
                self.assertEqual(at.number_input(key='months').value, 2)
                self.assertEqual(at.number_input(key='days').value, 3)
                self.assertFalse(at.exception)
                at.button(key='delete').click().run()
                self.assertFalse(at.exception)
                self.assertEqual(len(storage.list_records()), 1)


if __name__ == '__main__':
    unittest.main()
