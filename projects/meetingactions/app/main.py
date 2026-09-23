import asyncio
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from . import anchors, dates, exports, model, security, segments
from .store import connect, initialize, now

ROOT = Path(__file__).resolve().parents[1]
Name = Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=120)]
Note = Annotated[str,StringConstraints(strip_whitespace=True,min_length=5,max_length=2000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Meeting(Strict):
    title: Name
    meeting_date: date
    attendees: list[Name] = Field(min_length=1,max_length=30)
    transcript: Annotated[str,StringConstraints(strip_whitespace=True,min_length=10,max_length=80000)]

    @field_validator('attendees')
    @classmethod
    def unique(cls, values):
        if len(set(values)) != len(values):
            raise ValueError('参会者不能重复')
        return values


class Candidate(Strict):
    title: Annotated[str,StringConstraints(strip_whitespace=True,min_length=2,max_length=300)]
    quote: Annotated[str,StringConstraints(strip_whitespace=True,min_length=4,max_length=2000)]
    owner: Annotated[str,StringConstraints(strip_whitespace=True,max_length=120)] = ''
    due_phrase: Annotated[str,StringConstraints(strip_whitespace=True,max_length=80)] = ''


class Extract(Strict):
    segment: int = Field(default=0, ge=0)
    rerun: bool = False


class Review(Strict):
    version: int = Field(ge=1)
    decision: Literal['confirm','reject']
    title: Annotated[str,StringConstraints(strip_whitespace=True,min_length=2,max_length=300)]
    owner: Annotated[str,StringConstraints(strip_whitespace=True,max_length=120)] = ''
    due_date: date | None = None
    no_deadline: bool = False
    note: Note


class Update(Strict):
    version: int = Field(ge=1)
    state: Literal['open','in_progress','blocked','done','cancelled']
    note: Note


class Schedule(Strict):
    version: int = Field(ge=1)
    owner: Name
    due_date: date | None = None
    no_deadline: bool = False
    note: Note


def dump(v):
    return json.dumps(v,ensure_ascii=False)


def get(db, table, identity):
    row = db.execute(f'SELECT * FROM {table} WHERE id=?',(identity,)).fetchone()
    if not row:
        raise HTTPException(404,'记录不存在')
    item = dict(row)
    if 'attendees' in item:
        item['attendees'] = json.loads(item['attendees'])
    return item


def event(db, mid, aid, name, detail):
    db.execute('INSERT INTO events(meeting_id,action_id,event,detail,created_at) VALUES(?,?,?,?,?)',(mid,aid,name,dump(detail),now()))


def create_app(path=None):
    path = path or os.getenv('MEETINGACTIONS_DB',str(ROOT/'data/meetingactions.db'))

    @asynccontextmanager
    async def lifespan(app):
        initialize(path)
        yield

    app = FastAPI(title='MeetingActions',lifespan=lifespan)
    security.install(app)
    busy = asyncio.Lock()

    def add(db, mid, body, origin):
        meeting = get(db,'meetings',mid)
        try:
            start, owner_anchor = anchors.locate(meeting['transcript'],body.quote,body.owner,meeting['attendees'])
        except ValueError as exc:
            raise HTTPException(422,str(exc))
        if body.due_phrase and body.due_phrase not in body.quote:
            raise HTTPException(422,'期限词必须来自引用原文')
        existing = db.execute('SELECT * FROM actions WHERE meeting_id=? AND quote=? AND title=?',(mid,body.quote,body.title)).fetchone()
        if existing:
            return {**dict(existing),'deduplicated':True}
        if db.execute('SELECT count(*) FROM actions WHERE meeting_id=?',(mid,)).fetchone()[0]>=100:
            raise HTTPException(409,'单次会议最多 100 项行动')
        aid, stamp = uuid4().hex, now()
        due = dates.resolve(body.due_phrase,meeting['meeting_date'])
        db.execute('''INSERT INTO actions(id,meeting_id,title,quote,quote_start,proposed_owner,proposed_due,due_phrase,
                      origin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                   (aid,mid,body.title,body.quote,start,body.owner,due,body.due_phrase,origin,stamp,stamp))
        event(db,mid,aid,'candidate_created',{'origin':origin,'quote_start':start,'owner_anchor':owner_anchor})
        return get(db,'actions',aid)

    @app.get('/api/health')
    def health():
        return {'status':'ok','model_configured':model.configured(),'input_limit':4000}

    def segment_plan(meeting, runs):
        plan = segments.split(meeting['transcript'])
        for part in plan:
            latest = segments.matching_run(runs, part, meeting['sha256'])
            run = segments.matching_run([r for r in runs if r['state']=='success'], part, meeting['sha256']) or latest
            part.update(state=run['state'] if run else 'pending', run_id=run['id'] if run else None,
                        last_attempt=latest['state'] if latest else None)
        return plan

    @app.post('/api/meetings',status_code=201)
    def meeting(body:Meeting):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM meetings').fetchone()[0]>=100:
                raise HTTPException(409,'会议上限为100')
            mid = uuid4().hex
            db.execute('INSERT INTO meetings VALUES(?,?,?,?,?,?,?)',(mid,body.title,body.meeting_date.isoformat(),
                dump(body.attendees),body.transcript,hashlib.sha256(body.transcript.encode()).hexdigest(),now()))
            event(db,mid,'','meeting_created',{})
            return get(db,'meetings',mid)

    @app.get('/api/meetings')
    def meetings():
        with connect(path) as db:
            return [dict(r) for r in db.execute('SELECT id,title,meeting_date,created_at FROM meetings ORDER BY created_at DESC')]

    @app.get('/api/meetings/{mid}')
    def detail(mid:str):
        with connect(path) as db:
            result = get(db,'meetings',mid)
            result['actions'] = [dict(r) for r in db.execute('SELECT * FROM actions WHERE meeting_id=? ORDER BY created_at',(mid,))]
            result['events'] = [dict(r) for r in db.execute('SELECT * FROM events WHERE meeting_id=? ORDER BY id DESC LIMIT 100',(mid,))]
            result['runs'] = [{**dict(r),'trace':json.loads(r['trace'])} for r in db.execute('SELECT * FROM runs WHERE meeting_id=? ORDER BY created_at DESC',(mid,))]
            result['segments'] = segment_plan(result, result['runs'])
            return result

    @app.post('/api/meetings/{mid}/candidates',status_code=201)
    def candidate(mid:str,body:Candidate):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            return add(db,mid,body,'manual')

    @app.post('/api/meetings/{mid}/extract',status_code=201)
    async def extract(mid:str, body:Extract = Extract()):
        with connect(path) as db:
            meeting = get(db,'meetings',mid)
            parts = segments.split(meeting['transcript'])
            if body.segment >= len(parts):
                raise HTTPException(422,'分段不存在，请刷新原文范围')
            part = parts[body.segment]
            runs = [{**dict(r),'trace':json.loads(r['trace'])} for r in db.execute(
                "SELECT * FROM runs WHERE meeting_id=? AND state='success' ORDER BY created_at DESC", (mid,))]
            previous = segments.matching_run(runs, part, meeting['sha256'])
            if previous and not body.rerun:
                ids = next((t['action_ids'] for t in previous['trace'] if 'action_ids' in t), [])
                return {'id':previous['id'], 'actions':[get(db,'actions',aid) for aid in ids],
                        'trace':previous['trace'], 'reused':True, 'truncated':len(parts)>1, 'segment':part}
        if not model.configured():
            raise HTTPException(503,'免费模型未配置，可先手工关联行动项')
        if busy.locked():
            raise HTTPException(409,'模型正在处理，请完成后再试')
        trace = [{'step':'read','processed':part['chars'],'total':len(meeting['transcript']),
                  **part, 'segmentation':segments.VERSION, 'sha256':meeting['sha256']}]
        start, rid = time.monotonic(), uuid4().hex
        async with busy:
            # The demo counts actual attempts here, after successful-run reuse
            # and the process-wide busy check, never based on a client header.
            before_call = getattr(app.state, 'before_model_call', None)
            if before_call:
                before_call()
            try:
                raw = await model.extract(meeting['transcript'][part['start']:part['end']],meeting['attendees'])
                trace.append({'step':'model_output','candidates':raw})
                bodies = [Candidate.model_validate(x) for x in raw]
                if any(b.quote not in meeting['transcript'][part['start']:part['end']] for b in bodies):
                    raise ValueError('引用必须属于当前处理段')
                trace.append({'step':'extract','model':os.environ['MA_MODEL'],'count':len(bodies)})
                with connect(path) as db:
                    db.execute('BEGIN IMMEDIATE')
                    results = [add(db,mid,b,'model') for b in bodies]
                    trace += [{'step':'validate','result':'all_valid'}, {'step':'review','result':'required', 'action_ids':[a['id'] for a in results]},
                              {'elapsed_ms':round((time.monotonic()-start)*1000)}]
                    db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(rid,mid,'success',dump(trace),now()))
                return {'id':rid,'actions':results,'trace':trace,'truncated':len(parts)>1,'reused':False,'segment':part}
            except Exception as exc:
                trace.append({'step':'failed','error_type':type(exc).__name__})
                with connect(path) as db:
                    db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(rid,mid,'failed',dump(trace),now()))
                raise HTTPException(502,'模型结果未通过验证或调用失败；本轮没有保存部分行动项')

    def confirmed_schedule(body, attendees):
        if body.owner not in attendees:
            raise HTTPException(422,'请确认名单中的负责人')
        if (body.due_date is None) != body.no_deadline:
            raise HTTPException(422,'请选择日期，或明确勾选未约定期限；两者不可同时选择')

    @app.post('/api/actions/{aid}/review')
    def review(aid:str,body:Review):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            action = get(db,'actions',aid)
            if action['version']!=body.version or action['state']!='draft':
                raise HTTPException(409,'只能审核当前待确认版本，请刷新')
            meeting = get(db,'meetings',action['meeting_id'])
            if body.decision=='confirm':
                confirmed_schedule(body,meeting['attendees'])
            state = 'open' if body.decision=='confirm' else 'rejected'
            db.execute('''UPDATE actions SET title=?,owner=?,due_date=?,state=?,review_note=?,version=version+1,updated_at=? WHERE id=?''',
                       (body.title,body.owner if state=='open' else '',str(body.due_date or '') if state=='open' else '',state,body.note,now(),aid))
            event(db,action['meeting_id'],aid,'reviewed',body.model_dump(mode='json'))
            return get(db,'actions',aid)

    @app.post('/api/actions/{aid}/state')
    def state(aid:str,body:Update):
        allowed = {'open':{'in_progress','blocked','cancelled'},'in_progress':{'blocked','done','cancelled'},
                   'blocked':{'open','in_progress','cancelled'},'done':{'open'},'cancelled':{'open'}}
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            a = get(db,'actions',aid)
            if a['version']!=body.version or body.state not in allowed.get(a['state'],set()):
                raise HTTPException(409,'状态或版本已变化，不能执行此操作')
            db.execute('UPDATE actions SET state=?,completion_note=?,version=version+1,updated_at=? WHERE id=?',
                       (body.state,body.note if body.state=='done' else '',now(),aid))
            event(db,a['meeting_id'],aid,'state_changed',{'from':a['state'],**body.model_dump()})
            return get(db,'actions',aid)

    @app.post('/api/actions/{aid}/schedule')
    def schedule(aid:str,body:Schedule):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            a = get(db,'actions',aid)
            if a['version']!=body.version or a['state'] not in ('open','in_progress','blocked'):
                raise HTTPException(409,'只能调整当前未完成任务，请刷新')
            confirmed_schedule(body,get(db,'meetings',a['meeting_id'])['attendees'])
            db.execute('UPDATE actions SET owner=?,due_date=?,version=version+1,updated_at=? WHERE id=?',
                       (body.owner,str(body.due_date or ''),now(),aid))
            event(db,a['meeting_id'],aid,'rescheduled',{'previous_owner':a['owner'],'previous_due':a['due_date'],**body.model_dump(mode='json')})
            return get(db,'actions',aid)

    def board_rows(db,owner='',overdue=False,today=None):
        rows = [dict(r) for r in db.execute('''SELECT a.*,m.title AS meeting_title,m.attendees FROM actions a JOIN meetings m ON a.meeting_id=m.id
                     WHERE a.state NOT IN ('draft','rejected') ORDER BY a.due_date='',a.due_date,a.created_at''')]
        stamp = (today or date.today()).isoformat()
        for r in rows:
            r['attendees'] = json.loads(r['attendees'])
            r['overdue'] = bool(r['due_date'] and r['due_date']<stamp and r['state'] not in ('done','cancelled'))
        return [r for r in rows if (not owner or r['owner']==owner) and (not overdue or r['overdue'])]

    @app.get('/api/board')
    def board(owner:str='',overdue:bool=False,today:date|None=None):
        with connect(path) as db:
            return board_rows(db,owner,overdue,today)

    @app.get('/api/export/{format}')
    def export(format:Literal['json','csv','ics']):
        with connect(path) as db:
            rows = board_rows(db)
        body = dump({'generated_at':now(),'actions':rows}) if format=='json' else exports.csv_content(rows) if format=='csv' else exports.calendar(rows)
        media = {'json':'application/json','csv':'text/csv','ics':'text/calendar'}[format]
        return Response(body,media_type=media,headers={'Content-Disposition':f'attachment; filename="meeting-actions.{format}"'})

    @app.get('/')
    def index():
        return FileResponse(ROOT/'web/index.html')

    app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')
    return app


app = create_app()
