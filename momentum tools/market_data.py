from io import StringIO
from urllib.request import Request, urlopen
from pathlib import Path
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf

CACHE = Path(__file__).resolve().parent / 'data' / 'prices'

def universe():
    frames = []
    for file, symbol in [('nasdaqlisted.txt', 'Symbol'), ('otherlisted.txt', 'ACT Symbol')]:
        request = Request('https://www.nasdaqtrader.com/dynamic/SymDir/'+file, headers={'User-Agent':'MomentumResearch/1.0'})
        with urlopen(request, timeout=30) as response: raw = response.read().decode('utf-8')
        df = pd.read_csv(StringIO(raw), sep='|', dtype=str)
        df = df[(df['Test Issue'] == 'N') & df['ETF'].isin(['Y','N'])]
        frames.append(pd.DataFrame({'ticker':df[symbol], 'name':df['Security Name'], 'type':df['ETF'].map({'Y':'ETF','N':'Stock'})}))
    result = pd.concat(frames).drop_duplicates('ticker').sort_values('ticker').reset_index(drop=True)
    if len(result) < 1000: raise ValueError('종목 목록이 비정상적으로 짧습니다. 전체시장 조회를 중단합니다.')
    return result

def yahoo_symbol(ticker):
    return ticker.replace('.', '-')

def load_prices(tickers, bars, asof, refresh=False, progress=None):
    """Full requested universe, batched downloads; no silent truncation."""
    CACHE.mkdir(parents=True, exist_ok=True)
    asof = min(asof, datetime.now(ZoneInfo('America/New_York')).date()-timedelta(days=1))
    results, errors, pending = {}, {}, []
    start = asof - timedelta(days=max(730, int(bars*2.2)+120))
    for ticker in dict.fromkeys(tickers):
        filename = CACHE / (yahoo_symbol(ticker).replace('/','_')+'_'+asof.isoformat()+'.csv')
        if filename.exists() and not refresh:
            try:
                f = pd.read_csv(filename, index_col=0, parse_dates=True)
                if len(f) >= bars and (asof-f.index[-1].date()).days <= 7: results[ticker] = f; continue
            except (ValueError, OSError): pass
        pending.append(ticker)
    for offset in range(0, len(pending), 50):
        batch = pending[offset:offset+50]; symbols = [yahoo_symbol(t) for t in batch]
        try:
            downloaded = yf.download(symbols, start=start.isoformat(), end=(asof+timedelta(days=1)).isoformat(), auto_adjust=True, group_by='ticker', threads=4, progress=False, timeout=20)
            for ticker, symbol in zip(batch, symbols):
                try:
                    if isinstance(downloaded.columns, pd.MultiIndex): f = downloaded[symbol].copy()
                    else: f = downloaded.copy()
                    f.index = pd.to_datetime(f.index).tz_localize(None)
                    f = f[['Open','High','Low','Close','Volume']].dropna(subset=['Close']).sort_index()
                    f = f[~f.index.duplicated(keep='last')]
                    if f.empty: raise ValueError('가격 응답 없음')
                    if (asof-f.index[-1].date()).days > 7: raise ValueError('최근 가격 없음(7일 초과)')
                    # Keep short-history IPOs: each formula checks its own observation requirement.
                    if not np.isfinite(f[['Open','High','Low','Close']]).all().all(): raise ValueError('OHLC 누락')
                    results[ticker] = f
                    f.to_csv(CACHE / (yahoo_symbol(ticker).replace('/','_')+'_'+asof.isoformat()+'.csv'))
                except (KeyError, ValueError, TypeError) as e: errors[ticker] = str(e)
        except Exception as e:
            for ticker in batch: errors[ticker] = str(e)
        if progress: progress(min(offset+50,len(pending)),len(pending))
    return results, errors

def demo_prices():
    rng = np.random.default_rng(42); dates = pd.bdate_range(end='2026-09-30', periods=1800)
    result = {}
    for i, ticker in enumerate(['SPY','QQQ','IWM','TLT','GLD','AAPL','MSFT','NVDA']):
        close = 100*np.exp(np.cumsum(rng.normal(.0002+i*.00006,.009+i*.001,len(dates))))
        result[ticker] = pd.DataFrame({'Open':close, 'High':close*1.012, 'Low':close*.988, 'Close':close, 'Volume':1000000}, index=dates)
    # Extra synthetic comparison series for trying SPY vs TQQQ, outside the eight-symbol demo scan.
    q = result['QQQ'].Close.pct_change(fill_method=None).fillna(0.)
    c = 100 * (1 + (3*q).clip(lower=-.99)).cumprod()
    result['TQQQ'] = pd.DataFrame({'Open':c,'High':c*1.012,'Low':c*.988,'Close':c,'Volume':1000000},index=dates)
    return result
