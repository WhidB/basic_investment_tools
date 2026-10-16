"""Persistent notification rules and Windows sign-in integration."""
import json
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from native_core import prepare, evaluate, MODES
from market_data import fetch

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'alerts.sqlite3'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'InvestmentToolsCloseAlerts'

@contextmanager
def database(path=DB):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS rules (id INTEGER PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL UNIQUE, updated TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, checked TEXT NOT NULL, report TEXT NOT NULL)')
            yield db
    finally:
        db.close()

def canonical(config):
    c = dict(config)
    c['symbol'] = c['symbol'].strip().upper()
    mode = c.get('alert_connection', 'internet')
    if mode not in ('internet', 'vpn'):
        raise ValueError('알림 연결 방식은 인터넷 또는 VPN이어야 합니다.')
    # Preserve legacy internet JSON and its uniqueness; allow the same condition in both modes.
    if mode == 'internet':
        c.pop('alert_connection', None)
    prepare(c)
    return json.dumps(c, ensure_ascii=False, sort_keys=True, allow_nan=False)

def rules(path=DB):
    with database(path) as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM rules ORDER BY id')]
    for r in rows:
        r['config'] = json.loads(r['config'])
    return rows

def put_rule(name, config, rule_id=None, path=DB):
    content = canonical(config)
    name = name.strip() or config['symbol'] + ' ' + config['kind']
    now = datetime.now(timezone.utc).isoformat()
    with database(path) as db:
        duplicate = db.execute('SELECT id FROM rules WHERE config=?', (content,)).fetchone()
        if rule_id is not None:
            if duplicate and duplicate['id'] != rule_id:
                raise ValueError('같은 조건의 알림이 이미 등록되어 있습니다.')
            result = db.execute('UPDATE rules SET name=?, config=?, updated=? WHERE id=?', (name,content,now,rule_id))
            if result.rowcount != 1:
                raise ValueError('수정 대상 알림이 삭제되었습니다. 다시 목록을 확인하세요.')
            return rule_id
        if duplicate:
            db.execute('UPDATE rules SET name=?, updated=? WHERE id=?', (name,now,duplicate['id']))
            return duplicate['id']
        return db.execute('INSERT INTO rules(name,config,updated) VALUES(?,?,?)', (name,content,now)).lastrowid

def drop_rule(rule_id, path=DB):
    with database(path) as db:
        db.execute('DELETE FROM rules WHERE id=?', (rule_id,))

def save_report(report, path=DB):
    with database(path) as db:
        db.execute('INSERT INTO reports(checked,report) VALUES(?,?)', (datetime.now(timezone.utc).isoformat(),report))
        db.execute('DELETE FROM reports WHERE id NOT IN (SELECT id FROM reports ORDER BY id DESC LIMIT 30)')

def last_report(path=DB):
    with database(path) as db:
        row = db.execute('SELECT report FROM reports ORDER BY id DESC LIMIT 1').fetchone()
        return row['report'] if row else '아직 알림 조회 기록이 없습니다.'

def startup_command():
    python = Path(sys.executable).with_name('pythonw.exe')
    script = ROOT / 'startup_notify.py'
    if not python.exists() or not script.exists():
        raise ValueError('알림 실행 파일을 찾을 수 없습니다. 설치 경로를 확인하세요.')
    command = subprocess.list2cmdline([str(python),str(script),'--startup'])
    if len(command) > 260:
        raise ValueError('설치 경로가 너무 깁니다. 더 짧은 경로로 옮긴 후 등록하세요.')
    return command

def set_startup(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key,RUN_NAME,0,winreg.REG_SZ,startup_command())
        else:
            try:
                winreg.DeleteValue(key,RUN_NAME)
            except FileNotFoundError:
                pass

def startup_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key,RUN_NAME)[0] == startup_command()
    except (FileNotFoundError, ValueError):
        return False

def register(name, config, rule_id=None):
    canonical(config)
    previous = startup_enabled()
    set_startup(True)
    try:
        return put_rule(name,config,rule_id)
    except Exception:
        if not previous:
            set_startup(False)
        raise

def unregister(rule_id):
    drop_rule(rule_id)
    if not rules():
        set_startup(False)

def launch_now():
    command = [str(Path(sys.executable).with_name('pythonw.exe')), str(ROOT/'startup_notify.py'), '--once']
    subprocess.Popen(command, cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)

def rule_label(rule):
    c = rule['config']
    connection = 'VPN' if c.get('alert_connection') == 'vpn' else '인터넷'
    if c['kind'] == 'RSI':
        return f"{connection} · {c['symbol']} · RSI {c['period']}"
    mode = c['period_mode']
    if mode == 'calendar':
        span = f"{c['years']}년 {c['months']}개월 {c['days']}일 전"
    elif mode == 'trading':
        span = f"거래일 {c['trade_years']}년 {c['trade_months']}개월 {c['trade_days']}일 전"
    elif mode == 'dates':
        span = f"{c['start_date']} ~ {c['end_date']}"
    elif mode == 'since':
        span = f"{c['start_date']} ~ 최신 종가"
    elif mode == 'exclude':
        span = f"전체 (제외 {c['exclude_start']} ~ {c['exclude_end']})"
    else:
        span = MODES[mode]
    return f"{connection} · {c['symbol']} · ±{c['threshold']:g}σ · {span}"

def format_alert(snapshot):
    c, r, quote = snapshot['config'], snapshot['result'], snapshot['quote']
    used = f"사용 종가: {r['start']} ~ {r['end']} / {r['count']}개"
    if c['kind'] == 'RSI':
        return '\n'.join([
            f"[{c['symbol']} · RSI {c['period']}]",
            f"현재 RSI: {r['value']:.2f}",
            used,
            f"최근 확정 종가: ${quote['price']:,.2f} ({quote['time']})",
        ])
    delta = r['price'] - r['mean']
    if delta == 0:
        comparison = '평균과 같습니다'
    else:
        comparison = f"평균보다 {abs(delta):,.2f}달러 ({abs(delta/r['mean']*100):.2f}%) {'높습니다' if delta > 0 else '낮습니다'}"
    if r['value'] is None:
        position = '계산 불가'
        interpretation = '표준편차가 0이므로 범위 판정 불가'
    else:
        position = f"Z-score {r['value']:+.3f}"
        interpretation = f"{c['threshold']:g}표준편차 {'내' if r['matched'] else '외'}에 있습니다"
    return '\n'.join([
        f"[{c['symbol']} · ±{c['threshold']:g}σ]",
        f"현재 위치: {position}",
        f"해석: {interpretation} · {comparison}",
        used,
        f"최신 확정 종가: ${quote['price']:,.2f} ({quote['time']})",
        f"평균: ${r['mean']:,.2f} · 표준편차: ${r['std']:,.4f}",
        f"범위: ${r['low']:,.2f} ~ ${r['high']:,.2f}",
    ])

def check_rule(rule):
    c = rule['config']
    market = fetch(prepare(c))
    if market['stale']:
        raise ValueError(f"최근 마감일 {market['expected_date']} 종가가 아직 제공되지 않았습니다.")
    latest = market['observations'][-1]
    # Alert comparisons must use the latest completed close, never a live quote.
    market = dict(market, quote=dict(price=latest['close'], time=latest['date'], source='최신 확정 종가'))
    snapshot = evaluate(c, market)
    return format_alert(snapshot)

def collect_cycle(current, completed, checker=check_rule):
    """Return completed results and failures; retry only unchanged unsuccessful rules."""
    successes, failures = {}, {}
    for rule in current:
        key = (rule['id'], json.dumps(rule['config'],sort_keys=True))
        if key in completed:
            successes[key] = completed[key]
            continue
        try:
            successes[key] = checker(rule)
        except Exception as exc:
            failures[key] = f"[{rule_label(rule)}]\n조회 대기: {exc}"
    return successes, failures

