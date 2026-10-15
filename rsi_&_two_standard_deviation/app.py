import json
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import altair as alt
import streamlit as st

from indicators import calculate, validate
from market_data import fetch
from storage import list_records, save, delete

st.set_page_config(page_title='RSI · Z-score', page_icon=':material/monitoring:', layout='wide')

DEFAULTS = dict(kind='RSI', symbol='TQQQ', period=14, rsi_threshold=30.0,
                z_threshold=2.0, operator='<=', name='TQQQ 분석', active_id=None,
                snapshot=None, saved_view=False, years=1, months=0, days=0,
                z_legacy_period=None, z_period_mode='calendar',
                start_date=date(2018, 5, 9), end_date=date(2020, 12, 30))
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


@st.cache_data(ttl=300, max_entries=32, show_spinner=False)
def load_market(config):
    try:
        return {'data': fetch(config)}
    except ValueError as exc:
        # Cache failures too, so repeated clicks do not hammer a limited server.
        return {'error': str(exc)}


st.title('RSI · Z-score')
st.caption('미국 주식과 ETF · 실제 거래일 기준 분석')
if notice := st.session_state.pop('notice', None):
    st.success(notice)

try:
    records = list_records()
except (sqlite3.Error, OSError) as exc:
    st.error(f'저장소를 열 수 없습니다: {exc}')
    st.stop()

with st.sidebar:
    st.header('저장한 분석')
    mapping = {r['id']: r for r in records}
    if records:
        chosen = st.selectbox('항목 선택', list(mapping),
                              format_func=lambda i: f"{mapping[i]['name']} · #{i}", key='saved_record')
        if st.button('불러오기', key='load', width='stretch'):
            record = mapping[chosen]
            loaded = json.loads(record['config'])
            for key in ('kind', 'symbol', 'operator'):
                st.session_state[key] = loaded[key]
            if loaded['kind'] == 'RSI':
                st.session_state.period = loaded['period']
            elif loaded.get('period_mode') == 'calendar':
                st.session_state.z_period_mode = 'calendar'
                for key in ('years', 'months', 'days'):
                    st.session_state[key] = loaded[key]
                st.session_state.z_legacy_period = None
            elif loaded.get('period_mode') in ('dates', 'since'):
                st.session_state.z_period_mode = loaded['period_mode']
                st.session_state.start_date = date.fromisoformat(loaded['start_date'])
                if loaded['period_mode'] == 'dates':
                    st.session_state.end_date = date.fromisoformat(loaded['end_date'])
                st.session_state.z_legacy_period = None
            else:
                st.session_state.z_legacy_period = loaded['period']
            st.session_state['rsi_threshold' if loaded['kind'] == 'RSI' else 'z_threshold'] = loaded['threshold']
            st.session_state.name = record['name']
            st.session_state.active_id = chosen
            st.session_state.snapshot = json.loads(record['snapshot']) if record['snapshot'] else None
            st.session_state.saved_view = True
        if st.button('삭제', key='delete', width='stretch'):
            try:
                delete(chosen)
                if st.session_state.active_id == chosen:
                    st.session_state.active_id = None
                    st.session_state.snapshot = None
                st.session_state.notice = '저장 항목을 삭제했습니다.'
                st.rerun()
            except (sqlite3.Error, OSError) as exc:
                st.error(f'삭제하지 못했습니다: {exc}')
    else:
        st.info('조건을 입력하고 저장하면 여기에 표시됩니다.')
    st.caption('조건과 조회 결과는 이 컴퓨터에 보관됩니다.')

with st.container(border=True):
    kind = st.segmented_control('분석 방식', ['RSI', 'Z-score'], key='kind', selection_mode='single')
    if not kind:
        st.info('RSI 또는 Z-score를 선택하세요.')
        st.stop()
    left, middle, right = st.columns(3)
    symbol = left.text_input('주식 이름 (티커)', key='symbol', placeholder='TQQQ')
    if kind == 'RSI':
        period = middle.number_input('기간 (거래일)', min_value=2, max_value=2520, step=1, key='period')
        threshold = right.number_input('RSI 수치', min_value=0.0, max_value=100.0, step=1.0, key='rsi_threshold')
        operator = st.selectbox('RSI 비교 조건', ['<=', '>='], key='operator')
        st.caption(f'최근 {period}거래일의 가격 변화 · 종가 {period + 1}개 사용 · 장중에는 직전 확정 종가 기준')
    else:
        threshold = right.number_input('몇 표준편차 (Z-score 기준 n)', min_value=0.01, max_value=100.0, step=0.1, key='z_threshold')
        operator = '<='
        if st.session_state.z_legacy_period is not None:
            st.info('기존에 저장한 거래일 방식입니다. 년·개월·일 방식으로 변경한 뒤 업데이트할 수 있습니다.')
            if st.button('년·개월·일 방식으로 변경', key='calendar_mode'):
                st.session_state.z_legacy_period = None
                st.rerun()
            period = middle.number_input('기존 기간 (거래일)', min_value=2, max_value=2520, step=1, key='z_legacy_period')
        else:
            st.markdown('**종가 데이터 이용 기간**')
            modes = {'calendar': '1. 몇 년·개월·일 전부터 최신 종가까지',
                     'dates': '2. 지정 시작일부터 지정 종료일까지',
                     'since': '3. 지정 시작일부터 최신 종가까지'}
            mode = st.selectbox('기간 선택 방식', list(modes), format_func=modes.get, key='z_period_mode')
            if mode == 'calendar':
                y, m, d = st.columns(3)
                years = y.number_input('년', min_value=0, max_value=30, step=1, key='years')
                months = m.number_input('개월', min_value=0, max_value=11, step=1, key='months')
                days = d.number_input('일', min_value=0, max_value=365, step=1, key='days')
                st.caption(f'최신 확정 종가 날짜부터 {years}년 {months}개월 {days}일 전까지')
            else:
                today = datetime.now(ZoneInfo('Asia/Seoul')).date()
                start_date = st.date_input('시작일', min_value=date(1900, 1, 1), max_value=today, key='start_date', format='YYYY-MM-DD')
                if mode == 'dates':
                    end_date = st.date_input('종료일', min_value=date(1900, 1, 1), max_value=today, key='end_date', format='YYYY-MM-DD')
                else:
                    st.caption('종료일은 조회 시점의 최신 확정 종가 날짜입니다.')
            st.caption('양 끝 날짜 포함 · 구간 내 거래일 종가만 사용 · 현재 가격을 이 구간의 평균·표준편차와 비교')
        st.caption(f'평균 ± {threshold:g}σ · |Z-score| ≤ {threshold:g}이면 범위 안')
    config = dict(kind=kind, symbol=symbol, threshold=float(threshold), operator=operator)
    if kind == 'Z-score' and st.session_state.z_legacy_period is None:
        config['period_mode'] = mode
        if mode == 'calendar':
            config.update(years=int(years), months=int(months), days=int(days))
        else:
            config['start_date'] = start_date.isoformat()
            if mode == 'dates':
                config['end_date'] = end_date.isoformat()
    else:
        config['period'] = int(period)
    analyze = st.button('분석 / 최신 데이터 조회', type='primary', key='analyze')
    st.caption('같은 종목·기간 조회는 5분간 재사용합니다. 결과에 표시된 조회 시각을 확인하세요.')

if analyze:
    st.session_state.snapshot = None
    try:
        config = validate(config)
        with st.spinner('거래일 종가와 최신 시세를 확인하고 있습니다…'):
            # A threshold/operator edit does not require another network request.
            query = {k: v for k, v in config.items() if k not in ('threshold', 'operator')}
            response = load_market(query)
            if 'error' in response:
                raise ValueError(response['error'])
            market = response['data']
            result = calculate(config, market['observations'], market['quote']['price'])
            st.session_state.snapshot = dict(config=config, result=result, quote=market['quote'],
                fetched_at=market['fetched_at'], stale=market['stale'], expected_date=market['expected_date'])
            st.session_state.saved_view = False
    except Exception as exc:
        if 'RateLimit' in type(exc).__name__ or 'Too Many Requests' in str(exc):
            st.error('Yahoo Finance의 요청 한도에 도달했습니다. 잠시 후 다시 조회하세요. 저장한 데이터는 왼쪽에서 불러올 수 있습니다.')
        else:
            st.error(f'분석하지 못했습니다: {exc}')

with st.container(border=True):
    st.text_input('저장 이름', key='name')
    if st.session_state.active_id:
        st.caption(f"불러온 항목: #{st.session_state.active_id} · 업데이트하면 이 항목을 덮어씁니다.")
    a, b = st.columns(2)
    create = a.button('새로 저장', key='save')
    update = b.button('선택 항목 업데이트', key='update', disabled=st.session_state.active_id is None)
    if create or update:
        try:
            config = validate(config)
            snapshot = st.session_state.snapshot
            if snapshot and snapshot['config'] != config:
                snapshot = None
            st.session_state.active_id = save(st.session_state.name, config, snapshot,
                                             st.session_state.active_id if update else None)
            st.session_state.notice = '조건과 조회 결과를 저장했습니다.' if snapshot else '조건을 저장했습니다. 조회 결과는 아직 없습니다.'
            st.rerun()
        except (ValueError, sqlite3.Error, OSError) as exc:
            st.error(f'저장하지 못했습니다: {exc}')

snapshot = st.session_state.snapshot
try:
    current_config = validate(config)
except ValueError:
    current_config = None

if snapshot and snapshot['config'] != current_config:
    st.info('조건이 바뀌었습니다. 분석 버튼을 눌러 새 결과를 확인하세요.')
elif snapshot:
    result = snapshot['result']
    st.subheader(f"{snapshot['config']['symbol']} 분석 결과")
    if st.session_state.saved_view:
        st.info('저장 당시 결과입니다. 현재 데이터로 바꾸려면 최신 데이터 조회 후 업데이트하세요.')
    st.caption(f"조회 시각 (UTC): {snapshot['fetched_at']} · 종가 범위: {result['start']} ~ {result['end']} · {result['count']}개")
    if result.get('requested_start'):
        st.caption(f"요청 구간: {result['requested_start']} ~ {result.get('requested_end', result['end'])} (양 끝 포함)")
    if snapshot['stale']:
        st.warning(f"최근 마감 거래일({snapshot['expected_date']})의 종가가 아직 제공되지 않아 {result['end']} 기준으로 계산했습니다.")
    if kind == 'RSI':
        a, b, c = st.columns(3)
        a.metric(f'RSI {period}', f"{result['value']:.2f}")
        b.metric('최근 확정 종가', f"${result['last_close']:,.2f}")
        c.metric('조건', f'{operator} {threshold:g}')
        (st.success if result['matched'] else st.info)('조건 충족' if result['matched'] else '조건 미충족')
    else:
        a, b, c = st.columns(3)
        a.metric('현재 비교 가격', f"${result['price']:,.2f}")
        b.metric('Z-score', f"{result['value']:+.3f}" if result['value'] is not None else '계산 불가')
        c.metric('종가 평균', f"${result['mean']:,.2f}")
        st.caption(f"가격 출처: {snapshot['quote']['source']} · 시세 시각: {snapshot['quote']['time']}")
        if result['value'] is None:
            st.warning('종가가 모두 같아 표준편차가 0입니다. Z-score와 범위 판정을 계산할 수 없습니다.')
        else:
            side = '위' if result['value'] > 0 else '아래' if result['value'] < 0 else '동일 위치'
            (st.success if result['matched'] else st.warning)(
                f"{'범위 안' if result['matched'] else '범위 밖'} · 평균 대비 {abs(result['value']):.3f}σ {side}")
        st.markdown(f"하단 **${result['low']:,.2f}** · 상단 **${result['high']:,.2f}** · 표준편차 **${result['std']:,.4f}**")
    chart = pd.DataFrame(result['observations']).set_index('date').rename(columns={'close': '종가'})
    if kind == 'Z-score':
        chart['평균'] = result['mean']
        chart['하단'] = result['low']
        chart['상단'] = result['high']
        chart['현재 비교 가격'] = result['price']
    st.subheader('주가 변화')
    st.line_chart(chart)
    if kind == 'RSI':
        st.subheader(f'RSI {period} 변화')
        history = result.get('rsi_history') or [{'date': result['end'], 'rsi': result['value']}]
        rsi_data = pd.DataFrame(history)
        # Keep both charts on the same trading-date domain, including missing warm-up points.
        dates = [row['date'] for row in result['observations']]
        line = alt.Chart(rsi_data).mark_line(point=True, color='#64b5f6').encode(
            x=alt.X('date:O', title='거래일', sort=dates, scale=alt.Scale(domain=dates)),
            y=alt.Y('rsi:Q', title='RSI', scale=alt.Scale(domain=[0, 100])),
            tooltip=[alt.Tooltip('date:O', title='거래일'), alt.Tooltip('rsi:Q', title='RSI', format='.2f')])
        rule = alt.Chart(pd.DataFrame({'threshold': [threshold]})).mark_rule(
            color='#ffb74d', strokeDash=[6, 4]).encode(
            y='threshold:Q', tooltip=[alt.Tooltip('threshold:Q', title='설정 기준')])
        st.altair_chart((line + rule).properties(height=260))
        st.caption(f'파란선: 날짜별 RSI · 주황 점선: 설정 기준 {operator} {threshold:g} · 각 날짜까지의 최근 {period}거래일 변화로 계산')
        if len(history) < len(dates):
            st.info('이전 종가가 부족한 날짜의 RSI는 표시하지 않습니다. 예전에 저장한 결과라면 최신 데이터 조회 후 업데이트하세요.')
    with st.expander('계산에 사용한 종가 보기'):
        st.dataframe(pd.DataFrame(result['observations']).rename(columns={'date': '거래일', 'close': '종가 (USD)'}), hide_index=True)
else:
    st.info('조건을 입력한 뒤 분석 버튼을 누르세요. 예: TQQQ / RSI / 기간 14 / 수치 30 / <=')

with st.expander('계산 방식 안내'):
    st.markdown('''
    - **기간:** RSI는 거래일 수입니다. Z-score는 상대 기간, 시작일~종료일, 시작일~최신 종가 중 선택합니다. 주말·휴장일은 제외하며 당일은 정규장 마감 후에만 포함합니다. 과거 구간을 선택해도 현재 가격을 비교합니다.
    - **RSI:** 최근 N번의 가격 변화에서 상승·하락분의 단순 평균을 사용합니다(종가 N+1개). 과거를 계속 평활하는 일반 차트의 Wilder RSI와 다를 수 있습니다. 가격 변동이 전혀 없으면 50으로 표시합니다.
    - **Z-score:** 선택한 구간의 종가를 사용하고 최소 2개가 필요합니다. 년·개월을 먼저 빼고 일을 뺍니다. 없는 날짜는 해당 월 말일로 맞춥니다(윤년 포함). `(현재가격 − 평균) / 모집단 표준편차`이며 경계값은 범위 안에 포함합니다.
    - **현재가격:** Yahoo 최근 정규장 시세로 지연될 수 있습니다. 제공되지 않으면 최신 확정 종가로 대체하고 출처를 표시합니다.
    - **저장:** 조건과 조회 당시 사용한 종가·분석 결과를 함께 저장합니다. 조건을 바꾼 뒤 조회하지 않으면 조건만 저장됩니다.
    ''')
