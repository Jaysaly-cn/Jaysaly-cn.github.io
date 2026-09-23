import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from . import collect, model, report, security, segments, batches
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


class Revision(Strict):
    version: int = Field(ge=1)
    dimension: Name
    statement: Short
    quote: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=4000)]
    quote_start: int | None = Field(default=None, ge=0)
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=1000)]


class Archive(Strict):
    archived: bool


def create_app(db_path=None):
    path = db_path or os.getenv('EVIDENCEBRIEF_DB', str(ROOT / 'data/evidencebrief.sqlite3'))

    @asynccontextmanager
    async def lifespan(app):
        if not callable(path):
            initialize(path)
        yield

    app = FastAPI(title='EvidenceBrief', version='0.4.0', lifespan=lifespan)
    security.install(app)
    slots = asyncio.Semaphore(2)
    in_flight = set()  # Single-process workspace; no persisted running state to strand on restart.

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

    def remember(db, row, action, note):
        db.execute('INSERT OR IGNORE INTO claim_versions VALUES(?,?,?,?,?,?)',
                   (row['id'],row['version'],json.dumps(dict(row),ensure_ascii=False),action,note,now()))

    def claim_row(db, pid, cid):
        row=db.execute('SELECT * FROM claims WHERE id=? AND project_id=?',(cid,pid)).fetchone()
        if not row:
            raise HTTPException(404,'此项目内不存在该结论')
        return dict(row)

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

    def add_claim(db, pid, body, origin='human', quote_start=None):
        p = project_row(db, pid)
        source = source_row(db, pid, body.source_id)
        if source['archived']:
            raise HTTPException(409, '已归档来源不能新增结论')
        if body.dimension not in p['dimensions']:
            raise HTTPException(422, '比较维度不属于此研究项目')
        position = source['content'].find(body.quote) if quote_start is None else quote_start
        if position < 0 or source['content'][position:position+len(body.quote)] != body.quote:
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
        result=claim_row(db,pid,identity)
        remember(db,result,'created','初始候选')
        return result

    def snapshot(db, pid):
        p = project_row(db, pid)
        sources = [dict(r) for r in db.execute('SELECT * FROM sources WHERE project_id=? ORDER BY captured_at', (pid,))]
        for source in sources:
            source['extraction_coverage'] = segment_state(db,pid,source['id'])
        claims = [dict(r) for r in db.execute('SELECT * FROM claims WHERE project_id=? ORDER BY created_at', (pid,))]
        return report.build(p, sources, claims)

    @app.get('/api/health')
    def health():
        with connect(path) as db:
            db.execute('SELECT 1')
        return {'status': 'ok', 'version': '0.4.0', 'model_configured': model.configured(),
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
            remember(db,row,'baseline','版本记录启用时保留的当前状态；此前历史不可追溯')
            db.execute('UPDATE claims SET state=?,review_note=?,version=version+1,updated_at=? WHERE id=?',
                       (body.state, body.note, now(), cid))
            label = {'draft': '待确认', 'approved': '已确认', 'rejected': '已退回'}[body.state]
            event(db, pid, 'claim_reviewed', f'{row["statement"]} → {label}；{body.note}')
            result=claim_row(db,pid,cid)
            remember(db,result,'reviewed',body.note)
            return result

    @app.post('/api/projects/{pid}/claims/{cid}/revisions',status_code=201)
    def revise_claim(pid: str,cid: str,body: Revision):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            row=claim_row(db,pid,cid)
            if row['version']!=body.version:
                raise HTTPException(409,'结论已更新，请刷新后修订')
            source=source_row(db,pid,row['source_id'])
            if source['archived']:
                raise HTTPException(409,'已归档来源不能修订结论')
            if body.dimension not in project_row(db,pid)['dimensions']:
                raise HTTPException(422,'比较维度不属于此研究项目')
            position=body.quote_start
            if position is None:
                position=source['content'].find(body.quote)
                if position>=0 and source['content'].find(body.quote,position+1)>=0:
                    raise HTTPException(422,'引用重复，请填写明确的全文起始位置或扩展上下文')
            if position<0 or source['content'][position:position+len(body.quote)]!=body.quote:
                raise HTTPException(422,'引用或位置与原始来源不一致')
            changed=(body.dimension,body.statement,body.quote,position)
            if changed==(row['dimension'],row['statement'],row['quote'],row['quote_start']):
                raise HTTPException(422,'修订内容未发生变化')
            remember(db,row,'baseline','版本记录启用时保留的当前状态；此前历史不可追溯')
            db.execute("UPDATE claims SET dimension=?,statement=?,quote=?,quote_start=?,state='draft',review_note='',version=version+1,updated_at=? WHERE id=?",
                       (*changed,now(),cid))
            result=claim_row(db,pid,cid)
            remember(db,result,'revised',body.note)
            event(db,pid,'claim_revised',f'结论 {cid}：v{row["version"]} → v{result["version"]}，重新待审核；{body.note}')
            return result

    @app.get('/api/projects/{pid}/claims/{cid}/versions')
    def versions(pid: str,cid: str):
        with connect(path) as db:
            current=claim_row(db,pid,cid)
            history=[{**dict(r),'snapshot':json.loads(r['snapshot'])} for r in db.execute(
                'SELECT * FROM claim_versions WHERE claim_id=? ORDER BY version',(cid,))]
            return {'current':current,'versions':history,'note':'仅记录启用版本管理后的变化；旧记录首次变更时保存当时基线，不补造历史。'}

    def segment_state(db, pid, sid):
        source = source_row(db, pid, sid)
        rows = {r['segment_index']: dict(r) for r in db.execute(
            'SELECT * FROM extraction_segments WHERE source_id=? AND plan_version=?', (sid, segments.VERSION))}
        windows = []
        for w in segments.plan(source['content']):
            saved = rows.get(w['index'], {})
            windows.append({**w, 'state': 'running' if (sid,w['index']) in in_flight else saved.get('state','pending'),
                            'attempts': saved.get('attempts',0), 'error': saved.get('error',''),
                            'claim_ids': json.loads(saved.get('claim_ids','[]'))})
        processed = segments.covered([w for w in windows if w['state']=='success'])
        return {'plan_version': segments.VERSION, 'segments': windows, 'covered_characters': processed,
                'total_characters': len(source['content']), 'complete': processed==len(source['content'])}

    @app.get('/api/projects/{pid}/sources/{sid}/segments')
    def source_segments(pid: str, sid: str):
        with connect(path) as db:
            return segment_state(db,pid,sid)

    @app.post('/api/projects/{pid}/sources/{sid}/suggest', status_code=201)
    async def suggestions(pid: str, sid: str, segment: int = Query(default=0, ge=0)):
        if not model.configured():
            raise HTTPException(409, '未配置免费/本地模型；可手工关联原文并继续研究')
        with connect(path) as db:
            p = project_row(db, pid)
            source = source_row(db, pid, sid)
            if source['archived']:
                raise HTTPException(409, '已归档来源不能抽取建议')
            windows = segments.plan(source['content'])
            if segment >= len(windows):
                raise HTTPException(422, '分段不存在')
            window = windows[segment]
            prior = db.execute('SELECT * FROM extraction_segments WHERE source_id=? AND plan_version=? AND segment_index=?',
                               (sid, segments.VERSION, segment)).fetchone()
            if prior and prior['state']=='success':
                return {'claims': [], 'cached': True, 'coverage': segment_state(db,pid,sid), 'segment': window}
        key = (sid, segment)
        if key in in_flight:
            raise HTTPException(409, '此段正在处理，请等待当前请求完成')
        in_flight.add(key)
        excerpt = source['content'][window['start']:window['end']]
        attempts = prior['attempts'] + 1 if prior else 1

        def save_attempt(db, state, ids, error=''):
            db.execute('INSERT OR REPLACE INTO extraction_segments VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (sid, segments.VERSION, segment, window['start'], window['end'], state, attempts,
                        os.environ.get('EB_MODEL',''), json.dumps(ids), error, now()))
        try:
            async with slots:
                proposed = await model.suggest({**source,'content':excerpt}, p['dimensions'])
            bodies = [Claim(source_id=sid, **item) for item in proposed]
            offsets = []
            for body in bodies:
                position = excerpt.find(body.quote)
                if position < 0 or excerpt.find(body.quote,position+1)>=0:
                    raise ValueError('引用必须唯一定位在当前分段内')
                offsets.append(window['start']+position)
            with connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                if source_row(db,pid,sid)['archived']:
                    raise ValueError('来源处理期间已归档')
                results = [add_claim(db, pid, body, 'model', offset) for body,offset in zip(bodies,offsets)]
                save_attempt(db,'success',[r['id'] for r in results])
                processed = len(excerpt)
                event(db, pid, 'model_suggested', f'第{segment+1}段 [{window["start"]},{window["end"]})：{len(results)} 条候选；均需人工审核')
            in_flight.discard(key)
            with connect(path) as db:
                coverage = segment_state(db,pid,sid)
            return {'claims': results, 'model': os.environ['EB_MODEL'], 'scope': f'characters {window["start"]}:{window["end"]}',
                    'processed_characters': processed, 'total_characters': len(source['content']),
                    'truncated': not coverage['complete'], 'segment': window, 'coverage': coverage, 'cached': False}
        except Exception as exc:
            with connect(path) as db:
                save_attempt(db,'failed',[],type(exc).__name__)
                event(db, pid, 'model_failed', type(exc).__name__)
            raise HTTPException(502, '此段模型建议未通过验证或调用失败；未保存此段半成品，可重试；其他已成功分段保留')
        finally:
            in_flight.discard(key)

    batches.install(app,path,project_row,source_row,suggestions)

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
