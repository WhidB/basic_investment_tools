from pathlib import Path
from streamlit.testing.v1 import AppTest
import storage

APP=Path(__file__).resolve().parents[1]/'app.py'

def click_label(at,label):
    next(b for b in at.button if b.label==label).click().run()
    assert not at.exception

def test_query_persistence_and_saved_restore(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    at=AppTest.from_file(str(APP),default_timeout=15).run()
    assert not at.exception
    click_label(at,'종목 × 공식 추가')
    click_label(at,'모든 조회 카드 계산')
    assert len(at.session_state['runs'])==1
    assert at.metric[0].label=='계산값'
    click_label(at,'종목 × 공식 추가')
    click_label(at,'모든 조회 카드 계산')
    assert len(at.session_state['runs'])==2
    assert len(at.metric)==3
    click_label(at,'현재 작업 새로 저장')
    assert len(storage.list_records())==1
    # Remove current cards, then restore the saved cards and all runs.
    at.session_state['queries']=[]
    at.run()
    selector=next(s for s in at.selectbox if s.label=='저장본')
    selector.select(storage.list_records()[0]['id']).run()
    click_label(at,'불러오기')
    assert len(at.session_state['queries'])==2
    assert len(at.session_state['runs'])==2

def test_filter_mode_and_multiple_groups(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    at=AppTest.from_file(str(APP),default_timeout=15).run()
    at.segmented_control(key='mode').select('필터').run()
    assert not at.exception
    click_label(at,'공식 필터 추가')
    click_label(at,'공식 필터 추가')
    at.segmented_control(key='combine').select('개별 (각 결과 유지)').run()
    click_label(at,'필터 실행')
    result=at.session_state['runs'][0]['result']
    assert len(result['groups'])==2
    assert len(result['steps'])==2

def test_simple_view_relative_pair_can_be_changed_and_reversed(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    at=AppTest.from_file(str(APP),default_timeout=15).run()
    assert at.toggle(key='simple_view').value is True
    assert not any(s.label.startswith('Cross-sectional') for s in at.text_input)
    click_label(at,'종목 × 공식 추가')
    next(s for s in at.selectbox if s.label=='공식').select('relative').run()
    assert next(s for s in at.text_input if s.label=='대상 티커').value=='SPY'
    assert next(s for s in at.text_input if s.label=='비교 대상 티커').value=='TQQQ'
    click_label(at,'카드 설정 적용')
    click_label(at,'모든 조회 카드 계산')
    first=at.session_state['runs'][0]['result']
    card=first['cards'][0]
    value=first['details'][card['id']]['SPY']['value']
    assert card['spec']['benchmark']=='TQQQ'
    assert any(m.label=='상대 모멘텀' for m in at.metric)
    next(s for s in at.text_input if s.label=='대상 티커').set_value('TQQQ').run()
    next(s for s in at.text_input if s.label=='비교 대상 티커').set_value('SPY').run()
    click_label(at,'카드 설정 적용')
    click_label(at,'모든 조회 카드 계산')
    second=at.session_state['runs'][0]['result']
    assert abs(second['details'][card['id']]['TQQQ']['value']+value)<1e-12
    assert len(at.session_state['runs'])==2
    at.selectbox(key='language').select('en').run()
    assert not at.exception
    assert any(s.label=='Target ticker' for s in at.text_input)
    assert any(s.label=='Comparison ticker' for s in at.text_input)

def test_filter_only_shows_relevant_condition_inputs(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    at=AppTest.from_file(str(APP),default_timeout=15).run()
    at.segmented_control(key='mode').select('필터').run()
    click_label(at,'공식 필터 추가')
    assert not any(n.label.startswith('구간 상한') for n in at.number_input)
    next(s for s in at.selectbox if s.label=='조건').select('Top N').run()
    assert not at.exception
    assert any(n.label=='Top N · 동점 포함' for n in at.number_input)
    assert not any(n.label.startswith('기준값') for n in at.number_input)

def test_repeated_mode_switch_keeps_cards_and_existing_results(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    at=AppTest.from_file(str(APP),default_timeout=15).run()
    click_label(at,'종목 × 공식 추가')
    click_label(at,'모든 조회 카드 계산')
    query_id=at.session_state['queries'][0]['id']
    at.segmented_control(key='mode').select('필터').run()
    assert not at.exception
    click_label(at,'공식 필터 추가')
    click_label(at,'필터 실행')
    filter_id=at.session_state['filters'][0]['id']
    for language in ('ko','en'):
        at.selectbox(key='language').select(language).run()
        for simple in (True,False):
            at.toggle(key='simple_view').set_value(simple).run()
            for mode in ('값 조회','필터','값 조회','필터'):
                at.segmented_control(key='mode').select(mode).run()
                assert not at.exception
                assert at.session_state['mode']==mode
                assert at.session_state['queries'][0]['id']==query_id
                assert at.session_state['filters'][0]['id']==filter_id
                assert len(at.session_state['runs'])==2

def test_add_filter_opens_fresh_card_and_closes_previous_without_losing_settings(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    at=AppTest.from_file(str(APP),default_timeout=15).run()
    at.segmented_control(key='mode').select('필터').run()
    click_label(at,'공식 필터 추가')
    first=at.session_state['filters'][0]
    next(n for n in at.number_input if n.label.startswith('N ·')).set_value(40).run()
    click_label(at,'카드 설정 적용')
    click_label(at,'공식 필터 추가')
    first,second=at.session_state['filters']
    assert first['spec']['n']==40
    assert second['spec']['n']==60
    assert second['spec']['kind']=='roc'
    assert first['id']!=second['id']
    rev=at.session_state['revision']
    assert at.session_state[f"card_panel_{first['id']}_{rev}"] is False
    assert at.session_state[f"card_panel_{second['id']}_{rev}"] is True
    # Opening the previous card manually must not prevent the next add from focusing the new card.
    at.session_state[f"card_panel_{first['id']}_{rev}"]=True
    at.run()
    click_label(at,'공식 필터 추가')
    cards=at.session_state['filters']
    assert [at.session_state[f"card_panel_{c['id']}_{rev}"] for c in cards]==[False,False,True]
    assert cards[0]['spec']['n']==40

def test_run_filter_does_not_reopen_closed_last_panel(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    at=AppTest.from_file(str(APP),default_timeout=15).run()
    at.segmented_control(key='mode').select('필터').run()
    click_label(at,'공식 필터 추가')
    click_label(at,'공식 필터 추가')
    cards=at.session_state['filters']
    rev=at.session_state['revision']
    for card in cards: at.session_state[f"card_panel_{card['id']}_{rev}"]=False
    at.run()
    click_label(at,'필터 실행')
    for card in cards:
        assert at.session_state[f"card_panel_{card['id']}_{rev}"] is False
        panel=next(p for p in at.get('expander') if p.label.startswith(card['name']+' · '))
        assert panel.proto.expanded is False
    # Returning to the filter screen must also default to closed, not reopen the last card.
    at.segmented_control(key='mode').select('값 조회').run()
    at.segmented_control(key='mode').select('필터').run()
    assert not at.exception
    panels=[p for p in at.get('expander') if any(p.label.startswith(c['name']+' · ') for c in cards)]
    assert len(panels)==2
    assert all(not p.proto.expanded for p in panels)
