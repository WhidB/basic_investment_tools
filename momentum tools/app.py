from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime
from zoneinfo import ZoneInfo
import json
import math
import uuid
import pandas as pd
import streamlit as st
from momentum import CATALOG, Spec, validate
from market_data import universe
from service import evaluate, symbols
import storage
from i18n import Translator

st.set_page_config(page_title='Momentum lab', page_icon=':material/trending_up:', layout='wide')
for key, default in [('queries',[]),('filters',[]),('runs',[]),('revision',0),('loaded_id',None)]:
    st.session_state.setdefault(key, deepcopy(default))
if 'restore_settings' in st.session_state:
    restored=st.session_state.pop('restore_settings')
    for k,v in restored.items():
        st.session_state[k]=date.fromisoformat(v) if k=='asof' else v
    if 'language' in restored: storage.set_language(restored['language'])

if 'language' not in st.session_state:
    st.session_state.language = storage.get_language()
with st.sidebar:
    st.selectbox('언어 / Language', ['ko','en'], format_func=lambda lang: {'ko':'한국어','en':'English'}[lang], key='language', on_change=lambda:storage.set_language(st.session_state.language))
t = Translator(st.session_state.language, CATALOG)
with st.sidebar:
    simple_view = st.toggle(t('간단히 보기'), value=True, key='simple_view')

def uid(): return uuid.uuid4().hex[:10]

def clean(value):
    if isinstance(value, dict): return {k:clean(v) for k,v in value.items()}
    if isinstance(value, list): return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value): return None
    if isinstance(value, date): return value.isoformat()
    return value

@st.cache_data(ttl=21600, max_entries=2)
def cached_universe(): return universe()

def editor(card, key, is_filter):
    s = Spec(**card['spec'])
    with st.container(border=True):
        st.markdown(f"**{card['name']}**")
        kind = st.selectbox(t('공식'), list(CATALOG), index=list(CATALOG).index(s.kind), format_func=lambda k:CATALOG[k][0], key=key+'kind')
        if not simple_view: st.caption(t(CATALOG[kind][1]))
        rule = deepcopy(card.get('rule',dict(op='>=',threshold=0.,upper=1.,top=10,ascending=False,rank_weight=1.)))
        if is_filter:
            rule['op'] = st.selectbox(t('조건'),['>=','>','<=','<','구간','Top N'],index=['>=','>','<=','<','구간','Top N'].index(rule['op']),format_func=t,key=key+"ui_'조건'")
        with st.form(key+'form'):
            ticker = None
            if kind == 'relative':
                if not is_filter:
                    left, right = st.columns(2)
                    with left:
                        ticker = st.text_input(t('대상 티커'), card.get('ticker','SPY'), placeholder='SPY', key=key+"ui_'주식 / ETF 티커'")
                    with right:
                        comparison_default = 'TQQQ' if s.kind!='relative' and s.benchmark==card.get('ticker','SPY') else s.benchmark
                        benchmark = st.text_input(t('비교 대상 티커'), comparison_default, placeholder='TQQQ', key=key+"ui_'벤치마크 티커'")
                    st.caption(t('대상 수익률 − 비교 대상 수익률. 양수이면 대상이 더 강합니다.'))
                else:
                    benchmark = st.text_input(t('비교 대상 티커'), s.benchmark, placeholder='SPY 또는 TQQQ', key=key+"ui_'벤치마크 티커'")
                    st.caption(t('선택한 시장의 각 종목을 이 티커와 비교합니다.'))
            elif not is_filter:
                ticker = st.text_input(t('주식 / ETF 티커'),card.get('ticker','SPY'), key=key+"ui_'주식 / ETF 티커'")
            n = s.n
            if kind not in ('multi','ema','macd','direction'):
                n = st.number_input(t('N · 기간 (거래일)'), min_value=2, max_value=1260,value=s.n, key=key+"ui_'N · 거래일 (기본 기간 / 위험 구간 / 회귀 구간)'")
            kwargs = asdict(s); kwargs.update(kind=kind,n=int(n))
            if kind == 'multi':
                horizons = st.text_input(t('기간들 · 쉼표 구분'), ','.join(map(str,s.horizons)), key=key+"ui_'기간들 · 쉼표 구분'")
                weights = st.text_input(t('가중치들 · 기간과 같은 개수'), ','.join(map(str,s.weights)), key=key+"ui_'가중치들 · 기간과 같은 개수'")
                st.caption(t('예: 20,40,120 / 0.5,0.3,0.2. 가중합을 그대로 계산합니다.'))
            if kind == 'skip': kwargs['skip'] = int(st.number_input(t('제외할 최근 거래일'),0,1259,s.skip, key=key+"ui_'제외할 최근 거래일'"))
            if kind == 'relative': kwargs['benchmark'] = benchmark.strip().upper()
            if kind in ('ema','macd','direction'):
                kwargs['short'] = int(st.number_input(t('단기 EMA / MA 기간'),1,1259,s.short, key=key+"ui_'단기 EMA / MA 기간'"))
                kwargs['long'] = int(st.number_input(t('장기 EMA / MA 기간'),2,1260,s.long, key=key+"ui_'장기 EMA / MA 기간'"))
            if kind == 'macd':
                kwargs['signal'] = int(st.number_input(t('시그널 EMA 기간'),1,252,s.signal, key=key+"ui_'시그널 EMA 기간'"))
                kwargs['component'] = st.selectbox(t('필터 / 대표값으로 사용할 구성값'),['histogram','macd','signal'],index=['histogram','macd','signal'].index(s.component), format_func=t, key=key+"ui_'필터 / 대표값으로 사용할 구성값'")
            if kind in ('slope','direction','autocorr'): kwargs['k'] = int(st.number_input(t('k · 비교 간격 / lag'),1,1259,s.k, key=key+"ui_'k · 비교 간격 / lag'"))
            if kind == 'vr': kwargs['q'] = int(st.number_input(t('q · 묶을 수익률 기간'),2,1259,s.q, key=key+"ui_'q · 묶을 수익률 기간'"))
            if kind == 'vol': kwargs['annualize'] = st.checkbox(t('변동성 분모 연율화 (√252)'),value=s.annualize, key=key+"ui_'변동성 분모 연율화 (√252)'")
            if kind == 'slope': kwargs['normalized'] = st.checkbox(t('기울기 정규화'),value=s.normalized, key=key+"ui_'기울기 정규화'")
            if kind == 'ma': kwargs['binary'] = st.checkbox(t('가격 > MA를 0/1로 계산'),value=s.binary, key=key+"ui_'가격 > MA를 0/1로 계산'")
            if kind == 'quality': quality = st.text_input(t('beta, R², ADX/100, 1+MDD 가중치'),','.join(map(str,s.quality_weights)), key=key+"ui_'beta, R², ADX/100, 1+MDD 가중치'")
            with st.expander(t('추가 설정'), expanded=not simple_view):
                name = st.text_input(t('카드 이름'), card['name'], key=key+"ui_'카드 이름'")
            if is_filter:
                percent = CATALOG[kind][2]=='percent' and not (kind=='ma' and kwargs['binary'])
                unit = '% / 퍼센트포인트' if percent else '공식 원래 단위'
                if rule['op'] != 'Top N':
                    threshold = st.number_input(t('기준값 ('+unit+')'),value=float(rule['threshold']*(100 if percent else 1)),format='%.6f', key=key+'ui_control_70')
                    rule['threshold'] = threshold/(100 if percent else 1)
                if rule['op']=='구간':
                    upper = st.number_input(t('구간 상한 ('+unit+')'),value=float(rule['upper']*(100 if percent else 1)),format='%.6f', key=key+'ui_control_71')
                    rule['upper'] = upper/(100 if percent else 1)
                if rule['op']=='Top N': rule['top'] = int(st.number_input(t('Top N · 동점 포함'),1,10000,rule['top'], key=key+"ui_'Top N · 동점 포함'"))
                with st.expander(t('순위 설정'), expanded=not simple_view):
                    rule['ascending'] = st.checkbox(t('작은 값이 높은 순위'),value=rule['ascending'], key=key+"ui_'작은 값이 높은 순위'")
                    rule['rank_weight'] = st.number_input(t('종합 순위 가중치'),0.,1000.,float(rule['rank_weight']), key=key+"ui_'종합 순위 가중치'")
            submitted = st.form_submit_button(t('카드 설정 적용'),type='primary')
        if submitted:
            try:
                if kind == 'multi':
                    kwargs['horizons'] = [int(x.strip()) for x in horizons.split(',')]
                    kwargs['weights'] = [float(x.strip()) for x in weights.split(',')]
                if kind == 'quality':
                    kwargs['quality_weights'] = [float(x.strip()) for x in quality.split(',')]
                    if len(kwargs['quality_weights']) != 4: raise ValueError(t('추세 품질 가중치 4개가 필요합니다.'))
                validate(Spec(**kwargs))
                if rule['op']=='구간' and rule['threshold'] > rule['upper']: raise ValueError(t('구간 하한이 상한보다 큽니다.'))
                if not name.strip(): raise ValueError(t('카드 이름이 필요합니다.'))
                updates=dict(name=name.strip(),spec=kwargs)
                if is_filter: updates['rule'] = rule
                else:
                    parsed = symbols(ticker)
                    if len(parsed)!=1: raise ValueError(t('카드당 티커 하나를 입력하세요.'))
                    updates['ticker'] = parsed[0]
                if kind=='relative' and len(symbols(kwargs['benchmark']))!=1: raise ValueError(t('벤치마크 티커 하나를 입력하세요.'))
                card.update(updates)
                st.success(t('설정을 적용했습니다. 실행 버튼을 누르면 새 값으로 계산합니다.'))
            except (ValueError,TypeError) as e: st.error(t(str(e)))
        if st.button(t('카드 삭제'),key=key+'delete'):
            collection = st.session_state.filters if is_filter else st.session_state.queries
            collection[:] = [c for c in collection if c['id']!=card['id']]; st.rerun()

def run_config(config):
    cfg = deepcopy(config)
    if isinstance(cfg['asof'],str): cfg['asof'] = date.fromisoformat(cfg['asof'])
    progress = st.progress(0.,text=t('가격과 공식을 계산합니다…'))
    frame = cached_universe() if not cfg['demo'] and cfg['mode']=='필터' else None
    result = evaluate(cfg,frame,lambda done,total:progress.progress(done/max(total,1),text=t(f'가격 다운로드 {done:,} / {total:,}')))
    progress.empty()
    return clean(result)

st.title(t('Momentum lab'))
st.caption(t('미국 상장 주식 · ETF | 공식별 값 비교, 전체 시장 필터, 구성값과 해석'))
with st.sidebar:
    st.header(t('데이터 설정'))
    demo = st.toggle(t('데모 데이터'),value=True,key='demo',help=t('합성 가격 8종목. 실제 시장 결과가 아닙니다.'))
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    asof = st.date_input(t('조회 기준일'),value=today,max_value=today,key='asof')
    with st.expander(t('데이터 상세'), expanded=not simple_view):
        refresh = st.checkbox(t('실행 시 가격 캐시 새로 받기'),key='refresh')
        st.caption(t('실제 데이터: Yahoo Finance 수정 OHLC(분할·배당 반영). 완료 일봉만 사용하며, 최신 날짜는 결과에 표시합니다.'))
        st.caption(t('ETF 제외 집합은 Nasdaq의 비ETF 상장 증권입니다. 보통주 외 우선주·ADR·워런트·펀드 등이 포함될 수 있으며 OTC는 제외됩니다.'))
    st.divider()
    st.header(t('저장한 작업'))
    records = storage.list_records()
    chosen = st.selectbox(t('저장본'), ['']+[r['id'] for r in records],format_func=lambda i:next((r['name'] for r in records if r['id']==i),t('선택하세요')), key="ui_'저장본'")
    workspace_name = st.text_input(t('저장 이름'),value=t('내 모멘텀 작업'), key="ui_'저장 이름'")
    payload = lambda:clean(dict(queries=st.session_state.queries, filters=st.session_state.filters,runs=st.session_state.runs,settings=dict(demo=demo,asof=asof,refresh=refresh,**{k:st.session_state[k] for k in ('language','simple_view','mode','scope','combine','references') if k in st.session_state})))
    if st.button(t('현재 작업 새로 저장'),width='stretch', key="ui_'현재 작업 새로 저장'"):
        st.session_state.loaded_id = storage.save(workspace_name,payload()); st.rerun()
    if chosen:
        record = next(r for r in records if r['id']==chosen)
        if st.button(t('불러오기'),width='stretch', key="ui_'불러오기'"):
            p = record['payload']
            for k in ('queries','filters','runs'): st.session_state[k]=deepcopy(p[k])
            st.session_state.loaded_id=chosen; st.session_state.revision+=1
            # Sidebar widgets were rendered; apply their restored values on next run.
            st.session_state['restore_settings']=p.get('settings',{})
            st.rerun()
        if st.button(t('선택 저장본 업데이트'),width='stretch', key="ui_'선택 저장본 업데이트'"):
            storage.save(workspace_name,payload(),chosen); st.success(t('설정과 결과를 업데이트했습니다.'))
        if st.button(t('선택 저장본 삭제'),width='stretch', key="ui_'선택 저장본 삭제'"):
            storage.delete(chosen); st.rerun()
        st.download_button(t('저장본 JSON 다운로드'),json.dumps(record['payload'],ensure_ascii=False,indent=2),file_name='momentum_workspace.json',mime='application/json', key="ui_'저장본 JSON 다운로드'")

if demo: st.info(t('데모 모드 · 재현 가능한 합성 데이터 8종목입니다. 전체 미국 시장 조회는 사이드바에서 데모를 끄세요.'),icon=':material/science:')
mode = st.segmented_control(t('먼저 작업을 선택하세요'),['값 조회','필터'],default='값 조회',key='mode', format_func=t) or '값 조회'
collection = st.session_state.queries if mode=='값 조회' else st.session_state.filters
is_filter = mode=='필터'
scope = '전체'; combine = '누적 (교집합)'; references = ''
if is_filter:
    scope = st.selectbox(t('1 · 대상 범위'),['ETF','개별 주식 (ETF 제외)','전체'],key='scope',persist_state='session', format_func=t)
    combine = st.segmented_control(t('2 · 필터 적용 방식'),['누적 (교집합)','개별 (각 결과 유지)'],default='누적 (교집합)',key='combine',persist_state='session', format_func=t) or '누적 (교집합)'
    st.caption(t('각 공식은 같은 전체 대상에서 평가합니다. 누적 모드는 통과 집합의 교집합을 계산합니다. Top N은 전체 대상 순위이며 동점을 포함합니다.'))
    if not demo:
        if st.button(t('전체 종목 목록 확인 / 갱신'), key="ui_'전체 종목 목록 확인 / 갱신'"):
            try:
                cached_universe.clear(); df=cached_universe(); st.session_state['universe_preview']=df
            except Exception as e: st.error(t(f'종목 목록 연결 실패: {e}'))
        if 'universe_preview' in st.session_state:
            df=st.session_state.universe_preview
            st.caption(t(f'목록 전체 {len(df):,} · ETF {(df.type=="ETF").sum():,} · 비ETF {(df.type=="Stock").sum():,}'))
            with st.expander(t('전체 종목 목록')): st.dataframe(t.dataframe(df),height=250)
        st.caption(t('전체 시장 다운로드는 수천 종목을 모두 요청합니다. 첫 실행은 오래 걸릴 수 있으며 이후에는 로컬 가격 캐시를 사용합니다.'))
else:
    if not simple_view or any(c['spec']['kind'] in ('cross','z') or st.session_state.get(c['id']+'_'+str(st.session_state.revision)+'kind') in ('cross','z') for c in collection):
        references = st.text_input(t('Cross-sectional / Z-score 비교집단 티커'),value='SPY,QQQ,IWM,TLT,GLD,AAPL,MSFT,NVDA',key='references',persist_state='session')
    else:
        references = st.session_state.get('references','SPY,QQQ,IWM,TLT,GLD,AAPL,MSFT,NVDA')
    if not simple_view: st.caption(t('티커 × 공식 카드를 원하는 만큼 추가하세요. 다른 카드를 계산해도 이전 결과는 유지됩니다.'))

if st.button(t('공식 필터 추가' if is_filter else '종목 × 공식 추가'),icon=':material/add:', key='add_card'):
    for existing in collection:
        st.session_state[f"card_panel_{existing['id']}_{st.session_state.revision}"] = False
    ident=uid()
    number=len(collection)+1
    prefix=t('필터' if is_filter else '조회')
    while f'{prefix} {number}' in {c['name'] for c in collection}: number+=1
    collection.append(dict(id=ident,name=f'{prefix} {number}',ticker='SPY',spec=asdict(Spec()),rule=dict(op='>=',threshold=0.,upper=1.,top=10,ascending=False,rank_weight=1.)))
    st.session_state[f'card_panel_{ident}_{st.session_state.revision}'] = True
    st.rerun()
if not collection: st.info(t('추가 버튼으로 첫 공식 카드를 만드세요.'))
for card in collection:
    # Only Add card explicitly opens a panel. Rerenders must never reopen the last card.
    with st.expander(card['name']+' · '+CATALOG[card['spec']['kind']][0],expanded=False,key=f"card_panel_{card['id']}_{st.session_state.revision}",on_change='rerun'):
        editor(card,card['id']+'_'+str(st.session_state.revision),is_filter)

config = dict(mode=mode,cards=deepcopy(collection),demo=demo,asof=asof,refresh=refresh,scope=scope,combine=combine,references=references)
if st.button(t('필터 실행' if is_filter else '모든 조회 카드 계산'),type='primary',disabled=not collection,key='execute'):
    try:
        names=[c['name'] for c in collection]
        if len(names)!=len(set(names)): raise ValueError(t('카드 이름은 서로 다르게 지정하세요.'))
        result=run_config(config)
        st.session_state.runs.insert(0,dict(id=uid(),name=f'{mode} 실행 {len(st.session_state.runs)+1}',config=clean(config),result=result))
        st.rerun()
    except Exception as e: st.error(t(f'실행 실패: {e}'))

st.divider()
st.header(t('보관된 실행 결과'))
if not simple_view: st.caption(t('카드 설정을 수정해도 이전 실행값은 그대로 남습니다. 실행 업데이트로 해당 결과를 다시 계산하거나 전체 작업을 저장할 수 있습니다.'))
for run in list(st.session_state.runs):
    result = run['result']; key=run['id']
    with st.container(border=True):
        run_number = run['name'].rsplit(' ',1)[-1]
        st.subheader(f"{t(result['mode'])} · {run_number}"+t(' · 데모' if result['demo'] else ' · 실제 데이터'))
        st.caption(t(f"기준 거래일 {result['date']} · 가격 조회 {result['price_count']:,}/{result['target_count']:,} · 실행 방식 {run['config'].get('combine','')}"))
        with st.container(horizontal=True):
            if st.button(t('실행 업데이트'),key=key+'update'):
                try:
                    updated=deepcopy(run['config']); updated.update(asof=asof.isoformat(),refresh=True)
                    run['result']=run_config(updated); run['config']=updated; st.rerun()
                except Exception as e: st.error(t(str(e)))
            if st.button(t('실행 삭제'),key=key+'delete'):
                st.session_state.runs=[r for r in st.session_state.runs if r['id']!=key]; st.rerun()
            st.download_button(t('결과 JSON'),json.dumps(run,ensure_ascii=False,indent=2),file_name='momentum_result.json',mime='application/json',key=key+'json')
        if result['mode']=='값 조회':
            for card in result['cards']:
                spec=Spec(**card['spec']); item=result['details'][card['id']].get(card['ticker'])
                st.markdown(f"**{card['name']} · {card['ticker']} · {CATALOG[spec.kind][0]}**")
                if item:
                    percent=CATALOG[spec.kind][2]=='percent' and not (spec.kind=='ma' and spec.binary)
                    if spec.kind=='relative':
                        a,b,c=st.columns(3)
                        a.metric(f"{t('대상 수익률')} · {card['ticker']}",f"{item['details']['Momentum']:.2%}")
                        b.metric(f"{t('비교 대상 수익률')} · {spec.benchmark}",f"{item['details']['Benchmark Momentum']:.2%}")
                        c.metric(t('상대 모멘텀'),f"{item['value']*100:+.2f} pp")
                        st.caption(f"{card['ticker']} − {spec.benchmark} · {t('대상 수익률 − 비교 대상 수익률. 양수이면 대상이 더 강합니다.')}")
                    else:
                        st.metric(t('계산값'),f"{item['value']:.2%}" if percent else f"{item['value']:.6f}")
                    st.caption(t(CATALOG[spec.kind][1]))
                    with st.expander(t('계산 상세'),expanded=not simple_view):
                        d=pd.DataFrame([{'구성값':k,'값':v} for k,v in item['details'].items()]); st.dataframe(t.dataframe(d),hide_index=True)
                        st.caption(t(f"관측일 {item['observations']} · 설정 {json.dumps(card['spec'],ensure_ascii=False)}"))
                else: st.warning(t('계산 불가 · 아래 실패 목록을 확인하세요.'))
        else:
            st.caption(t(f"모든 공식에 유효한 종목 {result['valid_count']:,}. 종합 점수는 공식별 유리한 방향의 백분위(0~100)를 순위 가중치로 평균합니다. 전체 대상 기준 순위이며, 누락 종목의 종합 점수는 비워둡니다."))
            st.dataframe(t.dataframe(pd.DataFrame(result['steps']).rename(columns={'formula':'공식','independent_count':'개별 통과','cumulative_count':'누적 통과'})),hide_index=True)
            for name, rows in result['groups'].items():
                group_name = t(name) if name == '최종 누적 결과' else name
                st.markdown(f"**{group_name} · {len(rows):,} {t('종목')}**")
                df=pd.DataFrame(rows)
                if df.empty: st.info(t('통과 종목이 없습니다.'))
                else:
                    st.dataframe(t.dataframe(df),hide_index=True,height=350)
                    export_df = t.dataframe(df)
                    st.download_button(t('CSV 다운로드 · ')+group_name,export_df.to_csv(index=False).encode('utf-8-sig'),file_name='momentum_filter.csv',mime='text/csv',key=key+name+'csv')
            with st.expander(t('공식 해석과 종목별 구성값')):
                for card in result['cards']: st.markdown(f"**{card['name']}**: {t(CATALOG[card['spec']['kind']][1])}")
                choices=sorted({t for vals in result['details'].values() for t in vals})
                ticker=st.selectbox(t('구성값 확인 티커'),choices,key=key+'detailticker') if choices else None
                if ticker:
                    for card in result['cards']:
                        item=result['details'][card['id']].get(ticker)
                        if item:
                            st.markdown('**'+card['name']+'**'); st.json(item)
            st.caption(t('수익률 계열 표·CSV는 소수 단위입니다: 0.15=15%. 상대 모멘텀 0.08=8퍼센트포인트. RSI/ADX는 0~100, R²는 0~1입니다.'))
        if result['failures']:
            with st.expander(f"{t('조회 / 계산 실패 ')}{len(result['failures']):,} {t('건')}",expanded=False):
                failed=pd.DataFrame(result['failures']); st.dataframe(t.dataframe(failed),hide_index=True)
                st.download_button(t('실패 목록 CSV'),t.dataframe(failed).to_csv(index=False).encode('utf-8-sig'),file_name='momentum_failures.csv',key=key+'failcsv')

with st.expander(t('공식 안내 · 계산 규칙')):
    st.caption(t('모든 기간은 거래일. 변동성은 표본 표준편차(ddof=1), 횡단면 Z-score는 모집단 표준편차(ddof=0). EMA는 adjust=False, RSI/ADX는 SMA 초기값의 Wilder smoothing. Hurst는 로그 가격 차분의 R/S 추정입니다. 회귀·MDD는 N개 가격 관측, ROC는 N개 수익률(N+1개 가격)을 사용합니다.'))
    st.dataframe(t.dataframe(pd.DataFrame([{'공식':a,'해석':b,'단위':c} for a,b,c in CATALOG.values()])),hide_index=True)
    st.markdown(t('[Nasdaq 종목 분류](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs) · [가격 데이터 라이브러리](https://ranaroussi.github.io/yfinance/index.html)'))
