import asyncio
import json
from datetime import datetime,timezone
from typing import Literal
from uuid import uuid4
from fastapi import HTTPException
from fastapi.responses import Response
from .export import archive
from pydantic import BaseModel,ConfigDict,Field
from . import model

SCHEMA='''
CREATE TABLE IF NOT EXISTS impacts(id TEXT PRIMARY KEY,comparison_id TEXT REFERENCES comparisons(id),operation INTEGER,summary TEXT,old_quote TEXT,new_quote TEXT,state TEXT,version INTEGER);
CREATE TABLE IF NOT EXISTS impact_events(id TEXT PRIMARY KEY,impact_id TEXT REFERENCES impacts(id),snapshot TEXT,note TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS impact_runs(id TEXT PRIMARY KEY,comparison_id TEXT REFERENCES comparisons(id),operation INTEGER,raw TEXT,error TEXT,impact_id TEXT,metadata TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS briefs(id TEXT PRIMARY KEY,comparison_id TEXT REFERENCES comparisons(id),snapshot TEXT,created_at TEXT);
'''
def now():return datetime.now(timezone.utc).isoformat()
class Impact(BaseModel):
    model_config=ConfigDict(extra='forbid')
    summary:str=Field(min_length=5,max_length=1500)
    old_quote:str=Field(max_length=4000)
    new_quote:str=Field(max_length=4000)
class Revision(Impact):
    version:int=Field(ge=1)
    note:str=Field(min_length=5,max_length=1000)
class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:int=Field(ge=1)
    decision:Literal['confirmed','rejected']
    note:str=Field(min_length=5,max_length=1000)
class Brief(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=2,max_length=200)
    note:str=Field(min_length=5,max_length=2000)

def install_review(app,db):
    lock=asyncio.Lock()
    def comparison(c,cid):
        r=c.execute('SELECT snapshot FROM comparisons WHERE id=?',(cid,)).fetchone()
        if not r:raise HTTPException(404,'比较不存在')
        return json.loads(r['snapshot'])
    def operation(c,cid,index):
        operations=comparison(c,cid)['diff']['operations']
        if index<0 or index>=len(operations):raise HTTPException(404,'变更块不存在')
        op=operations[index]
        if op['kind']=='equal':raise HTTPException(422,'未改变的段落不能创建影响说明')
        return op
    def validate(item,op):
        if not item.summary.strip():raise HTTPException(422,'说明不能为空白')
        for side in ('old','new'):
            quote=getattr(item,side+'_quote');text=op[side+'_text']
            if (text and (not quote or quote not in text)) or (not text and quote):
                raise HTTPException(422,side+'_quote_mismatch')
    def save(c,cid,index,item):
        if c.execute('SELECT count(*) FROM impacts').fetchone()[0]>=1000:raise HTTPException(409,'影响说明上限1000条')
        identity=uuid4().hex
        c.execute('INSERT INTO impacts VALUES(?,?,?,?,?,?,?,?)',(identity,cid,index,item.summary,item.old_quote,item.new_quote,'draft',1))
        return dict(c.execute('SELECT * FROM impacts WHERE id=?',(identity,)).fetchone())

    @app.get('/api/comparisons/{cid}/impacts')
    def impacts(cid:str):
        with db() as c:
            comparison(c,cid)
            return [dict(r) for r in c.execute('SELECT * FROM impacts WHERE comparison_id=? ORDER BY rowid',(cid,))]

    @app.post('/api/comparisons/{cid}/operations/{index}/impacts',status_code=201)
    def manual(cid:str,index:int,item:Impact):
        with db() as c:
            c.execute('BEGIN IMMEDIATE');validate(item,operation(c,cid,index))
            return save(c,cid,index,item)

    @app.post('/api/comparisons/{cid}/operations/{index}/suggest',status_code=201)
    async def suggest(cid:str,index:int):
        if not model.configured():raise HTTPException(503,'未配置免费本地模型，可手工说明')
        if lock.locked():raise HTTPException(409,'模型正在处理其他请求')
        async with lock:
            with db() as c:
                op=operation(c,cid,index)
                if len(op['old_text'])+len(op['new_text'])>6000:raise HTTPException(422,'变更块超过模型6000字符限制，请手工复核')
                if c.execute('SELECT count(*) FROM impact_runs').fetchone()[0]>=100:raise HTTPException(409,'模型记录上限100次')
            raw=None;error=None;code=502;impact=None;metadata=model.provenance()
            try:
                raw=await model.propose(op)
                item=Impact.model_validate_json(raw)
                validate(item,op)
            except HTTPException as exc:error=exc.detail;code=exc.status_code
            except Exception as exc:error=type(exc).__name__
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                if not error:
                    try:impact=save(c,cid,index,item)
                    except HTTPException as exc:error=exc.detail;code=exc.status_code
                rid=uuid4().hex
                c.execute('INSERT INTO impact_runs VALUES(?,?,?,?,?,?,?,?)',(rid,cid,index,raw,error,impact['id'] if impact else None,json.dumps(metadata),now()))
            if error:raise HTTPException(code,'建议未保存，请查看模型记录')
            return impact

    @app.get('/api/comparisons/{cid}/model-runs')
    def runs(cid:str):
        with db() as c:
            comparison(c,cid)
            return [dict(r) for r in c.execute('SELECT * FROM impact_runs WHERE comparison_id=? ORDER BY created_at DESC',(cid,))]

    @app.post('/api/impacts/{identity}/revise')
    def revise(identity:str,item:Revision):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM impacts WHERE id=?',(identity,)).fetchone()
            if not row:raise HTTPException(404,'说明不存在')
            if row['version']!=item.version:raise HTTPException(409,'版本已更新')
            validate(item,operation(c,row['comparison_id'],row['operation']))
            if all(row[k]==getattr(item,k) for k in ('summary','old_quote','new_quote')):raise HTTPException(422,'内容未改变')
            c.execute("UPDATE impacts SET summary=?,old_quote=?,new_quote=?,state='draft',version=version+1 WHERE id=?",(item.summary,item.old_quote,item.new_quote,identity))
            updated=dict(c.execute('SELECT * FROM impacts WHERE id=?',(identity,)).fetchone())
            c.execute('INSERT INTO impact_events VALUES(?,?,?,?,?)',(uuid4().hex,identity,json.dumps({'previous':dict(row),'current':updated},ensure_ascii=False),item.note,now()))
            return updated

    @app.post('/api/impacts/{identity}/review')
    def review(identity:str,item:Review):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM impacts WHERE id=?',(identity,)).fetchone()
            if not row:raise HTTPException(404,'说明不存在')
            if row['version']!=item.version or row['state']==item.decision:raise HTTPException(409,'版本或状态已更新')
            c.execute('UPDATE impacts SET state=?,version=version+1 WHERE id=?',(item.decision,identity))
            updated=dict(c.execute('SELECT * FROM impacts WHERE id=?',(identity,)).fetchone())
            c.execute('INSERT INTO impact_events VALUES(?,?,?,?,?)',(uuid4().hex,identity,json.dumps({'previous':dict(row),'current':updated},ensure_ascii=False),item.note,now()))
            return updated

    @app.get('/api/impacts/{identity}/history')
    def history(identity:str):
        with db() as c:return [dict(r) for r in c.execute('SELECT * FROM impact_events WHERE impact_id=? ORDER BY created_at,id',(identity,))]

    @app.post('/api/comparisons/{cid}/briefs',status_code=201)
    def brief(cid:str,item:Brief):
        with db() as c:
            c.execute('BEGIN IMMEDIATE');snapshot=comparison(c,cid)
            if c.execute('SELECT count(*) FROM briefs').fetchone()[0]>=100:raise HTTPException(409,'简报上限100份')
            impacts=[dict(r) for r in c.execute("SELECT * FROM impacts WHERE comparison_id=? AND state='confirmed' ORDER BY operation,id",(cid,))]
            covered={r['operation'] for r in impacts}
            missing=[i for i,op in enumerate(snapshot['diff']['operations']) if op['kind']!='equal' and i not in covered]
            result={'title':item.title,'note':item.note,'comparison_id':cid,'comparison':snapshot,'confirmed_impacts':impacts,'unreviewed_operations':missing,'created_at':now()}
            identity=uuid4().hex
            c.execute('INSERT INTO briefs VALUES(?,?,?,?)',(identity,cid,json.dumps(result,ensure_ascii=False),result['created_at']))
            return {'id':identity,**result}

    @app.get('/api/comparisons/{cid}/briefs')
    def list_briefs(cid:str):
        with db() as c:
            comparison(c,cid)
            return [{'id':r['id'],'title':json.loads(r['snapshot'])['title'],'created_at':r['created_at']} for r in c.execute('SELECT * FROM briefs WHERE comparison_id=? ORDER BY created_at DESC',(cid,))]

    @app.get('/api/briefs/{identity}')
    def read_brief(identity:str):
        with db() as c:
            row=c.execute('SELECT snapshot FROM briefs WHERE id=?',(identity,)).fetchone()
            if not row:raise HTTPException(404,'简报不存在')
            return {'id':identity,**json.loads(row['snapshot'])}

    @app.get('/api/briefs/{identity}/export')
    def export_brief(identity:str):
        brief=read_brief(identity)
        return Response(archive(brief),media_type='application/zip',headers={
            'Content-Disposition':'attachment; filename="changelens-brief.zip"',
            'Cache-Control':'no-store'})
