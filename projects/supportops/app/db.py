import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path: str):
    with connect(path) as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
          source TEXT NOT NULL, audience TEXT NOT NULL,
          version INTEGER NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, question TEXT NOT NULL, audience TEXT NOT NULL,
          answer TEXT NOT NULL, mode TEXT NOT NULL, citations TEXT NOT NULL,
          trace TEXT NOT NULL, elapsed_ms INTEGER NOT NULL,
          usage TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback (
          run_id TEXT PRIMARY KEY REFERENCES runs(id), rating TEXT NOT NULL,
          note TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tickets (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
          title TEXT NOT NULL, category TEXT NOT NULL, priority TEXT NOT NULL,
          status TEXT NOT NULL, assignee TEXT NOT NULL, resolution TEXT NOT NULL,
          version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ticket_id TEXT NOT NULL REFERENCES tickets(id),
          event TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS knowledge_publications (
          id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
          ticket_version INTEGER NOT NULL, document_id TEXT NOT NULL,
          snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(ticket_id,ticket_version));
        CREATE TABLE IF NOT EXISTS rechecks (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
          snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
          verdict TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', reviewed_at TEXT NOT NULL DEFAULT '');
        ''')


def rowdict(row, json_fields=()):
    if row is None:
        return None
    result = dict(row)
    for field in json_fields:
        result[field] = json.loads(result[field])
    return result
