"""Calculations over completed trading-session observations only."""
import math
import re
import statistics
from datetime import date
from dateutil.relativedelta import relativedelta


def calendar_start(config, end):
    """Subtract calendar years/months (month-end clamped), then days."""
    return end - relativedelta(years=config['years'], months=config['months'], days=config['days'])


def rsi_value(values):
    changes = [b - a for a, b in zip(values, values[1:])]
    gain = sum(max(v, 0) for v in changes)
    loss = sum(max(-v, 0) for v in changes)
    return (50.0 if gain == 0 else 100.0) if loss == 0 else 100 - 100 / (1 + gain / loss)


def rsi_history(observations, period):
    """Each point uses only the N changes ending on that trading date."""
    values = [float(row['close']) for row in observations]
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('유효하지 않은 종가가 있습니다.')
    return [{'date': observations[i]['date'], 'rsi': rsi_value(values[i-period:i+1])}
            for i in range(max(period, len(values) - period - 1), len(values))]


def validate(config):
    config = dict(config)
    config['symbol'] = config['symbol'].strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', config['symbol']):
        raise ValueError('미국 주식 티커를 입력하세요. 예: TQQQ, AAPL, BRK-B')
    if config['kind'] not in ('RSI', 'Z-score'):
        raise ValueError('지원하지 않는 지표입니다.')
    if config['kind'] == 'Z-score' and config.get('period_mode') in ('dates', 'since'):
        try:
            start = date.fromisoformat(config['start_date'])
            end = date.fromisoformat(config['end_date']) if config['period_mode'] == 'dates' else None
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError('유효한 시작일과 종료일을 선택하세요.') from exc
        if end is not None and start > end:
            raise ValueError('시작일은 종료일보다 늦을 수 없습니다.')
    elif config['kind'] == 'Z-score' and config.get('period_mode') == 'calendar':
        for key, maximum in [('years', 30), ('months', 11), ('days', 365)]:
            if type(config.get(key)) is not int or not 0 <= config[key] <= maximum:
                raise ValueError('기간은 년 0~30, 개월 0~11, 일 0~365로 입력하세요.')
        if not any(config[key] for key in ('years', 'months', 'days')):
            raise ValueError('기간을 1일 이상 입력하세요.')
    elif type(config.get('period')) is not int or not 2 <= config['period'] <= 2520:
        raise ValueError('기간은 2~2520 거래일로 입력하세요.')
    if not math.isfinite(config['threshold']):
        raise ValueError('유효한 기준 수치를 입력하세요.')
    if config['kind'] == 'RSI' and not 0 <= config['threshold'] <= 100:
        raise ValueError('RSI 수치는 0~100입니다.')
    if config['kind'] == 'Z-score' and config['threshold'] <= 0:
        raise ValueError('Z-score 기준은 0보다 커야 합니다.')
    if config['operator'] not in ('<=', '>='):
        raise ValueError('비교 연산자를 확인하세요.')
    return config


def calculate(config, observations, price=None):
    config = validate(config)
    if not observations:
        raise ValueError('종가 데이터가 없습니다.')
    boundary = None
    end_boundary = observations[-1]['date']
    if config['kind'] == 'Z-score' and config.get('period_mode') in ('calendar', 'dates', 'since'):
        boundary = (calendar_start(config, date.fromisoformat(end_boundary)).isoformat()
                    if config['period_mode'] == 'calendar' else config['start_date'])
        if config['period_mode'] == 'dates':
            end_boundary = config['end_date']
        if boundary > observations[-1]['date']:
            raise ValueError('선택 날짜가 최신 확정 종가 날짜보다 늦습니다. 날짜를 확인하세요.')
        rows = [row for row in observations if boundary <= row['date'] <= end_boundary]
        needed = 2
    else:
        n = config['period']
        needed = n + 1 if config['kind'] == 'RSI' else n
        rows = observations[-needed:]
    if len(rows) < needed:
        raise ValueError(f'종가가 {needed}개 필요하지만 {len(rows)}개만 있습니다.')
    values = [float(row['close']) for row in rows]
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('유효하지 않은 종가가 있습니다.')
    result = {'observations': rows, 'start': rows[0]['date'], 'end': rows[-1]['date'],
              'last_close': values[-1], 'count': len(rows)}
    if boundary:
        result['requested_start'] = boundary
        result['requested_end'] = end_boundary
    if config['kind'] == 'RSI':
        rsi = rsi_value(values)
        result.update(value=rsi, rsi_history=rsi_history(observations, n), matched=(rsi <= config['threshold'] if config['operator'] == '<='
                                         else rsi >= config['threshold']))
    else:
        price = float(observations[-1]['close']) if price is None else float(price)
        if not math.isfinite(price) or price <= 0:
            raise ValueError('현재 가격이 유효하지 않습니다.')
        mean, std = statistics.mean(values), statistics.pstdev(values)
        z = (price - mean) / std if std > 0 else None
        low, high = mean - config['threshold'] * std, mean + config['threshold'] * std
        result.update(value=z, mean=mean, std=std, price=price, low=low, high=high,
                      matched=(abs(z) <= config['threshold'] if z is not None else None))
    return result
