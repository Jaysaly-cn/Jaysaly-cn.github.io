import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from . import collect, model, report, security
from .store import connect, initialize, now

ROOT = Path(__file__).resolve().parents[1]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Project(Strict):
    title: Name
    question: Short
    entities: list[Name] = Field(min_length=1, max_length=8)
    dimensions: list[Name] = Field(min_length=1, max_length=12)

    @field_validator('entities', 'dimensions')
    @classmethod
    def unique(cls, value):
        if len({v.casefold() for v in value}) != len(value):
            raise ValueError('对象和维度不可重复')
        return value


class Source(Strict):
    entity: Name
    title: Name
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=100000)]
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ''
    published_on: date | None = None

    @field_validator('published_on')
    @classmethod
    def not_future(cls, value):
        if value and value > date.today():
            raise ValueError('发布日期不能晚于今天')
        return value


class Fetch(Strict):
    entity: Name
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]


class Claim(Strict):
    source_id: Name
    dimension: Name
    statement: Short
    quote: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=4000)]


class Review(Strict):
    version: int = Field(ge=1)
    state: Literal['draft', 'approved', 'rejected']
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class Archive(Strict):
    archived: bool


def create_app(db_path=None):
    path = db_path or os.getenv('EVIDENCEBRIEF_DB', str(ROOT / 'data/evidencebrief.sqlite3'))

    @asynccontextmanager
    async def lifespan(app):
        initialize(path)
        yield

    app = FastAPI(title='EvidenceBrief', version='0.1.0', lifespan=lifespan)
    security.install(app)
    slots = asyncio.Semaphore(2)

    def project_row(db, identity):
        row = db.execute('SELECT * FROM projects WHERE id=?', (identity,)).fetchone()
        if not row:
            raise HTTPException(404, '研究项目不存在')
        result = dict(row)
        result['entities'], result['dimensions'] = json.loads(row['entities']), json.loads(row['dimensions'])
        return result

    def source_row(db, project_id, identity):
        row = db.execute('SELECT * FROM sources WHERE id=? AND project_id=?', (identity, project_id)).fetchone()
        if not row:
            raise HTTPException(404, '此项目内不存在该来源')
        return dict(row)

    def event(db, pid, action, detail):
        db.execute('INSERT INTO events(project_id,action,detail,created_at) VALUES (?,?,?,?)', (pid, action, detail, now()))

    def save_source(pid, body, method, raw_sha=''):
        content_hash = hashlib.sha256(body.content.encode()).hexdigest()
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            p = project_row(db, pid)
            if body.entity not in p['entities']:
                raise HTTPException(422, '来源对象不属于此研究项目')
            duplicate = db.execute('SELECT * FROM sources WHERE project_id=? AND entity=? AND url=? AND sha256=?',
                                   (pid, body.entity, body.url, content_hash)).fetchone()
            if duplicate:
                return {**dict(duplicate), 'deduplicated': True}
            if db.execute('SELECT count(*) FROM sources WHERE project_id=?', (pid,)).fetchone()[0] >= 30:
                raise HTTPException(409, '单个研究项目最多 30 份来源快照')
            identity = uuid4().hex
            db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,0)',
                       (identity, pid, body.entity, body.title, body.url, body.content, method, content_hash,
                        raw_sha, now(), str(body.published_on) if body.published_on else ''))
            event(db, pid, 'source_added', f'{body.entity}：{body.title} ({method})')
            return source_row(db, pid, identity)

    def add_claim(db, pid, body, origin='human'):
        p = project_row(db, pid)
        source = source_row(db, pid, body.source_id)
        if source['archived']:
            raise HTTPException(409, '已归档来源不能新增结论')
        if body.dimension not in p['dimensions']:
            raise HTTPException(422, '比较维度不属于此研究项目')
        position = source['content'].find(body.quote)
        if position < 0:
            raise HTTPException(422, '引用必须是此来源中的连续原文，不可改写')
        existing = db.execute('SELECT * FROM claims WHERE project_id=? AND source_id=? AND dimension=? AND statement=? AND quote=?',
                              (pid, body.source_id, body.dimension, body.statement, body.quote)).fetchone()
        if existing:
            return {**dict(existing), 'deduplicated': True}
        if db.execute('SELECT count(*) FROM claims WHERE project_id=?', (pid,)).fetchone()[0] >= 200:
            raise HTTPException(409, '单个项目最多 200 条结论')
        identity, stamp = uuid4().hex, now()
        db.execute('INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (identity, pid, body.source_id, source['entity'], body.dimension, body.statement, body.quote,
                    position, 'draft', origin, '', 1, stamp, stamp))
        event(db, pid, 'claim_added', f'{source["entity"]} / {body.dimension}：{body.statement}，待人工确认')
        return dict(db.execute('SELECT * FROM claims WHERE id=?', (identity,)).fetchone())

    def snapshot(db, pid):
        p = project_row(db, pid)
        sources = [dict(r) for r in db.execute('SELECT * FROM sources WHERE project_id=? ORDER BY captured_at', (pid,))]
        claims = [dict(r) for r in db.execute('SELECT * FROM claims WHERE project_id=? ORDER BY created_at', (pid,))]
        return report.build(p, sources, claims)

    @app.get('/api/health')
    def health():
        with connect(path) as db:
            db.execute('SELECT 1')
        return {'status': 'ok', 'version': '0.1.0', 'model_configured': model.configured(),
                'model_input_character_limit': model.input_limit()}

    @app.get('/api/projects')
    def projects():
        with connect(path) as db:
            return [project_row(db, r[0]) for r in db.execute('SELECT id FROM projects ORDER BY created_at DESC').fetchall()]

    @app.post('/api/projects', status_code=201)
    def create_project(body: Project):
        identity = uuid4().hex
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM projects').fetchone()[0] >= 50:
                raise HTTPException(409, '工作台最多 50 个研究项目')
            db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)', (identity, body.title, body.question,
                       json.dumps(body.entities, ensure_ascii=False), json.dumps(body.dimensions, ensure_ascii=False), now()))
            return project_row(db, identity)

    @app.get('/api/projects/{pid}')
    def detail(pid: str):
        with connect(path) as db:
            db.execute('BEGIN')
            result = snapshot(db, pid)
            result['claims'] = [dict(r) for r in db.execute('SELECT * FROM claims WHERE project_id=? ORDER BY created_at DESC', (pid,))]
            result['reports'] = [dict(r) for r in db.execute('SELECT id,created_at FROM reports WHERE project_id=? ORDER BY created_at DESC', (pid,))]
            result['events'] = [dict(r) for r in db.execute('SELECT * FROM events WHERE project_id=? ORDER BY id DESC LIMIT 50', (pid,))]
            return result

    @app.post('/api/projects/{pid}/sources', status_code=201)
    def paste_source(pid: str, body: Source):
        return save_source(pid, body, 'paste')

    @app.post('/api/projects/{pid}/fetch', status_code=201)
    def fetch_source(pid: str, body: Fetch):
        with connect(path) as db:
            p = project_row(db, pid)
            if body.entity not in p['entities']:
                raise HTTPException(422, '来源对象不属于此研究项目')
        try:
            result = collect.collect(body.url)
            source = Source(entity=body.entity, title=result['title'][:120], content=result['content'], url=result['url'])
        except (collect.CollectionError, ValueError) as exc:
            with connect(path) as db:
                event(db, pid, 'collection_failed', '采集未完成，可改用粘贴材料。' + type(exc).__name__)
            raise HTTPException(422, str(exc) if isinstance(exc, collect.CollectionError) else '来源内容未通过长度校验')
        return save_source(pid, source, 'https', result['raw_sha256'])

    @app.patch('/api/projects/{pid}/sources/{sid}')
    def archive_source(pid: str, sid: str, body: Archive):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            source = source_row(db, pid, sid)
            db.execute('UPDATE sources SET archived=? WHERE id=?', (body.archived, sid))
            event(db, pid, 'source_archived' if body.archived else 'source_restored', source['title'])
        return {'archived': body.archived, 'note': '新报告立即采用当前范围；已生成的报告保留当时快照'}

    @app.post('/api/projects/{pid}/claims', status_code=201)
    def create_claim(pid: str, body: Claim):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            return add_claim(db, pid, body)

    @app.patch('/api/projects/{pid}/claims/{cid}')
    def review_claim(pid: str, cid: str, body: Review):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM claims WHERE id=? AND project_id=?', (cid, pid)).fetchone()
            if not row:
                raise HTTPException(404, '此项目内不存在该结论')
            if row['version'] != body.version:
                raise HTTPException(409, '结论已被其他操作更新，请刷新')
            source = source_row(db, pid, row['source_id'])
            if body.state == 'approved' and source['archived']:
                raise HTTPException(409, '已归档来源不能批准结论')
            db.execute('UPDATE claims SET state=?,review_note=?,version=version+1,updated_at=? WHERE id=?',
                       (body.state, body.note, now(), cid))
            label = {'draft': '待确认', 'approved': '已确认', 'rejected': '已退回'}[body.state]
            event(db, pid, 'claim_reviewed', f'{row["statement"]} → {label}；{body.note}')
            return dict(db.execute('SELECT * FROM claims WHERE id=?', (cid,)).fetchone())

    @app.post('/api/projects/{pid}/sources/{sid}/suggest', status_code=201)
    async def suggestions(pid: str, sid: str):
        if not model.configured():
            raise HTTPException(409, '未配置免费/本地模型；可手工关联原文并继续研究')
        with connect(path) as db:
            p = project_row(db, pid)
            source = source_row(db, pid, sid)
            if source['archived']:
                raise HTTPException(409, '已归档来源不能抽取建议')
        try:
            async with slots:
                proposed = await model.suggest(source, p['dimensions'])
            bodies = [Claim(source_id=sid, **item) for item in proposed]
            with connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                results = [add_claim(db, pid, body, 'model') for body in bodies]
                processed = min(len(source['content']), model.input_limit())
                event(db, pid, 'model_suggested', f'{len(results)} 条候选；处理来源前 {processed} 字符；均需人工审核')
            return {'claims': results, 'model': os.environ['EB_MODEL'], 'scope': f'first {processed} characters',
                    'processed_characters': processed, 'total_characters': len(source['content']),
                    'truncated': processed < len(source['content'])}
        except Exception as exc:
            with connect(path) as db:
                event(db, pid, 'model_failed', type(exc).__name__)
            raise HTTPException(502, '模型建议未通过验证或调用失败；没有保存半成品，请继续手工研究')

    @app.post('/api/projects/{pid}/reports', status_code=201)
    def create_report(pid: str):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            data = snapshot(db, pid)
            if db.execute('SELECT count(*) FROM reports WHERE project_id=?', (pid,)).fetchone()[0] >= 50:
                raise HTTPException(409, '每个项目最多保留 50 个报告快照')
            identity, stamp = uuid4().hex, now()
            data['generated_at'] = stamp
            content = report.markdown(data)
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?)', (identity, pid, json.dumps(data, ensure_ascii=False), content, stamp))
            event(db, pid, 'report_created', f'已冻结研究报告；{len(data["gaps"])} 个待补项、{len(data["differences"])} 个不同表述待复核项')
            return {'id': identity, 'created_at': stamp, 'markdown': content, 'snapshot': data}

    @app.get('/api/projects/{pid}/reports/{rid}')
    def get_report(pid: str, rid: str, format: Literal['json', 'markdown'] = 'json'):
        with connect(path) as db:
            row = db.execute('SELECT * FROM reports WHERE id=? AND project_id=?', (rid, pid)).fetchone()
            if not row:
                raise HTTPException(404, '报告不存在')
            if format == 'markdown':
                return Response(row['markdown'], media_type='text/markdown', headers={'Content-Disposition': f'attachment; filename="evidencebrief-{rid}.md"'})
            return {**dict(row), 'snapshot': json.loads(row['snapshot'])}

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'web/index.html')

    app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')
    return app


app = create_app()
