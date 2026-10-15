from copy import deepcopy
from pathlib import Path
import pandas as pd
from streamlit.testing.v1 import AppTest
from i18n import Translator, EXPLANATIONS
from momentum import CATALOG
import storage

APP=Path(__file__).resolve().parents[1]/'app.py'

def click(at,label):
    next(b for b in at.button if b.label==label).click().run()
    assert not at.exception

def test_every_formula_explanation_translates():
    en=Translator('en',CATALOG); ko=Translator('ko',CATALOG)
    assert set(EXPLANATIONS)==set(CATALOG)
    for kind,(_,explanation,_) in CATALOG.items():
        assert en(explanation)==EXPLANATIONS[kind]
        assert ko(explanation)==explanation
    assert en('기준값 (% / 퍼센트포인트)')=='Threshold (% / percentage points)'
    assert en('거래일 부족: 20 / 필요 61')=='Insufficient trading observations: 20 / required 61'

def test_table_copy_preserves_values_and_custom_names():
    frame=pd.DataFrame({'formula':['내 모멘텀 작업'],'reason':['가격 응답 없음'],'계산값':[.15]})
    translated=Translator('en',CATALOG).dataframe(frame)
    assert translated['Formula'][0]=='내 모멘텀 작업'
    assert translated['Reason'][0]=='No price response'
    assert translated['Calculated value'][0]==.15
    assert frame['reason'][0]=='가격 응답 없음'

def test_switch_language_preserves_settings_results_and_restart_preference(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    at=AppTest.from_file(str(APP),default_timeout=15).run()
    click(at,'종목 × 공식 추가')
    next(n for n in at.number_input if n.label.startswith('N ·')).set_value(40).run()
    next(s for s in at.text_input if s.label=='주식 / ETF 티커').set_value('QQQ').run()
    click(at,'카드 설정 적용')
    click(at,'모든 조회 카드 계산')
    original=deepcopy(at.session_state['runs'])
    queries=deepcopy(at.session_state['queries'])
    at.selectbox(key='language').select('en').run()
    assert not at.exception
    assert at.metric[0].label=='Calculated value'
    assert any(c.value.startswith('Period return.') for c in at.caption)
    assert at.session_state['runs']==original
    assert at.session_state['queries']==queries
    assert next(n for n in at.number_input if n.label.startswith('N ·')).value==40
    assert next(s for s in at.text_input if s.label=='Stock / ETF ticker').value=='QQQ'
    assert storage.get_language()=='en'
    click(at,'Save current workspace')
    record=storage.list_records()[0]
    assert record['payload']['settings']['language']=='en'
    restarted=AppTest.from_file(str(APP),default_timeout=15).run()
    assert restarted.selectbox(key='language').value=='en'
    assert any(b.label=='Add ticker × formula' for b in restarted.button)
    at.selectbox(key='language').select('ko').run()
    assert at.metric[0].label=='계산값'
    assert at.session_state['runs']==original
    next(s for s in at.selectbox if s.label=='저장본').select(record['id']).run()
    click(at,'불러오기')
    assert at.selectbox(key='language').value=='en'
    assert storage.get_language()=='en'

def test_english_filter_options_keep_canonical_calculation_ids(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    storage.set_language('en')
    at=AppTest.from_file(str(APP),default_timeout=15).run()
    at.segmented_control(key='mode').select('필터').run()
    click(at,'Add formula filter')
    click(at,'Add formula filter')
    next(s for s in at.selectbox if s.label=='1 · Universe').select('전체').run()
    at.segmented_control(key='combine').select('개별 (각 결과 유지)').run()
    click(at,'Run filters')
    result=at.session_state['runs'][0]['result']
    assert result['target_count']==8
    assert len(result['groups'])==2
    assert result['mode']=='필터'
    assert any(list(d.value.columns)==['Formula','Independent passes','Cumulative passes'] for d in at.dataframe)
