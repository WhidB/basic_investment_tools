from datetime import date
from indicators import validate, calculate
from market_data import fetch

MODES = {
    'dates': '지정 시작일 ~ 지정 종료일',
    'since': '지정 시작일 ~ 최신 종가',
    'listing': '상장일 ~ 최신 종가',
    'exclude': '상장일 ~ 최신 종가 (지정 구간 제외)',
    'calendar': '몇 년·개월·일 전 ~ 최신 종가',
}

def prepare(config):
    c = dict(config)
    mode = c.get('period_mode')
    if mode in ('listing', 'exclude'):
        if mode == 'exclude':
            try:
                a, b = date.fromisoformat(c['exclude_start']), date.fromisoformat(c['exclude_end'])
            except (KeyError, ValueError):
                raise ValueError('제외 구간 날짜를 YYYY-MM-DD 형식으로 입력하세요.')
            if a > b:
                raise ValueError('제외 시작일은 제외 종료일보다 늦을 수 없습니다.')
        c.update(period_mode='since', start_date='1900-01-01')
    return validate(c)

def analyze(config):
    query = prepare(config)
    market = fetch(query)
    return evaluate(config, market)

def evaluate(config, market):
    query = prepare(config)
    all_rows = market['observations']
    selected = all_rows
    if config.get('period_mode') == 'exclude':
        selected = [r for r in all_rows
                    if not config['exclude_start'] <= r['date'] <= config['exclude_end']]
    result = calculate(query, selected, market['quote']['price'])
    result['excluded_count'] = len(all_rows) - len(selected)
    return dict(config=config, result=result, quote=market['quote'],
                fetched_at=market['fetched_at'], stale=market['stale'],
                expected_date=market['expected_date'])

def describe(snapshot):
    c, r = snapshot['config'], snapshot['result']
    lines = [f"{c['symbol']} · {c['kind']}", f"조회 시각 (UTC): {snapshot['fetched_at']}",
             f"사용 종가: {r['start']} ~ {r['end']} / {r['count']}개"]
    if c['kind'] == 'RSI':
        lines += [f"현재 RSI({c['period']}): {r['value']:.2f}",
                  f"최신 확정 종가: ${r['last_close']:,.2f}",
                  '최근 N거래일 변화의 단순 평균 방식 (기존 앱과 동일)']
    else:
        delta = r['price'] - r['mean']
        side = '높습니다' if delta > 0 else '낮습니다' if delta < 0 else '같습니다'
        lines += [f"현재 비교 가격: ${r['price']:,.2f}",
                  f"평균: ${r['mean']:,.2f} / 표준편차: ${r['std']:,.4f}",
                  f"평균보다 {abs(delta):,.2f}달러 ({abs(delta/r['mean']*100):.2f}%) {side}"]
        if r['value'] is None:
            lines += ['표준편차가 0이므로 Z-score와 범위 판정은 계산할 수 없습니다.']
        else:
            lines += [f"{c['threshold']:g}표준편차 {'내' if r['matched'] else '외'}에 있습니다.",
                      f"현재 위치: Z-score {r['value']:+.3f}",
                      f"범위: ${r['low']:,.2f} ~ ${r['high']:,.2f}"]
        lines += [f"시세 출처: {snapshot['quote']['source']} / {snapshot['quote']['time']}"]
        if c.get('period_mode') in ('listing', 'exclude'):
            lines += ['상장 이후 제공처에서 조회 가능한 종가를 사용합니다. 최초 제공일은 위 사용 구간을 확인하세요.']
        if c.get('period_mode') == 'exclude':
            lines += [f"제외: {c['exclude_start']} ~ {c['exclude_end']} (양 끝 포함), {r.get('excluded_count', 0)}개"]
    if snapshot['stale']:
        lines += [f"주의: 최근 마감 거래일({snapshot['expected_date']}) 데이터가 아직 제공되지 않았습니다."]
    return '\n'.join(lines)


