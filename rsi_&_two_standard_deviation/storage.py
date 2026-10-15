import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / 'data' / 'conditions.sqlite3'


@contextmanager
def connect(path=DB_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    try:
        db.row_factory = sqlite3.Row
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS conditions (id INTEGER PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL, snapshot TEXT, updated_at TEXT NOT NULL)')
            yield db
    finally:
        db.close()


def list_records(path=DB_PATH):
    with connect(path) as db:
        return [dict(row) for row in db.execute('SELECT * FROM conditions ORDER BY updated_at DESC, id DESC')]


def save(name, config, snapshot=None, record_id=None, path=DB_PATH):
    name = name.strip()
    if not name:
        raise ValueError('저장 이름을 입력하세요.')
    values = (name, json.dumps(config, ensure_ascii=False),
              json.dumps(snapshot, ensure_ascii=False, allow_nan=False) if snapshot else None,
              datetime.now(timezone.utc).isoformat())
    with connect(path) as db:
        if record_id is None:
            return db.execute('INSERT INTO conditions (name,config,snapshot,updated_at) VALUES (?,?,?,?)', values).lastrowid
        cursor = db.execute('UPDATE conditions SET name=?,config=?,snapshot=?,updated_at=? WHERE id=?', (*values, record_id))
        if cursor.rowcount != 1:
            raise ValueError('저장 항목을 찾을 수 없습니다. 새로 저장하세요.')
        return record_id


def delete(record_id, path=DB_PATH):
    with connect(path) as db:
        db.execute('DELETE FROM conditions WHERE id=?', (record_id,))
