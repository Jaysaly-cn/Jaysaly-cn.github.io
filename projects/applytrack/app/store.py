import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


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
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,company TEXT NOT NULL,title TEXT NOT NULL,
          jd TEXT NOT NULL,sha256 TEXT NOT NULL,source_url TEXT NOT NULL,stage TEXT NOT NULL DEFAULT 'saved',
          version INTEGER NOT NULL DEFAULT 1,follow_up TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requirements(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),
          label TEXT NOT NULL,quote TEXT NOT NULL,start INTEGER NOT NULL,kind TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft',version INTEGER NOT NULL DEFAULT 1,note TEXT NOT NULL DEFAULT '',
          origin TEXT NOT NULL,UNIQUE(job_id,quote,label));
        CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,title TEXT NOT NULL,body TEXT NOT NULL,
          url TEXT NOT NULL,sha256 TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mappings(id TEXT PRIMARY KEY,requirement_id TEXT NOT NULL REFERENCES requirements(id),
          evidence_id TEXT NOT NULL REFERENCES evidence(id),quote TEXT NOT NULL,start INTEGER NOT NULL,
          rationale TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(requirement_id,evidence_id));
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL REFERENCES jobs(id),
          kind TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS packets(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),
          body TEXT NOT NULL,sha256 TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),
          state TEXT NOT NULL,trace TEXT NOT NULL,created_at TEXT NOT NULL);
        ''')
