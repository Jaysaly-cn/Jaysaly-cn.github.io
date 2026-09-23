import json
import asyncio
import csv
import os
import sqlite3
from contextlib import contextmanager, asynccontextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from . import security, model
from .ingest import ingest, similar

ROOT=Path(__file__).resolve().parents[1]
def now():return datetime.now(timezone.utc).isoformat()

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)

class Annotation(Strict):
    source_id:str=Field(min_length=1,max_length=200)
    theme:str=Field(min_length=2,max_length=100)
    kind:Literal['problem','request','praise','other']
    quote:str=Field(min_length=2,max_length=4000)

class Review(Strict):
    version:int=Field(ge=1)
    decision:Literal['confirmed','rejected']
    note:str=Field(min_length=5,max_length=1000)

class Report(Strict):
    title:str=Field(min_length=2,max_length=200)
    note:str=Field(min_length=5,max_length=2000)

class SuggestRequest(Strict):
    source_id:str=Field(min_length=1,max_length=200)

class Suggested(Strict):
    theme:str=Field(min_length=2,max_length=100)
    kind:Literal['problem','request','praise','other']
    quote:str=Field(min_length=2,max_length=4000)

class ModelResult(Strict):
    suggestions:list[Suggested]=Field(max_length=5)

class Revision(Suggested):
    version:int=Field(ge=1)
    note:str=Field(min_length=5,max_length=1000)

class Duplicate(Strict):
    source_id:str=Field(min_length=1,max_length=200)
    target_id:str|None=Field(default=None,min_length=1,max_length=200)
    version:int=Field(ge=0)
    note:str=Field(min_length=5,max_length=1000)

def initialize(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path)) as c:
        c.row_factory=sqlite3.Row
        c.executescript('''
        CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,sha256 TEXT UNIQUE,raw BLOB);
        CREATE TABLE IF NOT EXISTS feedback(source_id TEXT PRIMARY KEY,channel TEXT,text TEXT);
        CREATE TABLE IF NOT EXISTS import_rows(import_id TEXT REFERENCES imports(id),line INTEGER,source_id TEXT REFERENCES feedback(source_id));
        CREATE TABLE IF NOT EXISTS annotations(id TEXT PRIMARY KEY,source_id TEXT REFERENCES feedback(source_id),theme TEXT,kind TEXT,quote TEXT,state TEXT,version INTEGER);
        CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,annotation_id TEXT REFERENCES annotations(id),snapshot TEXT,note TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY,title TEXT,snapshot TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS model_runs(id TEXT PRIMARY KEY,source_id TEXT REFERENCES feedback(source_id),raw TEXT,status TEXT,error TEXT,annotation_ids TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS duplicates(source_id TEXT PRIMARY KEY REFERENCES feedback(source_id),target_id TEXT REFERENCES feedback(source_id),version INTEGER,note TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS duplicate_events(id TEXT PRIMARY KEY,source_id TEXT REFERENCES feedback(source_id),snapshot TEXT,created_at TEXT);
        ''')
        if 'metadata' not in {r['name'] for r in c.execute('PRAGMA table_info(model_runs)')}:
            c.execute("ALTER TABLE model_runs ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")

def create_app(path=None):
    path=path or os.getenv('FEEDBACKLENS_DB',str(ROOT/'data/feedback.sqlite3'))
    def resolve_path():return Path(path() if callable(path) else path)
    @contextmanager
    def db():
        c=sqlite3.connect(resolve_path(),timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:yield c
        finally:c.close()
    @asynccontextmanager
    async def lifespan(app):
        initialize(resolve_path())
        yield
    app=FastAPI(title='FeedbackLens',version='0.1.0',lifespan=lifespan)
    security.install(app)
    generating=asyncio.Lock()

    @app.exception_handler(ValueError)
    @app.exception_handler(csv.Error)
    async def invalid(request,exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':str(exc)},status_code=422)

    @app.get('/api/status')
    def status():return {'version':'0.1.0','model_configured':model.configured(),'stage':'model-review-api'}

    @app.post('/api/imports',status_code=201)
    async def import_csv(request:Request):return ingest(resolve_path(),await request.body())

    @app.get('/api/feedback')
    def feedback():
        with db() as c:return [dict(row) for row in c.execute('SELECT * FROM feedback ORDER BY source_id')]

    @app.get('/api/similar')
    def candidates(source_id:str):return similar(resolve_path(),source_id)

    @app.get('/api/duplicates')
    def duplicates():
        with db() as c:return [dict(r) for r in c.execute('SELECT * FROM duplicates ORDER BY source_id')]

    @app.get('/api/duplicates/{source_id}/history')
    def duplicate_history(source_id:str):
        with db() as c:return [dict(r) for r in c.execute('SELECT * FROM duplicate_events WHERE source_id=? ORDER BY created_at,id',(source_id,))]

    @app.post('/api/duplicates')
    def decide_duplicate(item:Duplicate):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            for sid in (item.source_id,item.target_id):
                if sid is not None and not c.execute('SELECT 1 FROM feedback WHERE source_id=?',(sid,)).fetchone():raise HTTPException(404,'反馈不存在')
            old=c.execute('SELECT * FROM duplicates WHERE source_id=?',(item.source_id,)).fetchone()
            if item.version!=(old['version'] if old else 0):raise HTTPException(409,'重复判断已更新，请刷新')
            if item.target_id==(old['target_id'] if old else None):raise HTTPException(422,'重复判断没有变化')
            if item.target_id is not None:
                if item.source_id==item.target_id:raise HTTPException(422,'不能标记为自身的重复')
                if c.execute('SELECT 1 FROM duplicates WHERE source_id=? AND target_id IS NOT NULL',(item.target_id,)).fetchone():raise HTTPException(422,'目标已被标记为重复，请选择其代表记录')
                if c.execute('SELECT 1 FROM duplicates WHERE target_id=?',(item.source_id,)).fetchone():raise HTTPException(422,'本条已有重复记录，请先撤销这些标记')
            updated={**item.model_dump(),'version':item.version+1,'created_at':now()}
            c.execute('INSERT INTO duplicates VALUES(:source_id,:target_id,:version,:note,:created_at) ON CONFLICT(source_id) DO UPDATE SET target_id=excluded.target_id,version=excluded.version,note=excluded.note,created_at=excluded.created_at',updated)
            c.execute('INSERT INTO duplicate_events VALUES(?,?,?,?)',(uuid4().hex,item.source_id,json.dumps({'previous':dict(old) if old else None,'current':updated},ensure_ascii=False),updated['created_at']))
            return updated

    @app.get('/api/annotations')
    def annotations():
        with db() as c:return [dict(row) for row in c.execute('SELECT * FROM annotations ORDER BY rowid DESC')]

    @app.get('/api/model-runs')
    def model_runs():
        with db() as c:return [dict(row) for row in c.execute('SELECT * FROM model_runs ORDER BY created_at DESC')]

    @app.post('/api/suggestions',status_code=201)
    async def suggest(item:SuggestRequest):
        if not model.configured():raise HTTPException(503,'未配置本地免费模型，可手工归类')
        if generating.locked():raise HTTPException(409,'已有模型请求正在执行')
        async with generating:
            with db() as c:
                row=c.execute('SELECT * FROM feedback WHERE source_id=?',(item.source_id,)).fetchone()
                if not row:raise HTTPException(404,'反馈不存在')
                if c.execute('SELECT count(*) FROM model_runs').fetchone()[0]>=100:raise HTTPException(409,'最多保存100次模型记录')
                source=dict(row)
            raw=None;error=None;code=502;identity=uuid4().hex;created=[];metadata=model.provenance()
            try:
                raw=await model.propose(source)
                result=ModelResult.model_validate_json(raw)
                if any(s.quote not in source['text'] for s in result.suggestions):
                    code=422;raise ValueError('quote_mismatch')
            except Exception as exc:
                error='quote_mismatch' if code==422 else type(exc).__name__
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                if not error:
                    count=c.execute('SELECT count(*) FROM annotations').fetchone()[0]
                    if count+len(result.suggestions)>2000:error='annotation_capacity';code=409
                    else:
                        for s in result.suggestions:
                            aid=uuid4().hex
                            c.execute('INSERT INTO annotations VALUES(?,?,?,?,?,?,?)',(aid,item.source_id,s.theme,s.kind,s.quote,'draft',1))
                            created.append(aid)
                c.execute('INSERT INTO model_runs VALUES(?,?,?,?,?,?,?,?)',(identity,item.source_id,raw,'failed' if error else 'saved',error,json.dumps(created),now(),json.dumps(metadata)))
                record=dict(c.execute('SELECT * FROM model_runs WHERE id=?',(identity,)).fetchone())
            if error:raise HTTPException(code,'模型建议未保存，原因见模型记录；可手工归类')
            return record

    @app.post('/api/annotations',status_code=201)
    def annotate(item:Annotation):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            source=c.execute('SELECT text FROM feedback WHERE source_id=?',(item.source_id,)).fetchone()
            if not source:raise HTTPException(404,'反馈不存在')
            if item.quote not in source['text']:raise HTTPException(422,'引用必须逐字来自反馈原文')
            if c.execute('SELECT count(*) FROM annotations').fetchone()[0]>=2000:raise HTTPException(409,'归类数量达到2000条上限')
            identity=uuid4().hex
            c.execute('INSERT INTO annotations VALUES(?,?,?,?,?,?,?)',(identity,item.source_id,item.theme,item.kind,item.quote,'draft',1))
            return dict(c.execute('SELECT * FROM annotations WHERE id=?',(identity,)).fetchone())

    @app.post('/api/annotations/{identity}/revise')
    def revise(identity:str,item:Revision):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM annotations WHERE id=?',(identity,)).fetchone()
            if not row:raise HTTPException(404,'归类不存在')
            if row['version']!=item.version:raise HTTPException(409,'归类已更新，请刷新')
            source=c.execute('SELECT text FROM feedback WHERE source_id=?',(row['source_id'],)).fetchone()
            if item.quote not in source['text']:raise HTTPException(422,'引用必须逐字来自反馈原文')
            if all(row[key]==getattr(item,key) for key in ('theme','kind','quote')):raise HTTPException(422,'内容没有变化')
            c.execute('UPDATE annotations SET theme=?,kind=?,quote=?,state=?,version=version+1 WHERE id=?',(item.theme,item.kind,item.quote,'draft',identity))
            updated=dict(c.execute('SELECT * FROM annotations WHERE id=?',(identity,)).fetchone())
            snapshot={'action':'revised','previous':dict(row),'current':updated}
            c.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',(uuid4().hex,identity,json.dumps(snapshot,ensure_ascii=False),item.note,now()))
            return updated

    @app.get('/api/annotations/{identity}/history')
    def history(identity:str):
        with db() as c:return [dict(r) for r in c.execute('SELECT * FROM reviews WHERE annotation_id=? ORDER BY created_at,id',(identity,))]

    @app.post('/api/annotations/{identity}/review')
    def review(identity:str,item:Review):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM annotations WHERE id=?',(identity,)).fetchone()
            if not row:raise HTTPException(404,'归类不存在')
            if row['version']!=item.version:raise HTTPException(409,'归类已更新，请刷新')
            if row['state']==item.decision:raise HTTPException(409,'状态未变化')
            c.execute('UPDATE annotations SET state=?,version=version+1 WHERE id=?',(item.decision,identity))
            updated=dict(c.execute('SELECT * FROM annotations WHERE id=?',(identity,)).fetchone())
            c.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',(uuid4().hex,identity,json.dumps(updated,ensure_ascii=False),item.note,now()))
            return updated

    @app.post('/api/reports',status_code=201)
    def report(item:Report):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT count(*) FROM reports').fetchone()[0]>=100:raise HTTPException(409,'报告数量达到100份上限')
            evidence=[dict(row) for row in c.execute("SELECT a.*,f.channel,f.text FROM annotations a JOIN feedback f ON a.source_id=f.source_id WHERE a.state='confirmed' ORDER BY a.theme,a.source_id,a.id")]
            groups={}
            for row in evidence:groups.setdefault(row['theme'],set()).add(row['source_id'])
            decisions=[dict(row) for row in c.execute('SELECT * FROM duplicates ORDER BY source_id')]
            mapping={d['source_id']:d['target_id'] for d in decisions if d['target_id'] is not None}
            def canonical(ids):return sorted({mapping.get(s,s) for s in ids})
            all_ids=[r[0] for r in c.execute('SELECT source_id FROM feedback')]
            snapshot={'title':item.title,'review_note':item.note,'created_at':now(),
                      'counting_rule':'Raw counts use unique source_id. Deduplicated counts use explicitly reviewed representative IDs, per theme and overall. All evidence remains. Neither count measures people or priority. A representative may have no annotation of its own; themes are not transferred to it.',
                      'total_feedback':c.execute('SELECT count(*) FROM feedback').fetchone()[0],
                      'confirmed_feedback':len({row['source_id'] for row in evidence}),
                      'deduplicated_total_feedback':len(canonical(all_ids)),
                      'deduplicated_confirmed_feedback':len(canonical(row['source_id'] for row in evidence)),
                      'duplicate_decisions':decisions,
                      'themes':[{'theme':theme,'feedback_count':len(ids),'source_ids':sorted(ids),'deduplicated_feedback_count':len(canonical(ids)),'representative_ids':canonical(ids)} for theme,ids in sorted(groups.items())],
                      'evidence':evidence,
                      'imports':[dict(row) for row in c.execute('SELECT id,sha256 FROM imports ORDER BY id')]}
            identity=uuid4().hex
            c.execute('INSERT INTO reports VALUES(?,?,?,?)',(identity,item.title,json.dumps(snapshot,ensure_ascii=False),snapshot['created_at']))
            return {'id':identity,**snapshot}

    @app.get('/api/reports')
    def reports():
        with db() as c:return [dict(row) for row in c.execute('SELECT id,title,created_at FROM reports ORDER BY created_at DESC')]

    @app.get('/api/reports/{identity}')
    def read_report(identity:str):
        with db() as c:
            row=c.execute('SELECT snapshot FROM reports WHERE id=?',(identity,)).fetchone()
            if not row:raise HTTPException(404,'报告不存在')
            return {'id':identity,**json.loads(row['snapshot'])}
    app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='web')
    return app

app=create_app()
