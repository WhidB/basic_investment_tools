from datetime import date, datetime, timedelta, timezone
import math

import pandas as pd
import pandas_market_calendars as mcal
import requests

from indicators import calendar_start


def completed_closes(history, now):
    if history.empty or 'Close' not in history:
        raise ValueError('종가 데이터가 없습니다. 티커와 네트워크 연결을 확인하세요.')
    series = history['Close'].dropna().sort_index()
    if series.empty:
        raise ValueError('유효한 종가 데이터가 없습니다.')
    schedule = mcal.get_calendar('NYSE').schedule(
        start_date=series.index[0].date(), end_date=now.date())
    completed = schedule[schedule['market_close'] <= pd.Timestamp(now)]
    valid_dates = {d.date().isoformat() for d in completed.index}
    rows = {}
    for stamp, value in series.items():
        date = stamp.date().isoformat()
        if date in valid_dates and math.isfinite(float(value)) and value > 0:
            rows[date] = {'date': date, 'close': float(value)}
    return list(rows.values()), (completed.index[-1].date().isoformat() if len(completed) else None)


def fetch(config):
    """Use one chart request for history and the timestamped regular quote.

    No cookie/crumb lookup is needed. HTTP 429 is honored without retries.
    """
    now = datetime.now(timezone.utc)
    if config['kind'] == 'Z-score' and config.get('period_mode') in ('dates', 'since'):
        start = date.fromisoformat(config['start_date'])
        if start > now.date():
            raise ValueError('시작일은 미래 날짜일 수 없습니다.')
    elif config['kind'] == 'Z-score' and config.get('period_mode') == 'calendar':
        start = calendar_start(config, now.date()) - timedelta(days=40)
    else:
        # N earlier closes warm up the rolling RSI for every date in the chart.
        count = 2 * config['period'] + 1 if config['kind'] == 'RSI' else config['period']
        start = now.date() - timedelta(days=max(60, count * 2 + 30))
    params = {'period1': int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp()),
              'period2': int(now.timestamp()), 'interval': '1d', 'includePrePost': 'false'}
    try:
        response = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{config['symbol']}",
                                params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        if response.status_code == 429:
            raise ValueError('Yahoo 시세 서버가 일시적으로 요청을 제한했습니다. 5분 후 다시 조회하세요.')
        if response.status_code == 404:
            raise ValueError('종목을 찾을 수 없습니다. 미국 주식 티커를 확인하세요.')
        response.raise_for_status()
        chart = response.json()['chart']
        if chart.get('error') or not chart.get('result'):
            raise ValueError('주가 데이터가 없습니다. 티커를 확인하세요.')
        payload = chart['result'][0]
        metadata = payload['meta']
        history = pd.DataFrame({'Close': payload['indicators']['quote'][0]['close']},
            index=pd.to_datetime(payload['timestamp'], unit='s', utc=True).tz_convert('America/New_York'))
    except requests.RequestException as exc:
        raise ValueError('주가 서버에 연결하지 못했습니다. 인터넷 연결을 확인한 후 다시 시도하세요.') from exc
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('주가 서버 응답에 종가 데이터가 없습니다.') from exc
    if metadata.get('exchangeTimezoneName') != 'America/New_York' or metadata.get('currency') != 'USD':
        raise ValueError('현재는 미국 증시의 USD 주식·ETF만 지원합니다.')
    rows, expected_date = completed_closes(history, now)
    if not rows:
        raise ValueError('장이 끝난 거래일의 종가를 찾을 수 없습니다.')
    quote = {'price': rows[-1]['close'], 'time': rows[-1]['date'], 'source': '최신 확정 종가 (시세 대체)'}
    if config['kind'] == 'Z-score':
        price, stamp = metadata.get('regularMarketPrice'), metadata.get('regularMarketTime')
        if isinstance(price, (int, float)) and math.isfinite(price) and price > 0 and isinstance(stamp, (int, float)):
            quote_time = datetime.fromtimestamp(stamp, timezone.utc)
            market_date = pd.Timestamp(quote_time).tz_convert('America/New_York').date().isoformat()
            if market_date >= rows[-1]['date'] and quote_time <= now:
                quote = {'price': float(price), 'time': quote_time.isoformat(),
                         'source': 'Yahoo 최근 정규장 시세 (지연 가능)'}
    return {'observations': rows, 'quote': quote, 'fetched_at': now.isoformat(),
            'stale': rows[-1]['date'] != expected_date, 'expected_date': expected_date}
