import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from .ingest import parse


@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    with connect(path) as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS messages(
          id TEXT PRIMARY KEY,sha256 TEXT NOT NULL UNIQUE,message_id TEXT NOT NULL,
          metadata TEXT NOT NULL,raw BLOB NOT NULL,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS messages_message_id ON messages(message_id);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,message_id TEXT NOT NULL REFERENCES messages(id),
          title TEXT NOT NULL,quote TEXT NOT NULL,quote_start INTEGER NOT NULL,body_sha256 TEXT NOT NULL,
          owner TEXT NOT NULL DEFAULT '',due_date TEXT,state TEXT NOT NULL DEFAULT 'draft',
          version INTEGER NOT NULL DEFAULT 1,origin TEXT NOT NULL DEFAULT 'manual',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS task_events(id INTEGER PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id),
          action TEXT NOT NULL,note TEXT NOT NULL,snapshot TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY,snapshot TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS model_runs(id TEXT PRIMARY KEY,message_id TEXT NOT NULL REFERENCES messages(id),
          model TEXT NOT NULL,raw TEXT NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL,created_at TEXT NOT NULL);
        ''')
        columns={r['name'] for r in db.execute('PRAGMA table_info(tasks)')}
        for name in ('proposed_owner','proposed_due'):
            if name not in columns:
                db.execute(f"ALTER TABLE tasks ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")


def import_message(path, raw):
    metadata = parse(raw)
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute('SELECT id FROM messages WHERE sha256=?', (metadata['sha256'],)).fetchone()
        if previous:
            return {'id': previous['id'], 'duplicate': True, 'message_id_conflicts': conflicts(db, metadata)}
        if db.execute('SELECT count(*) FROM messages').fetchone()[0] >= 500:
            raise ValueError('本地收件箱最多保存 500 封邮件')
        identity = uuid4().hex
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',
                   (identity, metadata['sha256'], metadata['message_id'], json.dumps(metadata, ensure_ascii=False),
                    raw, datetime.now(timezone.utc).isoformat()))
        return {'id': identity, 'duplicate': False, 'message_id_conflicts': conflicts(db, metadata)}


def conflicts(db, metadata):
    if not metadata['message_id']:
        return []
    return [r['id'] for r in db.execute('SELECT id FROM messages WHERE message_id=? AND sha256<>?',
                                      (metadata['message_id'], metadata['sha256']))]


def messages(path):
    with connect(path) as db:
        return [{'id': r['id'], 'subject': json.loads(r['metadata'])['subject'], 'created_at': r['created_at']}
                for r in db.execute('SELECT id,metadata,created_at FROM messages ORDER BY created_at DESC')]


def message(path, identity):
    with connect(path) as db:
        row = db.execute('SELECT metadata FROM messages WHERE id=?', (identity,)).fetchone()
        if not row:
            raise KeyError('邮件不存在')
        metadata = json.loads(row['metadata'])
        return {'id': identity, **metadata, 'message_id_conflicts': conflicts(db, metadata)}
