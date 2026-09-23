import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(path):
    path = path() if callable(path) else path
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
        CREATE TABLE IF NOT EXISTS meetings(id TEXT PRIMARY KEY,title TEXT NOT NULL,meeting_date TEXT NOT NULL,
          attendees TEXT NOT NULL,transcript TEXT NOT NULL,sha256 TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY,meeting_id TEXT NOT NULL REFERENCES meetings(id),
          title TEXT NOT NULL,quote TEXT NOT NULL,quote_start INTEGER NOT NULL,
          proposed_owner TEXT NOT NULL,proposed_due TEXT NOT NULL,due_phrase TEXT NOT NULL,
          owner TEXT NOT NULL DEFAULT '',due_date TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'draft',
          origin TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,review_note TEXT NOT NULL DEFAULT '',
          completion_note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
          UNIQUE(meeting_id,quote,title));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,meeting_id TEXT NOT NULL,
          action_id TEXT NOT NULL,event TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,meeting_id TEXT NOT NULL,state TEXT NOT NULL,
          trace TEXT NOT NULL,created_at TEXT NOT NULL);
        ''')
