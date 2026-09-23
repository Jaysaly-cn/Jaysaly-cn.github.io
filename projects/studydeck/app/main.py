import asyncio
import json
import os
import sqlite3
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from fsrs import Scheduler, Card, Rating
from . import security, model

ROOT = Path(__file__).resolve().parents[1]
scheduler = Scheduler(enable_fuzzing=False)

def now(): return datetime.now(timezone.utc)

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Material(Strict):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=10, max_length=12000)

class Draft(Strict):
    question: str = Field(min_length=2, max_length=500)
    answer: str = Field(min_length=2, max_length=2000)
    quote: str = Field(min_length=2, max_length=2000)

class Proposals(Strict):
    cards: list[Draft] = Field(min_length=1, max_length=5)

class Approval(Draft):
    version: int = Field(ge=1)
    checked: bool

class Review(Strict):
    version: int = Field(ge=1)
    rating: int = Field(ge=1, le=4)

class Transition(Strict):
    version: int = Field(ge=1)
    action: Literal['pause', 'resume', 'reject', 'restore']

def create_app(path=None):
    path = Path(path or os.getenv('STUDYDECK_DB', str(ROOT/'data/study.sqlite3')))
    @contextmanager
    def db():
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn: yield conn
        finally: conn.close()

    @asynccontextmanager
    async def lifespan(app):
        path.parent.mkdir(parents=True, exist_ok=True)
        with db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS materials(id TEXT PRIMARY KEY,title TEXT,body TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY,material_id TEXT REFERENCES materials(id),
              question TEXT,answer TEXT,quote TEXT,state TEXT,version INTEGER,fsrs TEXT,due TEXT,origin TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,card_id TEXT REFERENCES cards(id),
              action TEXT,snapshot TEXT,created_at TEXT);
            ''')
        yield
    app = FastAPI(title='StudyDeck', version='0.1.0', lifespan=lifespan)
    security.install(app)
    lock = asyncio.Lock()

    def get(c, table, identity):
        row = c.execute(f'SELECT * FROM {table} WHERE id=?', (identity,)).fetchone()
        if row is None: raise HTTPException(404, '记录不存在')
        return dict(row)

    def insert(c, mid, item, origin):
        material = get(c, 'materials', mid)
        if item.quote not in material['body']: raise HTTPException(422, '引用必须逐字来自原文')
        if c.execute('SELECT count(*) FROM cards').fetchone()[0] >= 2000:
            raise HTTPException(409, '当前工作台最多 2000 张卡片')
        identity = uuid4().hex
        c.execute('INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (identity, mid, item.question, item.answer, item.quote, 'draft', 1, None, None, origin))
        event(c, identity, 'created')
        return get(c, 'cards', identity)

    def event(c, identity, action, extra=None):
        snapshot = get(c, 'cards', identity)
        if extra: snapshot.update(extra)
        c.execute('INSERT INTO events(card_id,action,snapshot,created_at) VALUES(?,?,?,?)',
                  (identity, action, json.dumps(snapshot, ensure_ascii=False), now().isoformat()))

    @app.get('/api/status')
    def status(): return {'model_configured': model.configured(), 'scheduler': 'fsrs 6.3.2', 'version': '0.1.0'}

    @app.get('/api/materials')
    def materials():
        with db() as c: return [dict(r) for r in c.execute('SELECT * FROM materials ORDER BY created_at DESC')]

    @app.post('/api/materials', status_code=201)
    def material(item: Material):
        with db() as c:
            if c.execute('SELECT count(*) FROM materials').fetchone()[0] >= 100:
                raise HTTPException(409, '最多保存 100 份资料')
            identity = uuid4().hex
            c.execute('INSERT INTO materials VALUES(?,?,?,?)', (identity,item.title,item.body,now().isoformat()))
            return get(c, 'materials', identity)

    @app.get('/api/cards')
    def cards():
        with db() as c: return [dict(r) for r in c.execute('SELECT * FROM cards ORDER BY rowid DESC')]

    @app.post('/api/materials/{mid}/cards', status_code=201)
    def draft(mid: str, item: Draft):
        with db() as c: return insert(c, mid, item, 'manual')

    @app.post('/api/materials/{mid}/generate', status_code=201)
    async def generate(mid: str):
        if not model.configured(): raise HTTPException(503, '未配置免费模型，可手动制卡')
        if lock.locked(): raise HTTPException(409, '模型正在生成，请稍后重试')
        async with lock:
            with db() as c: source = get(c, 'materials', mid)
            try: proposals = Proposals.model_validate_json(await model.propose(source))
            except Exception as exc:
                raise HTTPException(502, '模型输出未通过校验，请手动制卡或重试') from exc
            with db() as c: return [insert(c, mid, item, 'model') for item in proposals.cards]

    @app.post('/api/cards/{identity}/approve')
    def approve(identity: str, item: Approval):
        if not item.checked: raise HTTPException(422, '请核对答案是否由引用支持')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            card = get(c, 'cards', identity)
            if card['version'] != item.version or card['state'] != 'draft': raise HTTPException(409, '卡片已更新')
            source = get(c, 'materials', card['material_id'])
            if item.quote not in source['body']: raise HTTPException(422, '引用必须逐字来自原文')
            state = Card()
            c.execute('UPDATE cards SET question=?,answer=?,quote=?,state=?,version=version+1,fsrs=?,due=? WHERE id=?',
                      (item.question,item.answer,item.quote,'active',state.to_json(),state.due.isoformat(),identity))
            event(c, identity, 'approved')
            return get(c, 'cards', identity)

    @app.post('/api/cards/{identity}/transition')
    def transition(identity: str, item: Transition):
        transitions = {'pause': ('active','paused'), 'resume': ('paused','active'),
                       'reject': ('draft','rejected'), 'restore': ('rejected','draft')}
        before, after = transitions[item.action]
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            card = get(c, 'cards', identity)
            if card['version'] != item.version or card['state'] != before:
                raise HTTPException(409, '卡片状态已变化，请刷新后重试')
            c.execute('UPDATE cards SET state=?,version=version+1 WHERE id=?', (after, identity))
            event(c, identity, item.action)
            return get(c, 'cards', identity)

    @app.get('/api/due')
    def due():
        with db() as c:
            return [dict(r) for r in c.execute("SELECT * FROM cards WHERE state='active' AND due<=? ORDER BY due", (now().isoformat(),))]

    @app.post('/api/cards/{identity}/review')
    def review(identity: str, item: Review):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            card = get(c, 'cards', identity)
            stamp = now()
            if card['version'] != item.version or card['state'] != 'active': raise HTTPException(409, '卡片已更新或未确认')
            state = Card.from_json(card['fsrs'])
            if state.due > stamp: raise HTTPException(409, '尚未到复习时间')
            updated, log = scheduler.review_card(state, Rating(item.rating), review_datetime=stamp)
            c.execute('UPDATE cards SET version=version+1,fsrs=?,due=? WHERE id=?', (updated.to_json(),updated.due.isoformat(),identity))
            event(c, identity, 'reviewed', {'review_log':json.loads(log.to_json()), 'scheduler':json.loads(scheduler.to_json())})
            return get(c, 'cards', identity)

    @app.get('/api/export')
    def export():
        with db() as c:
            return {'format':'studydeck-1','exported_at':now().isoformat(),
                    **{table:[dict(r) for r in c.execute(f'SELECT * FROM {table}')] for table in ('materials','cards','events')}}

    app.mount('/', StaticFiles(directory=ROOT/'web', html=True), name='web')
    return app

app = create_app()
