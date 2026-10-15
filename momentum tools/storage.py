import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent / 'data'

def connection():
    ROOT.mkdir(exist_ok=True)
    db = sqlite3.connect(ROOT / 'momentum.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, name TEXT, payload TEXT, updated TEXT)')
    return db

def save(name, payload, record_id=None):
    record_id = record_id or str(uuid.uuid4())
    with connection() as db:
        db.execute('INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?)', (record_id, name, json.dumps(payload, ensure_ascii=False, allow_nan=False), datetime.now(timezone.utc).isoformat()))
    return record_id

def list_records():
    with connection() as db:
        rows = db.execute('SELECT id,name,payload,updated FROM records ORDER BY updated DESC').fetchall()
    return [dict(id=i,name=n,payload=json.loads(p),updated=u) for i,n,p,u in rows]

def delete(record_id):
    with connection() as db: db.execute('DELETE FROM records WHERE id=?', (record_id,))

def get_language():
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)')
        row = db.execute('SELECT value FROM preferences WHERE key=?', ('language',)).fetchone()
    return row[0] if row and row[0] in ('ko','en') else 'ko'

def set_language(language):
    if language not in ('ko','en'): raise ValueError('Unsupported language')
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)')
        db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)', ('language',language))
