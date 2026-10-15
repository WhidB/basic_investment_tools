"""Pure calculations. All windows are trading observations, returns are decimals."""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

CATALOG = {
    'roc': ('Price Momentum / ROC', '기간 수익률. 0.15는 +15%입니다.', 'percent'),
    'log': ('Log Momentum', '로그 수익률. 실제 수익률은 exp(값)-1입니다.', 'number'),
    'multi': ('Multi-Horizon Momentum', '기간별 수익률의 가중합. 가중치를 자동 정규화하지 않습니다.', 'percent'),
    'skip': ('Skip-Month Momentum', '최근 skip 거래일을 제외한 과거 구간 수익률입니다.', 'percent'),
    'relative': ('Relative Momentum', '동일 날짜의 벤치마크 수익률 대비 초과 수익률(퍼센트포인트)입니다.', 'percent'),
    'cross': ('Cross-Sectional Momentum', '지정 비교집단 안의 수익률 백분위. 100이 가장 높습니다.', 'number'),
    'ts': ('Time-Series Momentum', '자산 자체의 수익률 부호: +1 상승, 0 보합, -1 하락입니다.', 'number'),
    'vol': ('Volatility-Adjusted Momentum', '수익률 / 일별 표준편차. 연율화 옵션은 분모에 sqrt(252)를 곱합니다.', 'number'),
    'down': ('Downside-Adjusted Momentum', '수익률 / 하방 RMS. 하락일만이 아니라 전체 N일로 나눕니다.', 'number'),
    'z': ('Momentum Z-score', '비교집단 평균 대비 표준편차 거리. +1이면 평균보다 1표준편차 높습니다.', 'number'),
    'ema': ('EMA Momentum', '단기 EMA / 장기 EMA - 1. 양수이면 단기 추세가 더 높습니다.', 'percent'),
    'macd': ('MACD', 'MACD·시그널·히스토그램을 함께 표시합니다. 가격 단위라 종목 간 직접 비교에 주의하세요.', 'number'),
    'rsi': ('RSI', 'Wilder RSI(0~100). 높은 값은 상승 강도이며 자동 매수 신호는 아닙니다.', 'number'),
    'distance': ('Moving Average Distance', '가격 / 이동평균 - 1. 양수이면 이동평균 위입니다.', 'percent'),
    'slope': ('Moving Average Slope', 'k 거래일에 걸친 이동평균 변화 / k. 정규화 옵션은 비율로 계산합니다.', 'number'),
    'regression': ('Regression Momentum', '로그 가격 회귀의 일별 기울기 × R². 양수는 일관된 상승 경향입니다.', 'number'),
    'ma': ('Moving-Average Momentum', '가격과 MA 거리 또는 가격 > MA의 0/1 신호입니다. Distance와 같은 계열입니다.', 'percent'),
    'consistency': ('Trend Consistency Momentum', '기간 수익률 × 상승일 비중. 상승일 비중도 함께 표시합니다.', 'percent'),
    'autocorr': ('Return Autocorrelation', '양수는 지속성, 음수는 반전 경향. 표본의 잡음이 크며 유의성 검정은 아닙니다.', 'number'),
    'vr': ('Variance Ratio', '1 초과는 양의 시계열 의존, 1 미만은 음의 의존과 일관됩니다. 검정 통계량은 아닙니다.', 'number'),
    'adx': ('ADX', 'Wilder ADX(0~100)는 방향과 무관한 추세 강도입니다. +DI/-DI를 함께 확인하세요.', 'number'),
    'r2': ('Regression R²', '0~1. 1에 가까우면 로그 가격이 직선 추세를 잘 따릅니다. 방향은 beta로 확인합니다.', 'number'),
    'hurst': ('Hurst Exponent', 'R/S 추정. 0.5 초과 지속성, 미만 반지속성의 후보이나 방법·표본 의존성이 큽니다.', 'number'),
    'direction': ('Trend Direction', '가격 > 단기 MA > 장기 MA 및 장기 MA 기울기 > 0을 모두 만족하면 1입니다.', 'number'),
    'speed': ('Trend Speed', '로그 가격 회귀의 일별 beta. 양수 상승, 음수 하락입니다.', 'number'),
    'mdd': ('Maximum Drawdown', '구간 최대 낙폭(음수). -0.05는 -5%; 0에 가까울수록 낙폭이 작습니다.', 'percent'),
    'quality': ('Composite Trend Quality', 'beta·R²·ADX/100·(1+MDD)의 사용자 가중합. 단위가 달라 연구용 설정이 필요합니다.', 'number'),
}

@dataclass
class Spec:
    kind: str = 'roc'
    n: int = 60
    skip: int = 21
    horizons: list = field(default_factory=lambda: [20, 60, 120, 252])
    weights: list = field(default_factory=lambda: [.4, .3, .2, .1])
    benchmark: str = 'SPY'
    short: int = 12
    long: int = 26
    signal: int = 9
    k: int = 5
    q: int = 5
    annualize: bool = False
    normalized: bool = True
    binary: bool = False
    component: str = 'histogram'
    quality_weights: list = field(default_factory=lambda: [1., 1., 1., 1.])

def validate(s):
    if s.kind not in CATALOG: raise ValueError('알 수 없는 공식')
    for key in ('n', 'short', 'long', 'signal', 'k', 'q'):
        if getattr(s, key) < 1: raise ValueError('기간은 1 이상이어야 합니다.')
    if s.kind == 'skip' and not 0 <= s.skip < s.n: raise ValueError('skip은 전체 기간보다 작아야 합니다.')
    if s.kind in ('ema', 'macd', 'direction') and s.short >= s.long: raise ValueError('단기 기간은 장기 기간보다 작아야 합니다.')
    if len(s.horizons) != len(s.weights) or not s.horizons or min(s.horizons) < 1: raise ValueError('기간과 가중치 개수가 같아야 합니다.')
    if not np.isfinite(s.weights + s.quality_weights).all(): raise ValueError('가중치는 유한한 숫자여야 합니다.')
    if s.kind == 'vr' and not 2 <= s.q < s.n: raise ValueError('VR은 2 ≤ q < N이어야 합니다.')
    if s.kind == 'autocorr' and s.k >= s.n - 1: raise ValueError('lag는 N-1보다 작아야 합니다.')

def required(s):
    validate(s)
    if s.kind == 'multi': return max(s.horizons) + 1
    if s.kind in ('ema', 'macd'): return 5 * (s.long + s.signal)
    if s.kind in ('adx', 'quality'): return max(s.n + 1, 6 * s.n)
    if s.kind == 'direction': return s.long + s.k
    if s.kind == 'slope': return s.n + s.k
    if s.kind == 'rsi': return 6 * s.n + 1
    return s.n + 1

def wilder(x, n):
    """SMA seed then Wilder recursive smoothing, preserving leading NA."""
    out = pd.Series(np.nan, index=x.index, dtype=float)
    start = x.first_valid_index()
    if start is None: return out
    i = x.index.get_loc(start) + n - 1
    if i >= len(x): return out
    out.iloc[i] = x.iloc[i-n+1:i+1].mean()
    for j in range(i+1, len(x)):
        out.iloc[j] = (out.iloc[j-1] * (n-1) + x.iloc[j]) / n
    return out

def adx(frame, n):
    h, l, c = frame.High, frame.Low, frame.Close
    up, down = h.diff(), -l.diff()
    plus = up.where((up > down) & (up > 0), 0.)
    minus = down.where((down > up) & (down > 0), 0.)
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr = wilder(tr, n)
    p = 100 * wilder(plus, n) / atr.replace(0, np.nan)
    m = 100 * wilder(minus, n) / atr.replace(0, np.nan)
    dx = 100 * (p-m).abs() / (p+m).replace(0, np.nan)
    return {'ADX': float(wilder(dx, n).iloc[-1]), '+DI': float(p.iloc[-1]), '-DI': float(m.iloc[-1])}

def regression(c, n):
    y = np.log(c.iloc[-n:].to_numpy()); x = np.arange(n)
    if n < 3: raise ValueError('회귀에는 최소 3개 관측이 필요합니다.')
    beta, intercept = np.polyfit(x, y, 1)
    ss = np.sum((y-y.mean())**2)
    r2 = 0. if ss < 1e-20 else max(0., min(1., 1-np.sum((y-(intercept+beta*x))**2)/ss))
    return float(beta), float(r2)

def calculate(frame, s, benchmark=None):
    validate(s)
    frame = frame.sort_index().copy()
    c = frame.Close.astype(float)
    if len(c) < required(s): raise ValueError(f'거래일 부족: {len(c)} / 필요 {required(s)}')
    if not np.isfinite(c).all() or (c <= 0).any(): raise ValueError('가격 누락 또는 0 이하 가격')
    r = c.pct_change(fill_method=None).dropna().iloc[-s.n:]
    roc = lambda n: float(c.iloc[-1] / c.iloc[-n-1] - 1)
    m = roc(s.n) if len(c) > s.n else float('nan'); d = {'Momentum': m}; kind = s.kind
    if kind in ('roc', 'cross', 'z'): value = m
    elif kind == 'log': value = float(np.log1p(m))
    elif kind == 'multi':
        d = {f'M_{n}': roc(n) for n in s.horizons}
        value = sum(w * roc(n) for w, n in zip(s.weights, s.horizons))
        d.update({f'w_{i+1}': w for i,w in enumerate(s.weights)})
    elif kind == 'skip': value = float(c.iloc[-s.skip-1] / c.iloc[-s.n-1]-1)
    elif kind == 'relative':
        if benchmark is None: raise ValueError('벤치마크 데이터가 필요합니다.')
        aligned = pd.concat([c.rename('asset'), benchmark.Close.rename('benchmark')], axis=1, join='inner').dropna()
        if len(aligned) < s.n+1 or aligned.index[-1] != c.index[-1]: raise ValueError('벤치마크 동일 날짜 데이터 부족')
        if aligned.index[-s.n-1] != c.index[-s.n-1]: raise ValueError('벤치마크 비교 시작 날짜 불일치')
        b = float(aligned.benchmark.iloc[-1]/aligned.benchmark.iloc[-s.n-1]-1)
        value = m-b; d['Benchmark Momentum'] = b
    elif kind == 'ts': value = float(np.sign(m))
    elif kind in ('vol', 'down'):
        sigma = float(r.std(ddof=1)) if kind == 'vol' else float(np.sqrt(np.mean(np.minimum(r, 0)**2)))
        if sigma <= 1e-14 or not np.isfinite(sigma): raise ValueError('위험 분모가 0 또는 정의 불가')
        denom = sigma * (np.sqrt(252) if s.annualize and kind == 'vol' else 1)
        value = m / denom; d['Daily Risk'] = sigma; d['Denominator'] = denom
    elif kind in ('ema', 'macd'):
        a = c.ewm(span=s.short, adjust=False).mean(); b = c.ewm(span=s.long, adjust=False).mean()
        d = {'EMA Short': float(a.iloc[-1]), 'EMA Long': float(b.iloc[-1])}
        if kind == 'ema': value = float(a.iloc[-1]/b.iloc[-1]-1)
        else:
            line = a-b; sig = line.ewm(span=s.signal, adjust=False).mean()
            d.update({'MACD': float(line.iloc[-1]), 'Signal': float(sig.iloc[-1]), 'Histogram': float((line-sig).iloc[-1])})
            value = d[{'macd':'MACD','signal':'Signal','histogram':'Histogram'}[s.component]]
    elif kind == 'rsi':
        diff = c.diff(); gain = wilder(diff.clip(lower=0), s.n).iloc[-1]; loss = wilder(-diff.clip(upper=0), s.n).iloc[-1]
        value = 50. if gain == loss == 0 else (100. if loss == 0 else float(100-100/(1+gain/loss)))
        d = {'Average Gain': float(gain), 'Average Loss': float(loss)}
    elif kind in ('distance', 'ma', 'slope', 'direction'):
        ma = c.rolling(s.n).mean(); d['MA'] = float(ma.iloc[-1])
        if kind in ('distance', 'ma'):
            value = float(c.iloc[-1]/ma.iloc[-1]-1)
            if kind == 'ma' and s.binary: value = float(c.iloc[-1] > ma.iloc[-1])
        elif kind == 'slope':
            value = float((ma.iloc[-1]/ma.iloc[-s.k-1]-1)/s.k) if s.normalized else float((ma.iloc[-1]-ma.iloc[-s.k-1])/s.k)
        else:
            a = c.rolling(s.short).mean(); b = c.rolling(s.long).mean(); slope = float((b.iloc[-1]/b.iloc[-s.k-1]-1)/s.k)
            value = float(c.iloc[-1] > a.iloc[-1] > b.iloc[-1] and slope > 0)
            d = {'Price': float(c.iloc[-1]), 'MA Short': float(a.iloc[-1]), 'MA Long': float(b.iloc[-1]), 'Long MA Slope': slope}
    elif kind in ('regression', 'r2', 'speed', 'quality'):
        beta, r2 = regression(c, s.n); d = {'Beta': beta, 'R²': r2}
        value = {'regression': beta*r2, 'r2': r2, 'speed': beta, 'quality': 0}[kind]
        if kind == 'quality':
            a = adx(frame, s.n)['ADX']; window = c.iloc[-s.n:]; dd = float((window/window.cummax()-1).min())
            d.update({'ADX': a, 'MDD': dd}); value = float(np.dot(s.quality_weights, [beta,r2,a/100,1+dd]))
    elif kind == 'consistency':
        consistency = float((r > 0).mean()); value = m*consistency; d['Positive Day Ratio'] = consistency
    elif kind == 'autocorr': value = float(r.autocorr(s.k))
    elif kind == 'vr':
        variance = float(r.var(ddof=1))
        if variance <= 1e-20: raise ValueError('수익률 분산이 0')
        value = float(r.rolling(s.q).sum().dropna().var(ddof=1)/(s.q*variance))
    elif kind == 'adx': d = adx(frame, s.n); value = d['ADX']
    elif kind == 'hurst':
        x = np.log(c.iloc[-s.n:].to_numpy()); sizes = np.unique(np.geomspace(8, len(x)//2, 8).astype(int)); points = []
        for size in sizes:
            ratios = []
            for start in range(0, len(x)-size+1, size):
                segment = np.diff(x[start:start+size]); std = segment.std(ddof=1)
                if std > 1e-14: ratios.append(np.ptp(np.cumsum(segment-segment.mean()))/std)
            if ratios and np.mean(ratios) > 0: points.append((size, np.mean(ratios)))
        if len(points) < 3: raise ValueError('Hurst 추정에는 충분한 변동과 최소 64일 이상이 필요합니다.')
        value = float(np.polyfit(np.log(np.array(points)[:,0]), np.log(np.array(points)[:,1]), 1)[0]); d = {'R/S scales': len(points)}
    elif kind == 'mdd':
        window = c.iloc[-s.n:]; value = float((window/window.cummax()-1).min())
    else: raise ValueError(kind)
    if not np.isfinite(value): raise ValueError('계산값이 정의되지 않습니다(변동 없음/데이터 부족).')
    return {'value': float(value), 'details': d, 'date': str(c.index[-1].date()), 'observations': len(c)}

def cross_transform(results, kind):
    values = pd.Series({k:v['value'] for k,v in results.items()}, dtype=float)
    if len(values) < 2: raise ValueError('횡단면 비교에는 유효 종목이 최소 2개 필요합니다.')
    if kind == 'z':
        std = values.std(ddof=0)
        if std < 1e-14: raise ValueError('비교집단 모멘텀 표준편차가 0입니다.')
        transformed = (values-values.mean())/std
    else: transformed = (values.rank(method='average')-1)/(len(values)-1)*100
    for ticker, result in results.items():
        result['details']['Raw Momentum'] = result['value']; result['details']['Reference Size'] = len(values)
        result['value'] = float(transformed[ticker])
    return results

def screen(table, rules, cumulative):
    """Rules carry id/op/threshold/upper/top/ascending/rank_weight."""
    masks, ranks, steps = {}, {}, []
    survivors = pd.Series(True, index=table.index)
    for rule in rules:
        v = table[rule['id']]; op = rule['op']; t = rule['threshold']; asc = rule['ascending']
        rank = v.rank(ascending=asc, method='min'); ranks[rule['id']] = rank
        if op == 'Top N': mask = rank <= rule['top']
        elif op == '>=': mask = v >= t
        elif op == '<=': mask = v <= t
        elif op == '>': mask = v > t
        elif op == '<': mask = v < t
        else: mask = v.between(t, rule['upper'])
        mask = mask & v.notna(); masks[rule['id']] = mask
        survivors &= mask
        steps.append((rule['id'], int(mask.sum()), int(survivors.sum())))
    ranking = pd.DataFrame(ranks)
    # Best=100, worst=0, equal values share score; missing values never get a score.
    scores = []
    for rule in rules:
        v = table[rule['id']]; count = v.notna().sum()
        p = v.rank(ascending=not rule['ascending'], method='average')
        score = (p-1)/(count-1)*100 if count > 1 else p.where(p.isna(), 100.)
        scores.append(score * rule['rank_weight'])
    denominator = sum(r['rank_weight'] for r in rules)
    if denominator <= 0: raise ValueError('순위 가중치 합은 양수여야 합니다.')
    ranking['Composite Score'] = pd.concat(scores, axis=1).sum(axis=1, min_count=len(rules))/denominator
    ranking['Overall Rank'] = ranking['Composite Score'].rank(ascending=False, method='min')
    return (survivors if cumulative else masks), ranking, steps
