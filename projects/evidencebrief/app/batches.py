"""Durable, bounded orchestration of the existing verified segment tool; single worker."""
import asyncio
import json
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from . import segments
from .store import connect,now


class Plan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_ids:list[str]=Field(min_length=1,max_length=8)


class Advance(BaseModel):
    model_config=ConfigDict(extra='forbid')
    retry_failed:bool=False


class Pause(BaseModel):
    model_config=ConfigDict(extra='forbid')
    paused:bool


def install(app,path,project_row,source_row,suggest):
    active=set()
    def read(db,pid,bid):
        row=db.execute('SELECT * FROM extraction_batches WHERE id=? AND project_id=?',(bid,pid)).fetchone()
        if row is None:raise HTTPException(404,'研究执行计划不存在')
        result=dict(row);result['steps']=json.loads(row['steps']);result['paused']=bool(row['paused'])
        for step in result['steps']:
            if step['state']=='running' and bid not in active:step['state']='interrupted'
        result['complete']=all(s['state']=='success' for s in result['steps'])
        result['notice']='仅执行选定资料的证据候选抽取；完成不代表研究完整，也不批准结论。'
        return result

    @app.post('/api/projects/{pid}/batches',status_code=201)
    def create(pid:str,body:Plan):
        if len(set(body.source_ids))!=len(body.source_ids):raise HTTPException(422,'来源不可重复')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE');project_row(db,pid)
            if db.execute('SELECT count(*) FROM extraction_batches WHERE project_id=?',(pid,)).fetchone()[0]>=10:
                raise HTTPException(409,'每项目最多10份执行计划')
            steps=[]
            for sid in body.source_ids:
                source=source_row(db,pid,sid)
                if source['archived']:raise HTTPException(409,'归档来源不能加入计划')
                for window in segments.plan(source['content']):
                    steps.append({'source_id':sid,'title':source['title'],'sha256':source['sha256'],
                                  'plan_version':segments.VERSION,**window,'state':'pending','attempts':0,'claim_ids':[],'error':''})
            if len(steps)>32:raise HTTPException(422,'单计划最多32个分段，请减少来源；未截断资料')
            bid,stamp=uuid4().hex,now()
            db.execute('INSERT INTO extraction_batches VALUES(?,?,?,0,?,?)',(bid,pid,json.dumps(steps,ensure_ascii=False),stamp,stamp))
            return read(db,pid,bid)

    @app.get('/api/projects/{pid}/batches/{bid}')
    def status(pid:str,bid:str):
        with connect(path) as db:return read(db,pid,bid)

    @app.post('/api/projects/{pid}/batches/{bid}/pause')
    def pause(pid:str,bid:str,body:Pause):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE');read(db,pid,bid)
            db.execute('UPDATE extraction_batches SET paused=?,updated_at=? WHERE id=?',(body.paused,now(),bid))
            return read(db,pid,bid)

    @app.post('/api/projects/{pid}/batches/{bid}/next')
    async def advance(pid:str,bid:str,body:Advance):
        if bid in active:raise HTTPException(409,'计划中已有步骤执行，请等待该步骤结束')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE');batch=read(db,pid,bid)
            if batch['paused']:raise HTTPException(409,'计划已暂停；当前正在执行的步骤不会被强制中断')
            candidates=[s for s in batch['steps'] if s['state'] in ('pending','interrupted')]
            if not candidates and body.retry_failed:candidates=[s for s in batch['steps'] if s['state']=='failed']
            if not candidates:return batch
            step=candidates[0];step.update(state='running',attempts=step['attempts']+1,error='')
            db.execute('UPDATE extraction_batches SET steps=?,updated_at=? WHERE id=?',(json.dumps(batch['steps'],ensure_ascii=False),now(),bid))
        active.add(bid)
        def save():
            with connect(path) as db:db.execute('UPDATE extraction_batches SET steps=?,updated_at=? WHERE id=?',
                (json.dumps(batch['steps'],ensure_ascii=False),now(),bid))
        try:
            with connect(path) as db:
                source=source_row(db,pid,step['source_id'])
                if source['sha256']!=step['sha256'] or step['plan_version']!=segments.VERSION:
                    raise HTTPException(409,'资料或分段规则变化，请建立新计划')
            result=await suggest(pid,step['source_id'],step['index'])
            completed=next(w for w in result['coverage']['segments'] if w['index']==step['index'])
            step.update(state='success',claim_ids=completed['claim_ids'],cached=result['cached'])
            save()
        except asyncio.CancelledError:
            step.update(state='interrupted',error='请求中断；可继续，已保存分段会复用');save();raise
        except Exception as exc:
            step.update(state='failed',error=(str(exc.detail) if isinstance(exc,HTTPException) else type(exc).__name__))
            save()
        finally:active.discard(bid)
        with connect(path) as db:return read(db,pid,bid)
