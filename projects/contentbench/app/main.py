import asyncio
from difflib import SequenceMatcher
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from . import model, security
from .checks import CHANNELS, check
from .store import connect, initialize, now

ROOT = Path(__file__).resolve().parents[1]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=3000)]
Channel = Literal['小红书', '公众号', '短信', '邮件']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Fact(Strict):
    id: Annotated[str, StringConstraints(pattern=r'^F[1-9][0-9]?$')]
    text: Text
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]


class Brief(Strict):
    name: Name
    audience: Name
    objective: Name
    tone: Name
    facts: list[Fact] = Field(min_length=1, max_length=20)
    forbidden: list[Name] = Field(default_factory=list, max_length=30)
    required_phrase: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ''

    @field_validator('facts')
    @classmethod
    def unique(cls, value):
        if len({v.id for v in value}) != len(value):
            raise ValueError('事实 ID 不可重复')
        return value


class Copy(Strict):
    title: Name
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=6000)]
    fact_ids: list[Name] = Field(max_length=20)


class Draft(Copy):
    channel: Channel


class Revision(Copy):
    expected_revision: Name


class Review(Strict):
    state: Literal['approved', 'rejected']
    version: int = Field(ge=1)
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
    facts_checked: bool = False


class Generate(Strict):
    channel: Channel


def decode(row):
    result = dict(row)
    for key in ('brief', 'fact_ids', 'checks', 'snapshot'):
        if key in result:
            result[key] = json.loads(result[key])
    return result


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def event(db, campaign, action, detail):
    db.execute('INSERT INTO events(campaign_id,action,detail,created_at) VALUES(?,?,?,?)',
               (campaign, action, detail, now()))


def get(db, table, id):
    # table is only supplied by static route code, never by a request.
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (id,)).fetchone()
    if not row:
        raise HTTPException(404, '记录不存在')
    return decode(row)


def validate_copy(brief, copy):
    if len(copy.fact_ids) != len(set(copy.fact_ids)) or set(copy.fact_ids) - {f['id'] for f in brief['facts']}:
        raise HTTPException(422, '引用事实必须来自当前活动，且不可重复')


def add_revision(db, draft, brief, copy, number, origin, model_name=''):
    validate_copy(brief, copy)
    rid = uuid4().hex
    checks = check(brief, draft['channel'], copy.title, copy.body, copy.fact_ids)
    db.execute('''INSERT INTO revisions(id,draft_id,number,title,body,fact_ids,origin,model,checks,state,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?,'draft',?)''',
               (rid, draft['id'], number, copy.title, copy.body, dump(copy.fact_ids), origin, model_name, dump(checks), now()))
    db.execute('UPDATE drafts SET current_revision=? WHERE id=?', (rid, draft['id']))
    event(db, draft['campaign_id'], 'revision_created', rid)
    return get(db, 'revisions', rid)


def create_app(path=None):
    path = path or os.getenv('CONTENTBENCH_DB', str(ROOT / 'data/contentbench.db'))

    @asynccontextmanager
    async def lifespan(app):
        initialize(path)
        yield

    app = FastAPI(title='ContentBench', lifespan=lifespan)
    security.install(app)
    generating = asyncio.Lock()

    @app.get('/api/status')
    def status():
        return {'model_configured': model.configured(), 'channels': CHANNELS, 'mode': 'single-team',
                'semantic_verification': '人工逐句审核；规则检查不保证事实正确'}

    @app.post('/api/campaigns', status_code=201)
    def create_campaign(brief: Brief):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM campaigns').fetchone()[0] >= 100:
                raise HTTPException(409, '本机工作台活动上限为 100')
            cid = uuid4().hex
            db.execute('INSERT INTO campaigns VALUES(?,?,?)', (cid, dump(brief.model_dump()), now()))
            event(db, cid, 'campaign_created', brief.name)
            return get(db, 'campaigns', cid)

    @app.get('/api/campaigns')
    def campaigns():
        with connect(path) as db:
            return [decode(r) for r in db.execute('SELECT * FROM campaigns ORDER BY created_at DESC')]

    @app.get('/api/campaigns/{cid}')
    def campaign(cid: str):
        with connect(path) as db:
            result = get(db, 'campaigns', cid)
            result['drafts'] = []
            for row in db.execute('SELECT * FROM drafts WHERE campaign_id=? ORDER BY created_at DESC', (cid,)):
                draft = dict(row)
                draft['revisions'] = [decode(r) for r in db.execute('SELECT * FROM revisions WHERE draft_id=? ORDER BY number DESC', (row['id'],))]
                result['drafts'].append(draft)
            result['exports'] = [dict(r) for r in db.execute('SELECT id,created_at FROM exports WHERE campaign_id=? ORDER BY created_at DESC', (cid,))]
            result['events'] = [dict(r) for r in db.execute('SELECT * FROM events WHERE campaign_id=? ORDER BY id DESC LIMIT 100', (cid,))]
            return result

    def save_draft(cid, channel, copy, origin, model_name=''):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            brief = get(db, 'campaigns', cid)['brief']
            if db.execute('SELECT count(*) FROM drafts WHERE campaign_id=?', (cid,)).fetchone()[0] >= 50:
                raise HTTPException(409, '每个活动最多 50 份稿件')
            did = uuid4().hex
            db.execute('INSERT INTO drafts VALUES(?,?,?,?,?)', (did, cid, channel, '', now()))
            draft = get(db, 'drafts', did)
            return add_revision(db, draft, brief, copy, 1, origin, model_name)

    @app.post('/api/campaigns/{cid}/drafts', status_code=201)
    def new_draft(cid: str, copy: Draft):
        return save_draft(cid, copy.channel, copy, 'manual')

    @app.post('/api/campaigns/{cid}/generate', status_code=201)
    async def generate(cid: str, request: Generate):
        with connect(path) as db:
            brief = get(db, 'campaigns', cid)['brief']
        if not model.configured():
            raise HTTPException(503, '免费模型尚未配置，可以先手工录入稿件')
        if generating.locked():
            raise HTTPException(409, '模型正在生成，请完成后再试')
        async with generating:
            try:
                raw, name = await model.generate(brief, request.channel, CHANNELS[request.channel])
                copy = Copy.model_validate(raw)
                validate_copy(brief, copy)
            except Exception:
                with connect(path) as db:
                    event(db, cid, 'generation_failed', '模型返回无效、不可达或不符合免费配置要求')
                raise HTTPException(502, '生成失败；没有保存无效结果。请检查模型连接与结构化输出。')
            return save_draft(cid, request.channel, copy, 'model', name)

    @app.post('/api/drafts/{did}/revisions', status_code=201)
    def revise(did: str, copy: Revision):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            draft = get(db, 'drafts', did)
            if draft['current_revision'] != copy.expected_revision:
                raise HTTPException(409, '稿件已更新，请刷新再编辑')
            previous = get(db, 'revisions', draft['current_revision'])
            if previous['number'] >= 30:
                raise HTTPException(409, '每份稿件最多 30 个版本')
            brief = get(db, 'campaigns', draft['campaign_id'])['brief']
            return add_revision(db, draft, brief, copy, previous['number'] + 1, 'manual')

    @app.post('/api/revisions/{rid}/review')
    def review(rid: str, request: Review):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            revision = get(db, 'revisions', rid)
            draft = get(db, 'drafts', revision['draft_id'])
            if draft['current_revision'] != rid or revision['version'] != request.version:
                raise HTTPException(409, '版本已变化，只能审核最新稿件')
            if revision['state'] != 'draft':
                raise HTTPException(409, '该版本已完成审核；请创建修订版')
            if request.state == 'approved' and (not request.facts_checked or revision['checks']['blockers']):
                raise HTTPException(422, '请先修复规则问题，并确认已逐句核对事实')
            db.execute('UPDATE revisions SET state=?,review_note=?,version=version+1 WHERE id=?',
                       (request.state, request.note, rid))
            event(db, draft['campaign_id'], request.state, rid + ': ' + request.note)
            return get(db, 'revisions', rid)

    @app.get('/api/drafts/{did}/compare')
    def compare(did: str, before: str, after: str):
        with connect(path) as db:
            get(db, 'drafts', did)
            old, new = get(db, 'revisions', before), get(db, 'revisions', after)
            if old['draft_id'] != did or new['draft_id'] != did:
                raise HTTPException(404, '版本不属于当前稿件')
            changes = {}
            for field in ('title', 'body'):
                a, b = old[field].splitlines(keepends=True), new[field].splitlines(keepends=True)
                changes[field] = [{'operation': tag, 'before': ''.join(a[i:j]), 'after': ''.join(b[k:l])}
                                  for tag, i, j, k, l in SequenceMatcher(None, a, b).get_opcodes()]
            return {'before': old, 'after': new, 'changes': changes,
                    'facts_added': sorted(set(new['fact_ids']) - set(old['fact_ids'])),
                    'facts_removed': sorted(set(old['fact_ids']) - set(new['fact_ids'])),
                    'notice': '逐行文本差异，不判断语义正确性。对比不会修改审核状态或旧导出。'}

    @app.post('/api/campaigns/{cid}/exports', status_code=201)
    def export(cid: str):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            campaign = get(db, 'campaigns', cid)
            rows = db.execute('''SELECT r.*,d.channel FROM drafts d JOIN revisions r ON d.current_revision=r.id
                                 WHERE d.campaign_id=? AND r.state='approved' ORDER BY d.created_at''', (cid,)).fetchall()
            if not rows:
                raise HTTPException(409, '没有最新版本已审核通过的稿件')
            if db.execute('SELECT count(*) FROM exports WHERE campaign_id=?', (cid,)).fetchone()[0] >= 50:
                raise HTTPException(409, '每个活动最多 50 份导出快照')
            eid = uuid4().hex
            stamp = now()
            snapshot = {'id': eid, 'created_at': stamp, 'brief': campaign['brief'],
                        'copies': [decode(r) for r in rows], 'notice': '人工批准的导出快照；未向任何渠道发布'}
            db.execute('INSERT INTO exports VALUES(?,?,?,?)', (eid, cid, dump(snapshot), stamp))
            event(db, cid, 'export_created', eid)
            return snapshot

    @app.get('/api/exports/{eid}')
    def download(eid: str):
        with connect(path) as db:
            snapshot = get(db, 'exports', eid)['snapshot']
        return Response(json.dumps(snapshot, ensure_ascii=False, indent=2), media_type='application/json',
                        headers={'Content-Disposition': f'attachment; filename="contentbench-{eid}.json"'})

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'app/web/index.html')

    app.mount('/static', StaticFiles(directory=ROOT / 'app/web'), name='static')
    return app


app = create_app()
