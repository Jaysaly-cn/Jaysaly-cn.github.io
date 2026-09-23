import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from . import store, security, model

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Candidate(Strict):
    title: Text
    quote: Annotated[str, StringConstraints(min_length=2, max_length=3000)]
    quote_start: int | None = Field(default=None, ge=0)


class Revision(Candidate):
    version: int = Field(ge=1)
    note: Note


class Proposed(Strict):
    title: Text
    quote: Annotated[str, StringConstraints(min_length=2,max_length=3000)]
    owner: Annotated[str, StringConstraints(max_length=120)]
    due_phrase: Annotated[str, StringConstraints(max_length=200)]


class ModelOutput(Strict):
    actions: list[Proposed] = Field(max_length=8)


class Confirmation(Strict):
    version: int = Field(ge=1)
    owner: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    due_date: date | None
    note: Note
    conflict_ids: list[str] = Field(default_factory=list, max_length=500)


class Transition(Strict):
    version: int = Field(ge=1)
    state: Literal['open','doing','blocked','done','cancelled','rejected']
    note: Note


def now():
    return datetime.now(timezone.utc).isoformat()


def task(db, identity):
    row=db.execute('SELECT * FROM tasks WHERE id=?',(identity,)).fetchone()
    if not row:raise HTTPException(404,'任务不存在')
    return dict(row)


def record(db, identity, action, note, acknowledged_conflicts=None):
    snapshot=task(db,identity)
    if acknowledged_conflicts is not None:
        snapshot['acknowledged_conflicts']=acknowledged_conflicts
    db.execute('INSERT INTO task_events(task_id,action,note,snapshot,created_at) VALUES(?,?,?,?,?)',
               (identity,action,note,json.dumps(snapshot,ensure_ascii=False),now()))
    return snapshot


def locate(body, quote, start):
    if start is None:
        start=body.find(quote)
        if start<0:raise HTTPException(422,'引用不存在于邮件正文')
        if body.find(quote,start+1)>=0:raise HTTPException(422,'引用出现多次，请指定字符起点')
    if body[start:start+len(quote)]!=quote:raise HTTPException(422,'引用与字符起点不匹配')
    return start


def create_app(path=None):
    path=path or os.getenv('INBOXTOTASKS_DB',str(Path(__file__).resolve().parents[1]/'data/inbox.sqlite3'))
    @asynccontextmanager
    async def lifespan(app):
        store.initialize(path)
        yield
    app=FastAPI(title='InboxToTasks',lifespan=lifespan)
    security.install(app)
    generating=asyncio.Lock()

    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse({'detail':'邮件不存在'},status_code=404)

    @app.get('/api/status')
    def status():return {'stage':'model-candidates','model_configured':model.configured(),'mode':'single-local-workspace','model_character_limit':4000}

    @app.post('/api/messages/{mid}/suggest',status_code=201)
    async def suggest(mid:str):
        source=store.message(path,mid)
        if not model.configured():raise HTTPException(503,'免费模型未配置，仍可使用手工候选')
        if len(source['body'])>4000:raise HTTPException(422,'本版模型提取支持最多4000字符正文；不会静默截断，请使用手工候选')
        if generating.locked():raise HTTPException(409,'模型正在处理，请完成后重试')
        async with generating:
            with store.connect(path) as db:
                if db.execute('SELECT count(*) FROM model_runs WHERE message_id=?',(mid,)).fetchone()[0]>=30:
                    raise HTTPException(409,'每封邮件最多30次模型尝试')
            raw='';run_id=uuid4().hex;error='';items=[]
            try:
                raw=await model.extract(source)
                proposed=ModelOutput.model_validate_json(raw).actions
                for item in proposed:
                    offset=locate(source['body'],item.quote,None)
                    if item.owner and item.owner not in item.quote:raise ValueError('Owner is not grounded in quote')
                    if item.due_phrase and item.due_phrase not in item.quote:raise ValueError('Due phrase is not grounded in quote')
                    items.append((item,offset))
            except Exception as exc:
                error=type(exc).__name__
            with store.connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                existing=db.execute('SELECT count(*) FROM tasks WHERE message_id=?',(mid,)).fetchone()[0]
                if not error and existing+len(items)>50:error='CandidateLimit'
                db.execute('INSERT INTO model_runs VALUES(?,?,?,?,?,?,?)',
                           (run_id,mid,os.getenv('IT_MODEL',''),raw,'failed' if error else 'succeeded',error,now()))
                saved=[]
                if not error:
                    for item,offset in items:
                        duplicate=db.execute('SELECT id FROM tasks WHERE message_id=? AND title=? AND quote_start=? AND quote=?',
                                             (mid,item.title,offset,item.quote)).fetchone()
                        if duplicate:
                            saved.append(task(db,duplicate['id']));continue
                        identity=uuid4().hex
                        db.execute('INSERT INTO tasks(id,message_id,title,quote,quote_start,body_sha256,origin,created_at,proposed_owner,proposed_due) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                   (identity,mid,item.title,item.quote,offset,source['body_sha256'],'model',now(),item.owner,item.due_phrase))
                        saved.append(record(db,identity,'model_candidate','免费模型候选，必须核对否定、引用旧文与适用条件'))
            if error:raise HTTPException(502,'模型输出未通过协议或引用检查；本次未保存任何候选，失败记录已保留')
            return {'run_id':run_id,'tasks':saved,'notice':'候选可能误解语义或遗漏；重复条目复用原任务，不改变其状态'}

    @app.get('/api/messages/{mid}/model-runs')
    def model_runs(mid:str):
        store.message(path,mid)
        with store.connect(path) as db:
            return [dict(r) for r in db.execute('SELECT * FROM model_runs WHERE message_id=? ORDER BY created_at DESC',(mid,))]

    @app.post('/api/messages',status_code=201)
    async def ingest(request:Request):
        try:return store.import_message(path,await request.body())
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc

    @app.get('/api/messages')
    def listing():return store.messages(path)

    @app.get('/api/messages/{mid}')
    def get_message(mid:str):
        result=store.message(path,mid)
        with store.connect(path) as db:
            result['tasks']=[dict(r) for r in db.execute('SELECT * FROM tasks WHERE message_id=? ORDER BY created_at',(mid,))]
        return result

    @app.post('/api/messages/{mid}/tasks',status_code=201)
    def create_task(mid:str,request:Candidate):
        source=store.message(path,mid)
        offset=locate(source['body'],request.quote,request.quote_start)
        with store.connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM tasks WHERE message_id=?',(mid,)).fetchone()[0]>=50:
                raise HTTPException(409,'每封邮件最多50个候选')
            duplicate=db.execute('SELECT id FROM tasks WHERE message_id=? AND title=? AND quote_start=? AND quote=?',
                                 (mid,request.title,offset,request.quote)).fetchone()
            if duplicate:return task(db,duplicate['id'])
            identity=uuid4().hex
            db.execute('INSERT INTO tasks(id,message_id,title,quote,quote_start,body_sha256,created_at) VALUES(?,?,?,?,?,?,?)',
                       (identity,mid,request.title,request.quote,offset,source['body_sha256'],now()))
            return record(db,identity,'created','人工创建候选，尚未确认责任与期限')

    @app.post('/api/tasks/{tid}/revise')
    def revise(tid:str,request:Revision):
        with store.connect(path) as db:
            db.execute('BEGIN IMMEDIATE');old=task(db,tid)
            if old['version']!=request.version:raise HTTPException(409,'任务版本已变化')
            source=json.loads(db.execute('SELECT metadata FROM messages WHERE id=?',(old['message_id'],)).fetchone()['metadata'])
            offset=locate(source['body'],request.quote,request.quote_start)
            db.execute("UPDATE tasks SET title=?,quote=?,quote_start=?,owner='',due_date=NULL,proposed_owner='',proposed_due='',state='draft',version=version+1 WHERE id=?",
                       (request.title,request.quote,offset,tid))
            return record(db,tid,'revised',request.note)

    @app.post('/api/tasks/{tid}/confirm')
    def confirm(tid:str,request:Confirmation):
        with store.connect(path) as db:
            db.execute('BEGIN IMMEDIATE');old=task(db,tid)
            if old['version']!=request.version or old['state']!='draft':raise HTTPException(409,'只能确认当前候选版本')
            source=json.loads(db.execute('SELECT metadata FROM messages WHERE id=?',(old['message_id'],)).fetchone()['metadata'])
            conflicts=store.conflicts(db,source)
            if sorted(set(request.conflict_ids))!=sorted(conflicts):
                raise HTTPException(409,'存在邮件内容冲突，请核对所有冲突邮件后提交其ID')
            db.execute("UPDATE tasks SET owner=?,due_date=?,state='open',version=version+1 WHERE id=?",
                       (request.owner,request.due_date.isoformat() if request.due_date else None,tid))
            return record(db,tid,'confirmed',request.note,conflicts)

    @app.post('/api/tasks/{tid}/state')
    def transition(tid:str,request:Transition):
        allowed={'draft':{'rejected'},'rejected':set(),'open':{'doing','blocked','done','cancelled'},
                 'doing':{'open','blocked','done','cancelled'},'blocked':{'open','doing','cancelled'},
                 'done':{'open'},'cancelled':{'open'}}
        with store.connect(path) as db:
            db.execute('BEGIN IMMEDIATE');old=task(db,tid)
            if old['version']!=request.version:raise HTTPException(409,'任务版本已变化')
            if request.state not in allowed[old['state']]:raise HTTPException(409,'不允许该状态变化；候选需先确认')
            db.execute('UPDATE tasks SET state=?,version=version+1 WHERE id=?',(request.state,tid))
            return record(db,tid,'state_changed',request.note)

    @app.get('/api/tasks/{tid}/history')
    def history(tid:str):
        with store.connect(path) as db:
            task(db,tid)
            return [{**dict(r),'snapshot':json.loads(r['snapshot'])} for r in db.execute('SELECT * FROM task_events WHERE task_id=? ORDER BY id',(tid,))]

    @app.post('/api/exports',status_code=201)
    def export():
        with store.connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            tasks=[dict(r) for r in db.execute("SELECT * FROM tasks WHERE state NOT IN ('draft','rejected') ORDER BY created_at")]
            if not tasks:raise HTTPException(409,'没有已确认任务')
            if db.execute('SELECT count(*) FROM exports').fetchone()[0]>=100:raise HTTPException(409,'最多100份导出快照')
            sources={t['message_id'] for t in tasks}
            evidence=[{'id':mid,**json.loads(db.execute('SELECT metadata FROM messages WHERE id=?',(mid,)).fetchone()['metadata'])} for mid in sorted(sources)]
            for source in evidence:
                source['message_id_conflicts']=store.conflicts(db,source)
            identity=uuid4().hex;stamp=now()
            snapshot={'id':identity,'created_at':stamp,'tasks':tasks,'sources':evidence,
                      'notice':'人工确认的任务快照，包含已完成/取消状态；未向邮箱或日历发送内容'}
            db.execute('INSERT INTO exports VALUES(?,?,?)',(identity,json.dumps(snapshot,ensure_ascii=False),stamp))
            return snapshot

    @app.get('/api/exports/{eid}')
    def download(eid:str):
        with store.connect(path) as db:
            row=db.execute('SELECT snapshot FROM exports WHERE id=?',(eid,)).fetchone()
            if not row:raise HTTPException(404,'快照不存在')
            return JSONResponse(json.loads(row['snapshot']),headers={'Content-Disposition':f'attachment; filename="inbox-tasks-{eid}.json"'})
    @app.get('/api/exports')
    def exports():
        with store.connect(path) as db:
            return [dict(r) for r in db.execute('SELECT id,created_at FROM exports ORDER BY created_at DESC')]

    root=Path(__file__).resolve().parents[1]
    @app.get('/')
    def index():return FileResponse(root/'web/index.html')
    @app.get('/sample.eml')
    def sample():return FileResponse(root/'samples/request.eml',media_type='message/rfc822')
    app.mount('/static',StaticFiles(directory=root/'web'),name='static')
    return app


app=create_app()
