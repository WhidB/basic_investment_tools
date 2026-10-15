from collections import Counter
from dataclasses import asdict
import re
import pandas as pd
from momentum import Spec, calculate, cross_transform, required, screen
from market_data import load_prices, demo_prices

def symbols(text):
    values = list(dict.fromkeys(x.upper() for x in re.split(r'[\s,;]+', text.strip()) if x))
    if any(not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-^=]{0,19}', x) for x in values): raise ValueError('티커 형식을 확인하세요.')
    return values

def evaluate(config, universe_frame=None, progress=None):
    cards = config['cards']; demo = config['demo']; mode = config['mode']
    if not cards: raise ValueError('공식 카드를 먼저 추가하세요.')
    specs = {c['id']: Spec(**c['spec']) for c in cards}
    required_bars = max(required(s) for s in specs.values())
    if mode == '값 조회':
        target = list(dict.fromkeys(c['ticker'] for c in cards))
        references = symbols(config['references']) if any(s.kind in ('cross','z') for s in specs.values()) else []
        if any(s.kind in ('cross','z') for s in specs.values()) and len(references) < 2: raise ValueError('Cross-sectional / Z-score 비교 티커를 최소 2개 지정하세요.')
    else:
        if demo:
            target = ['SPY','QQQ','IWM','TLT','GLD','AAPL','MSFT','NVDA']
            if config['scope'] == 'ETF': target = target[:5]
            if config['scope'] == '개별 주식 (ETF 제외)': target = target[5:]
        else:
            if universe_frame is None: raise ValueError('전체 종목 목록을 불러오지 못했습니다.')
            frame = universe_frame
            if config['scope'] == 'ETF': frame = frame[frame.type == 'ETF']
            if config['scope'] == '개별 주식 (ETF 제외)': frame = frame[frame.type == 'Stock']
            target = frame.ticker.tolist()
        references = target
    needed = list(dict.fromkeys(target + references + [s.benchmark for s in specs.values() if s.kind == 'relative']))
    if demo:
        prices = {k:v.loc[:str(config['asof'])] for k,v in demo_prices().items() if k in needed}
        prices = {k:v for k,v in prices.items() if not v.empty}
        errors = {k:'데모에 없는 티커 또는 기준일 이전 가격 없음' for k in needed if k not in prices}
    else:
        prices, errors = load_prices(needed, required_bars, config['asof'], config['refresh'], progress)
    # Compare only the modal last trading date; exclude stale dates explicitly.
    dates = Counter(str(prices[t].index[-1].date()) for t in target if t in prices)
    if not dates: raise ValueError('가격 조회에 성공한 대상 종목이 없습니다. 데이터 연결과 티커를 확인하세요. '+str(dict(list(errors.items())[:3])))
    common_date = dates.most_common(1)[0][0]
    for ticker in list(prices):
        if str(prices[ticker].index[-1].date()) != common_date:
            errors[ticker] = '공통 평가일 불일치'; del prices[ticker]
    table = pd.DataFrame(index=target, dtype=float); details = {}; failures = []
    for card in cards:
        ident = card['id']; s = specs[ident]; candidates = references if s.kind in ('cross','z') else (target if mode == '필터' else [card['ticker']])
        candidates = list(dict.fromkeys(candidates + ([card['ticker']] if mode == '값 조회' and s.kind in ('cross','z') else [])))
        values = {}
        for ticker in candidates:
            try:
                if ticker not in prices: raise ValueError(errors.get(ticker,'가격 없음'))
                values[ticker] = calculate(prices[ticker], s, prices.get(s.benchmark))
            except (ValueError, KeyError, TypeError) as e: failures.append({'ticker':ticker, 'formula':card['name'], 'reason':str(e)})
        if s.kind in ('cross','z'):
            try:
                # Reference stats never include a query ticker outside the explicit comparison group.
                reference_values = {t:v for t,v in values.items() if t in references}
                transformed = cross_transform(reference_values, s.kind)
                if mode == '값 조회' and card['ticker'] not in references:
                    raise ValueError('조회 종목을 비교집단 티커에도 포함하세요.')
                values = transformed
            except ValueError as e:
                failures.append({'ticker':'비교집단','formula':card['name'],'reason':str(e)}); values = {}
        table[ident] = pd.Series({t:v['value'] for t,v in values.items()}, dtype=float)
        details[ident] = values
    result = {'target_count':len(target), 'price_count':sum(t in prices for t in target), 'date':common_date, 'details':details, 'failures':failures, 'demo':demo, 'mode':mode, 'cards':cards}
    if mode == '필터':
        rules = [dict(id=c['id'], **c['rule']) for c in cards]
        selection, ranking, steps = screen(table, rules, config['combine']=='누적 (교집합)')
        display = table.join(ranking, rsuffix='_rank')
        display = display.rename(columns={c['id']:c['name'] for c in cards} | {c['id']+'_rank':c['name']+' 순위' for c in cards})
        groups = {'최종 누적 결과':selection} if config['combine']=='누적 (교집합)' else {c['name']:selection[c['id']] for c in cards}
        result['groups'] = {name:display[mask].sort_values('Composite Score',ascending=False).reset_index(names='ticker').to_dict('records') for name,mask in groups.items()}
        result['steps'] = [dict(formula=next(c['name'] for c in cards if c['id']==i), independent_count=a, cumulative_count=b) for i,a,b in steps]
        result['valid_count'] = int(table.notna().all(axis=1).sum())
    return result
