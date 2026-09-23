import asyncio
import hashlib
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from urllib.parse import urlsplit
from . import model, security
from .store import connect, initialize, now

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)]
Quote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=2000)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
Kind = Literal['responsibility', 'required', 'preferred']
Stage = Literal['saved', 'applied', 'screening', 'interview', 'offer', 'rejected', 'withdrawn', 'accepted']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Source(Strict):
    source_url: str = Field(default='', max_length=2000)

    @field_validator('source_url')
    @classmethod
    def safe_url(cls, value):
        if value:
            u = urlsplit(value)
            if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
                raise ValueError('来源须为 HTTP(S) 链接')
        return value


class Job(Source):
    company: Text
    title: Text
    jd: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=80000)]


class Requirement(Strict):
    label: Text
    quote: Quote
    kind: Kind


class Review(Strict):
    version: int = Field(ge=1)
    decision: Literal['approved', 'rejected']
    label: Text
    kind: Kind
    note: Note


class Evidence(Source):
    title: Text
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=20000)]


class Mapping(Strict):
    evidence_id: str
    quote: Quote
    rationale: Note


class Transition(Strict):
    version: int = Field(ge=1)
    stage: Stage
    note: Note
    packet_id: str = ''


class FollowUp(Strict):
    version: int = Field(ge=1)
    due: date | None = None
    note: Note


class Correction(Strict):
    version: int = Field(ge=1)
    note: Note


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def locate(text, quote):
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        raise HTTPException(422, '引用必须是唯一的连续原文，请扩展上下文')
    return start


def get(db, table, identifier):
    # Table names are internal constants, never request values.
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (identifier,)).fetchone()
    if row is None:
        raise HTTPException(404, '记录不存在')
    return dict(row)


def event(db, job_id, kind, detail):
    db.execute('INSERT INTO events(job_id,kind,detail,created_at) VALUES(?,?,?,?)',
               (job_id, kind, json.dumps(detail, ensure_ascii=False), now()))


def check_version(row, version):
    if row['version'] != version:
        raise HTTPException(409, '记录已更新，请刷新后重试')


def create_app(path=None):
    path = path or os.getenv('APPLYTRACK_DB', str(Path(__file__).resolve().parents[1] / 'data/applytrack.db'))
    @asynccontextmanager
    async def lifespan(app):
        initialize(path)
        yield
    app = FastAPI(title='ApplyTrack · 求职证据工作台', lifespan=lifespan)
    security.install(app)
    lock = asyncio.Lock()  # ponytail: single-process model queue; distributed workers need durable jobs.

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': '记录重复或关联不存在'}, status_code=409)

    @app.get('/api/health')
    def health():
        return {'ok': True, 'model_configured': model.configured(), 'model_input_limit': 4000}

    @app.post('/api/jobs', status_code=201)
    def add_job(data: Job):
        with connect(path) as db:
            if db.execute('SELECT count(*) FROM jobs').fetchone()[0] >= 300:
                raise HTTPException(409, '个人工作台最多300个岗位')
            identifier = str(uuid4())
            db.execute('INSERT INTO jobs(id,company,title,jd,sha256,source_url,created_at) VALUES(?,?,?,?,?,?,?)',
                       (identifier, data.company, data.title, data.jd, digest(data.jd), data.source_url, now()))
            event(db, identifier, 'created', {'sha256': digest(data.jd)})
            return get(db, 'jobs', identifier)

    @app.get('/api/jobs')
    def list_jobs(stage: Stage | None = None, overdue: bool = False):
        with connect(path) as db:
            rows = [dict(r) for r in db.execute('SELECT id,company,title,stage,version,follow_up,created_at FROM jobs ORDER BY created_at DESC')]
        return [r for r in rows if (not stage or r['stage'] == stage) and
                (not overdue or (r['follow_up'] and r['follow_up'] < date.today().isoformat() and r['stage'] not in ('accepted','withdrawn','rejected')))]

    def detail(db, jid):
        job = get(db, 'jobs', jid)
        job['requirements'] = [dict(r) for r in db.execute('SELECT * FROM requirements WHERE job_id=? ORDER BY rowid', (jid,))]
        for requirement in job['requirements']:
            requirement['evidence'] = [dict(r) for r in db.execute('''SELECT m.*,e.title,e.url,e.sha256,e.body FROM mappings m
                JOIN evidence e ON e.id=m.evidence_id WHERE m.requirement_id=? ORDER BY m.created_at''', (requirement['id'],))]
        approved = [r for r in job['requirements'] if r['status'] == 'approved']
        job['coverage'] = {'approved_requirements': len(approved), 'linked_requirements': sum(bool(r['evidence']) for r in approved),
                           'gaps': [r['id'] for r in approved if not r['evidence']], 'meaning': '人工关联覆盖，非胜任度或录用概率'}
        return job

    @app.get('/api/jobs/{jid}')
    def job_detail(jid: str):
        with connect(path) as db:
            result = detail(db, jid)
            for table in ('events', 'packets', 'runs'):
                columns = 'id,sha256,created_at' if table == 'packets' else '*'
                result[table] = [dict(r) for r in db.execute(f'SELECT {columns} FROM {table} WHERE job_id=? ORDER BY rowid', (jid,))]
            return result

    def insert_requirement(db, jid, data, origin, jd):
        if db.execute('SELECT count(*) FROM requirements WHERE job_id=?', (jid,)).fetchone()[0] >= 80:
            raise HTTPException(409, '每个岗位最多80条要求')
        start = locate(jd, data.quote)
        identifier = str(uuid4())
        db.execute('INSERT INTO requirements(id,job_id,label,quote,start,kind,origin) VALUES(?,?,?,?,?,?,?)',
                   (identifier, jid, data.label, data.quote, start, data.kind, origin))
        event(db, jid, 'requirement_added', {'id': identifier, 'origin': origin})
        return get(db, 'requirements', identifier)

    @app.post('/api/jobs/{jid}/requirements', status_code=201)
    def add_requirement(jid: str, data: Requirement):
        with connect(path) as db:
            job = get(db, 'jobs', jid)
            return insert_requirement(db, jid, data, 'manual', job['jd'])

    @app.post('/api/jobs/{jid}/extract')
    async def extract(jid: str):
        if not model.configured():
            raise HTTPException(503, '未配置免费模型；可手工录入要求')
        if lock.locked():
            raise HTTPException(409, '模型正在处理，请稍后重试')
        with connect(path) as db:
            job = get(db, 'jobs', jid)
        async with lock:
            run_id = str(uuid4())
            trace = {'input_chars': min(len(job['jd']), 4000), 'truncated': len(job['jd']) > 4000}
            try:
                raw = await model.extract(job['jd'])
                trace['output'] = raw
                candidates = [Requirement.model_validate(r) for r in raw]
                with connect(path) as db:
                    created = [insert_requirement(db, jid, r, 'model', job['jd'][:4000]) for r in candidates]
                    db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', (run_id, jid, 'success', json.dumps(trace, ensure_ascii=False), now()))
                return {'requirements': created, **trace}
            except Exception as exc:
                trace['error_type'] = type(exc).__name__
                with connect(path) as db:
                    db.execute('INSERT INTO runs VALUES(?,?,?,?,?)', (run_id, jid, 'failed', json.dumps(trace, ensure_ascii=False), now()))
                raise HTTPException(422, '模型提取未通过校验，未保存部分结果；详见运行记录') from exc

    @app.post('/api/requirements/{rid}/review')
    def review(rid: str, data: Review):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = get(db, 'requirements', rid)
            check_version(row, data.version)
            if row['status'] != 'draft':
                raise HTTPException(409, '要求已经审核')
            db.execute('UPDATE requirements SET status=?,label=?,kind=?,note=?,version=version+1 WHERE id=?',
                       (data.decision, data.label, data.kind, data.note, rid))
            event(db, row['job_id'], 'requirement_reviewed', {'id': rid, **data.model_dump()})
            return get(db, 'requirements', rid)

    @app.post('/api/evidence', status_code=201)
    def add_evidence(data: Evidence):
        with connect(path) as db:
            if db.execute('SELECT count(*) FROM evidence').fetchone()[0] >= 500:
                raise HTTPException(409, '证据库最多500条')
            identifier = str(uuid4())
            db.execute('INSERT INTO evidence VALUES(?,?,?,?,?,?)', (identifier, data.title, data.body, data.source_url, digest(data.body), now()))
            return get(db, 'evidence', identifier)

    @app.post('/api/requirements/{rid}/withdraw')
    def withdraw(rid: str, data: Correction):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = get(db, 'requirements', rid)
            check_version(row, data.version)
            if row['status'] != 'approved':
                raise HTTPException(409, '只能撤回已审核要求')
            db.execute("UPDATE requirements SET status='withdrawn',version=version+1 WHERE id=?", (rid,))
            event(db, row['job_id'], 'requirement_withdrawn', {'id': rid, **data.model_dump()})
            return get(db, 'requirements', rid)

    @app.get('/api/evidence')
    def list_evidence():
        with connect(path) as db:
            return [dict(r) for r in db.execute('SELECT * FROM evidence ORDER BY created_at DESC')]

    @app.post('/api/requirements/{rid}/evidence', status_code=201)
    def link(rid: str, data: Mapping):
        with connect(path) as db:
            row = get(db, 'requirements', rid)
            if row['status'] != 'approved':
                raise HTTPException(409, '先审核岗位要求')
            evidence = get(db, 'evidence', data.evidence_id)
            start = locate(evidence['body'], data.quote)
            identifier = str(uuid4())
            db.execute('INSERT INTO mappings VALUES(?,?,?,?,?,?,?)', (identifier, rid, data.evidence_id, data.quote, start, data.rationale, now()))
            event(db, row['job_id'], 'evidence_linked', {'id': identifier, **data.model_dump()})
            return get(db, 'mappings', identifier)

    @app.post('/api/jobs/{jid}/packets', status_code=201)
    def packet(jid: str):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            job = detail(db, jid)
            job['requirements'] = [r for r in job['requirements'] if r['status'] == 'approved']
            if not job['requirements']:
                raise HTTPException(409, '至少审核一条岗位要求再冻结材料')
            identifier = str(uuid4())
            created = now()
            body = json.dumps({'schema': 1, 'created_at': created, 'job': job}, ensure_ascii=False, sort_keys=True)
            db.execute('INSERT INTO packets VALUES(?,?,?,?,?)', (identifier, jid, body, digest(body), created))
            event(db, jid, 'packet_frozen', {'id': identifier, 'sha256': digest(body)})
            return {'id': identifier, 'sha256': digest(body)}

    @app.get('/api/packets/{pid}/export')
    def export(pid: str):
        with connect(path) as db:
            row = get(db, 'packets', pid)
        return Response(row['body'], media_type='application/json', headers={'Content-Disposition': 'attachment; filename="applytrack-packet.json"'})

    transitions = {'saved': {'applied','withdrawn'}, 'applied': {'screening','interview','rejected','withdrawn'},
                   'screening': {'interview','rejected','withdrawn'}, 'interview': {'offer','rejected','withdrawn'},
                   'offer': {'accepted','withdrawn'}, 'rejected': {'saved'}, 'withdrawn': {'saved'}, 'accepted': set()}

    @app.post('/api/jobs/{jid}/stage')
    def stage(jid: str, data: Transition):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            job = get(db, 'jobs', jid)
            check_version(job, data.version)
            if data.stage not in transitions[job['stage']]:
                raise HTTPException(409, '不允许该阶段变更')
            if data.stage == 'applied':
                snapshot = get(db, 'packets', data.packet_id)
                if snapshot['job_id'] != jid:
                    raise HTTPException(422, '投递材料不属于该岗位')
            db.execute('UPDATE jobs SET stage=?,version=version+1 WHERE id=?', (data.stage, jid))
            event(db, jid, 'stage_changed', {'from': job['stage'], **data.model_dump()})
            return get(db, 'jobs', jid)

    @app.post('/api/jobs/{jid}/follow-up')
    def follow_up(jid: str, data: FollowUp):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            job = get(db, 'jobs', jid)
            check_version(job, data.version)
            db.execute('UPDATE jobs SET follow_up=?,version=version+1 WHERE id=?', (data.due.isoformat() if data.due else '', jid))
            event(db, jid, 'follow_up_changed', {'from': job['follow_up'], **data.model_dump(mode='json')})
            return get(db, 'jobs', jid)

    web = Path(__file__).resolve().parents[1] / 'web'
    app.mount('/static', StaticFiles(directory=web), name='static')

    @app.get('/')
    def home():
        return FileResponse(web / 'index.html')

    return app


app = create_app()
