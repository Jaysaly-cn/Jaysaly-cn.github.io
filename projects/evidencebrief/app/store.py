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
        CREATE TABLE IF NOT EXISTS projects(
          id TEXT PRIMARY KEY,title TEXT NOT NULL,question TEXT NOT NULL,
          entities TEXT NOT NULL,dimensions TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources(
          id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
          entity TEXT NOT NULL,title TEXT NOT NULL,url TEXT NOT NULL,content TEXT NOT NULL,
          method TEXT NOT NULL,sha256 TEXT NOT NULL,raw_sha256 TEXT NOT NULL,
          captured_at TEXT NOT NULL,published_on TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,
          UNIQUE(project_id,entity,url,sha256));
        CREATE TABLE IF NOT EXISTS claims(
          id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
          source_id TEXT NOT NULL REFERENCES sources(id),entity TEXT NOT NULL,dimension TEXT NOT NULL,
          statement TEXT NOT NULL,quote TEXT NOT NULL,quote_start INTEGER NOT NULL,
          state TEXT NOT NULL,origin TEXT NOT NULL,review_note TEXT NOT NULL,
          version INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL REFERENCES projects(id),
          action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reports(
          id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
          snapshot TEXT NOT NULL,markdown TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS extraction_segments(
          source_id TEXT NOT NULL REFERENCES sources(id),plan_version TEXT NOT NULL,segment_index INTEGER NOT NULL,
          start INTEGER NOT NULL,end INTEGER NOT NULL,state TEXT NOT NULL,attempts INTEGER NOT NULL,
          model TEXT NOT NULL,claim_ids TEXT NOT NULL,error TEXT NOT NULL,updated_at TEXT NOT NULL,
          PRIMARY KEY(source_id,plan_version,segment_index));
        CREATE TABLE IF NOT EXISTS claim_versions(
          claim_id TEXT NOT NULL REFERENCES claims(id),version INTEGER NOT NULL,
          snapshot TEXT NOT NULL,action TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL,
          PRIMARY KEY(claim_id,version));
        ''')
