import asyncio
import hmac
import hashlib
import json
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from . import model
from .db import connect, initialize, now, rowdict, record_document
from .retrieval import search

ROOT = Path(__file__).resolve().parents[1]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Document(StrictModel):
    title: Short
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=50000)]
    source: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = '用户导入'
    audience: Literal['public', 'internal'] = 'public'


class Ask(StrictModel):
    question: Question
    audience: Literal['public', 'internal'] = 'public'
    use_model: bool = False


class ReviseDocument(Document):
    version: int = Field(ge=1)
    change_note: Annotated[str, StringConstraints(strip_whitespace=True,min_length=5,max_length=2000)]


class Feedback(StrictModel):
    rating: Literal['helpful', 'unhelpful']
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ''


class NewTicket(StrictModel):
    run_id: Short
    title: Short


class UpdateTicket(StrictModel):
    version: int = Field(ge=1)
    status: Literal['open', 'in_progress', 'waiting', 'resolved']
    assignee: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ''
    resolution: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = ''

class PublishKnowledge(StrictModel):
    version: int = Field(ge=1)
    title: Short
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=50000)]
    review_note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]
    reviewed: bool = False

class RecheckReview(StrictModel):
    verdict: Literal['improved','regressed','unchanged','inconclusive']
    note: Annotated[str,StringConstraints(strip_whitespace=True,min_length=5,max_length=2000)]
    reviewed: bool = False


def create_app(db_path=None, *, allow_model=True):
    path = db_path or os.getenv('SUPPORTOPS_DB', str(ROOT / 'data/supportops.sqlite3'))

    @asynccontextmanager
    async def lifespan(app):
        if not callable(path):
            initialize(path)
        yield

    app = FastAPI(title='SupportOps', version='0.3.0', lifespan=lifespan)
    model_slots = asyncio.Semaphore(2)
    requests = defaultdict(deque)

    @app.middleware('http')
    async def guard(request: Request, call_next):
        if request.url.path.startswith('/api/'):
            demo = request.scope.get('isolated_demo_session', False)
            token = os.getenv('SUPPORTOPS_ACCESS_TOKEN', '')
            supplied = request.headers.get('authorization', '').removeprefix('Bearer ')
            host = request.client.host if request.client else ''
            if not demo and token and not hmac.compare_digest(supplied, token):
                return JSONResponse({'detail': '请输入此工作台的访问令牌'}, status_code=401)
            if not demo and not token and host not in ('127.0.0.1', '::1', 'testclient'):
                return JSONResponse({'detail': '远程访问必须配置 SUPPORTOPS_ACCESS_TOKEN'}, status_code=403)
            if not demo and not token and request.url.hostname not in ('127.0.0.1', 'localhost', '::1', 'testserver'):
                return JSONResponse({'detail': '本地模式不接受外部 Host'}, status_code=403)
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                return JSONResponse({'detail': '不允许跨站访问'}, status_code=403)
            if request.method not in ('GET', 'HEAD'):
                stamp = time.monotonic()
                # Single-process bounded rate history; deploy one worker for this SQLite edition.
                history = requests['workspace']
                while history and stamp - history[0] > 60:
                    history.popleft()
                if len(history) >= 60:
                    return JSONResponse({'detail': '工作台每分钟最多 60 次写入，请稍后重试'}, status_code=429)
                history.append(stamp)
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 240000:
                        return JSONResponse({'detail': '请求过大，请限制为 240KB'}, status_code=413)
                    body.extend(chunk)
                # Starlette's cached Request body is replayed to downstream handlers.
                request._body = bytes(body)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def get_run(run_id):
        with connect(path) as db:
            result = rowdict(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone(),
                             ('citations', 'trace', 'usage'))
        if result is None:
            raise HTTPException(404, '回答记录不存在')
        return result

    @app.get('/api/health')
    def health():
        with connect(path) as db:
            db.execute('SELECT 1')
        return {'status': 'ok', 'model_configured': allow_model and model.configured(),
                'model': os.getenv('LLM_MODEL', '') if allow_model and model.configured() else None,
                'model_disabled_reason': '' if allow_model else '演示仅提供证据检索；小模型答复实测未达标',
                'retrieval': 'BM25Plus / Chinese bigram', 'version': '0.3.0'}

    @app.get('/api/documents')
    def documents():
        with connect(path) as db:
            return [dict(r) for r in db.execute('SELECT * FROM documents ORDER BY created_at DESC')]

    @app.post('/api/documents', status_code=201)
    def add_document(body: Document):
        identity = uuid4().hex
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM documents').fetchone()[0] >= 100:
                raise HTTPException(409, '此版本每个工作台最多 100 篇文档')
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)',
                       (identity, body.title, body.content, body.source, body.audience, 1, now()))
            record_document(db,identity,'新资料导入')
        return {'id': identity}

    @app.patch('/api/documents/{document_id}')
    def revise_document(document_id: str, body: ReviseDocument):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            original=db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
            if original is None:raise HTTPException(404,'文档不存在')
            if original['version']!=body.version:raise HTTPException(409,'资料已更新，请重新载入当前版本再修订')
            fields=('title','content','source','audience')
            if all(original[key]==getattr(body,key) for key in fields):raise HTTPException(422,'资料内容未改变')
            if db.execute('SELECT count(*) FROM document_versions WHERE document_id=?',(document_id,)).fetchone()[0]>=100:
                raise HTTPException(409,'每份资料最多保留100个版本')
            db.execute('UPDATE documents SET title=?,content=?,source=?,audience=?,version=version+1 WHERE id=?',
                       (*[getattr(body,key) for key in fields],document_id))
            record_document(db,document_id,body.change_note)
            return dict(db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone())

    @app.get('/api/documents/{document_id}/history')
    def document_history(document_id: str):
        with connect(path) as db:
            rows=[rowdict(row,('snapshot',)) for row in db.execute(
                'SELECT * FROM document_versions WHERE document_id=? ORDER BY version',(document_id,))]
            if not rows:raise HTTPException(404,'资料历史不存在')
            return {'current':rowdict(db.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()),'versions':rows}

    @app.delete('/api/documents/{document_id}')
    def delete_document(document_id: str):
        with connect(path) as db:
            if not db.execute('DELETE FROM documents WHERE id=?', (document_id,)).rowcount:
                raise HTTPException(404, '文档不存在')
        return {'deleted': document_id, 'note': '历史回答保留当时引用快照'}

    @app.post('/api/seed')
    def seed():
        source = json.loads((ROOT / 'examples/knowledge.json').read_text(encoding='utf-8'))
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute('SELECT count(*) FROM documents').fetchone()[0]
            missing = [d for d in source if not db.execute('SELECT 1 FROM documents WHERE id=?', (d['id'],)).fetchone()]
            if count + len(missing) > 100:
                raise HTTPException(409, '导入将超过文档数量限制')
            if any(db.execute('SELECT count(*) FROM document_versions WHERE document_id=?',(d['id'],)).fetchone()[0]>=100 for d in missing):
                raise HTTPException(409,'示例资料已达到100个历史版本上限')
            for d in missing:
                version=db.execute('SELECT coalesce(max(version),0)+1 FROM document_versions WHERE document_id=?',(d['id'],)).fetchone()[0]
                db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)',
                    (d['id'], d['title'], d['content'], '合成示例 / 星河协作 SaaS', d['audience'], version, now()))
                record_document(db,d['id'],'载入合成示例；既有历史保留')
        return {'inserted': len(missing)}

    @app.post('/api/ask', status_code=201)
    async def ask(body: Ask):
        if body.use_model and not allow_model:
            raise HTTPException(409, '演示仅提供证据检索；小模型答复实测未达标，请关闭模型生成')
        start = time.perf_counter()
        with connect(path) as db:
            docs = [dict(r) for r in db.execute(
                'SELECT * FROM documents WHERE audience=? OR audience=?', ('public', body.audience))]
        citations = search(docs, body.question)
        trace = [{'step': 'retrieve', 'status': 'ok', 'documents_searched': len(docs),
                  'chunks_returned': len(citations), 'method': 'BM25Plus; lexical relevance is not confidence'}]
        usage = {}
        if not citations:
            answer = '知识库没有检索到相关证据。请补充资料或创建工单交由人工处理。'
            mode = 'no_evidence'
        else:
            answer = '以下为关键词检索得到的原文片段，尚未经模型判断是否足以回答问题：\n\n' + '\n\n'.join(
                f'[{i + 1}] {c["title"]}\n{c["content"]}' for i, c in enumerate(citations))
            mode = 'extractive'
            if body.use_model:
                if not model.configured():
                    raise HTTPException(409, '尚未配置模型。可关闭模型生成以运行真实证据检索。')
                try:
                    async with model_slots:
                        result = await model.generate(body.question, citations)
                    usage = result['usage']
                    mode = 'insufficient' if result['insufficient'] else 'model'
                    answer = result['answer']
                    trace.append({'step': 'generate', 'status': 'ok', 'model': os.environ['LLM_MODEL'],
                                  'citation_ids': result['citation_ids'], 'insufficient': result['insufficient']})
                except Exception as exc:
                    # Never return upstream messages: they may contain credentials or private endpoint details.
                    mode = 'model_error'
                    trace.append({'step': 'generate', 'status': 'error', 'error_type': type(exc).__name__})
                    answer = '模型调用失败，以下保留检索证据供人工核对。\n\n' + answer
        trace.append({'step': 'review', 'status': 'human_required', 'reason': '答复建议不会自动发送给客户'})
        result = {'id': uuid4().hex, 'question': body.question, 'audience': body.audience,
                  'answer': answer, 'mode': mode, 'citations': citations, 'trace': trace,
                  'elapsed_ms': round((time.perf_counter() - start) * 1000), 'usage': usage, 'created_at': now()}
        with connect(path) as db:
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)',
                tuple(json.dumps(result[k], ensure_ascii=False) if k in ('citations', 'trace', 'usage') else result[k]
                      for k in ('id', 'question', 'audience', 'answer', 'mode', 'citations', 'trace', 'elapsed_ms', 'usage', 'created_at')))
        return result

    @app.get('/api/runs')
    def runs():
        with connect(path) as db:
            return [dict(r) for r in db.execute('''SELECT r.id,r.question,r.mode,r.elapsed_ms,r.created_at,
                f.rating FROM runs r LEFT JOIN feedback f ON r.id=f.run_id ORDER BY r.created_at DESC LIMIT 100''')]

    @app.get('/api/runs/{run_id}')
    def run(run_id: str):
        return get_run(run_id)

    @app.post('/api/runs/{run_id}/feedback')
    def feedback(run_id: str, body: Feedback):
        get_run(run_id)
        with connect(path) as db:
            db.execute('INSERT INTO feedback VALUES (?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET rating=excluded.rating,note=excluded.note,updated_at=excluded.updated_at',
                       (run_id, body.rating, body.note, now()))
        return {'saved': True}

    @app.post('/api/runs/{run_id}/rechecks',status_code=201)
    def recheck(run_id: str):
        before=get_run(run_id)
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM rechecks WHERE run_id=?',(run_id,)).fetchone()[0]>=20:
                raise HTTPException(409,'每个原问题最多保留20次复查')
            documents=[dict(r) for r in db.execute('SELECT * FROM documents WHERE audience=? OR audience=?',('public',before['audience']))]
            citations=search(documents,before['question'])
            identity,stamp=uuid4().hex,now()
            snapshot={'before':before,'after':{'question':before['question'],'audience':before['audience'],
                'citations':citations,'documents_searched':len(documents),'created_at':stamp,
                'manifest':[{'id':d['id'],'version':d['version'],'sha256':hashlib.sha256(d['content'].encode()).hexdigest()} for d in documents]},
                'method':'Same BM25 retrieval; no model call; compare evidence only, not answer accuracy'}
            db.execute('INSERT INTO rechecks(id,run_id,snapshot,created_at) VALUES(?,?,?,?)',
                       (identity,run_id,json.dumps(snapshot,ensure_ascii=False),stamp))
            return rowdict(db.execute('SELECT * FROM rechecks WHERE id=?',(identity,)).fetchone(),('snapshot',))

    @app.get('/api/rechecks')
    def rechecks():
        with connect(path) as db:
            return [rowdict(r,('snapshot',)) for r in db.execute('SELECT * FROM rechecks ORDER BY created_at DESC LIMIT 50')]

    @app.post('/api/rechecks/{recheck_id}/review')
    def review_recheck(recheck_id: str,body: RecheckReview):
        if not body.reviewed:raise HTTPException(422,'请先核对前后证据与问题的关系')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            check=db.execute('SELECT * FROM rechecks WHERE id=?',(recheck_id,)).fetchone()
            if check is None:raise HTTPException(404,'复查记录不存在')
            if check['verdict']:raise HTTPException(409,'该次复查判断已保存，不覆盖原结论；可重新复查')
            db.execute('UPDATE rechecks SET verdict=?,note=?,reviewed_at=? WHERE id=?',(body.verdict,body.note,now(),recheck_id))
            return rowdict(db.execute('SELECT * FROM rechecks WHERE id=?',(recheck_id,)).fetchone(),('snapshot',))

    @app.get('/api/badcases')
    def badcases():
        with connect(path) as db:
            return [dict(r) for r in db.execute('''SELECT r.id,r.question,r.mode,f.note,r.created_at FROM runs r
                LEFT JOIN feedback f ON r.id=f.run_id WHERE f.rating='unhelpful'
                OR r.mode IN ('no_evidence','model_error','insufficient') ORDER BY r.created_at DESC LIMIT 100''')]

    @app.post('/api/tickets', status_code=201)
    def create_ticket(body: NewTicket):
        source = get_run(body.run_id)
        question = source['question'].lower()
        category = '技术支持' if any(w in question for w in ('错误', '登录', '故障', 'api')) else '一般咨询'
        priority = 'high' if any(w in question for w in ('泄露', '宕机', '无法使用', '全员')) else 'normal'
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM tickets WHERE run_id=?', (body.run_id,)).fetchone()
            if existing:
                return {**dict(existing), 'deduplicated': True}
            identity, stamp = uuid4().hex, now()
            db.execute('INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (identity, body.run_id, body.title, category, priority, 'open', '', '', 1, stamp, stamp))
            db.execute('INSERT INTO events(ticket_id,event,detail,created_at) VALUES (?,?,?,?)',
                       (identity, 'created', '从回答记录创建；分类和优先级为关键词规则建议', stamp))
            return dict(db.execute('SELECT * FROM tickets WHERE id=?', (identity,)).fetchone())

    @app.get('/api/tickets')
    def tickets():
        with connect(path) as db:
            return [dict(r) for r in db.execute('SELECT * FROM tickets ORDER BY created_at DESC LIMIT 200')]

    @app.get('/api/tickets/{ticket_id}')
    def ticket(ticket_id: str):
        with connect(path) as db:
            result = rowdict(db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone())
            if result is None:
                raise HTTPException(404, '工单不存在')
            result['events'] = [dict(r) for r in db.execute('SELECT * FROM events WHERE ticket_id=? ORDER BY id', (ticket_id,))]
            result['publications'] = [rowdict(r,('snapshot',)) for r in db.execute(
                'SELECT * FROM knowledge_publications WHERE ticket_id=? ORDER BY created_at',(ticket_id,))]
        result['run'] = get_run(result['run_id'])
        return result

    @app.post('/api/tickets/{ticket_id}/knowledge',status_code=201)
    def publish_knowledge(ticket_id: str, body: PublishKnowledge):
        if not body.reviewed:raise HTTPException(422,'请确认已删除个案隐私并核对通用知识适用范围')
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            ticket=db.execute('SELECT * FROM tickets WHERE id=?',(ticket_id,)).fetchone()
            if ticket is None:raise HTTPException(404,'工单不存在')
            if ticket['version']!=body.version:raise HTTPException(409,'工单版本已变化，请重新核对')
            if ticket['status']!='resolved':raise HTTPException(409,'只有已解决工单可以沉淀知识')
            if db.execute('SELECT 1 FROM knowledge_publications WHERE ticket_id=? AND ticket_version=?',
                          (ticket_id,body.version)).fetchone():raise HTTPException(409,'此工单版本已经发布过知识，请查看原记录')
            if db.execute('SELECT count(*) FROM documents').fetchone()[0]>=100:raise HTTPException(409,'知识库已达到100篇上限')
            run=rowdict(db.execute('SELECT * FROM runs WHERE id=?',(ticket['run_id'],)).fetchone(),('citations','trace','usage'))
            audience=run['audience']
            document_id,publication_id,stamp=uuid4().hex,uuid4().hex,now()
            source=f'人工审核工单 {ticket_id} / 版本 {body.version}'
            document={'id':document_id,'title':body.title,'content':body.content,'source':source,'audience':audience,'version':1,'created_at':stamp}
            snapshot={'ticket':dict(ticket),'run':run,'document':document,'review_note':body.review_note}
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?)',tuple(document.values()))
            record_document(db,document_id,'由已解决工单人工审核发布')
            db.execute('INSERT INTO knowledge_publications VALUES(?,?,?,?,?,?)',
                       (publication_id,ticket_id,body.version,document_id,json.dumps(snapshot,ensure_ascii=False),stamp))
            db.execute('INSERT INTO events(ticket_id,event,detail,created_at) VALUES(?,?,?,?)',
                       (ticket_id,'knowledge_published',f'已发布知识：{body.title}；范围继承原问题：{audience}；工单版本{body.version}',stamp))
            return {'id':publication_id,'document_id':document_id,'audience':audience,'ticket_version':body.version}

    @app.patch('/api/tickets/{ticket_id}')
    def update_ticket(ticket_id: str, body: UpdateTicket):
        allowed = {'open': {'open', 'in_progress'}, 'in_progress': {'in_progress', 'waiting', 'resolved'},
                   'waiting': {'waiting', 'in_progress'}, 'resolved': {'resolved', 'open'}}
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            original = db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone()
            if original is None:
                raise HTTPException(404, '工单不存在')
            if original['version'] != body.version:
                raise HTTPException(409, '工单已被更新，请刷新后重试')
            if body.status not in allowed[original['status']]:
                raise HTTPException(409, '状态流转不允许，请先认领处理或恢复处理')
            if body.status in ('in_progress', 'waiting', 'resolved') and not body.assignee:
                raise HTTPException(422, '请填写处理人')
            if body.status == 'resolved' and not body.resolution:
                raise HTTPException(422, '解决工单必须填写解决记录')
            stamp = now()
            db.execute('UPDATE tickets SET status=?,assignee=?,resolution=?,version=version+1,updated_at=? WHERE id=?',
                       (body.status, body.assignee, body.resolution, stamp, ticket_id))
            db.execute('INSERT INTO events(ticket_id,event,detail,created_at) VALUES (?,?,?,?)',
                       (ticket_id, 'updated', json.dumps({'from': original['status'], **body.model_dump()}, ensure_ascii=False), stamp))
            return dict(db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone())

    @app.get('/api/metrics')
    def metrics():
        with connect(path) as db:
            count = lambda table: db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
            return {'documents': count('documents'), 'runs': count('runs'), 'tickets': count('tickets'),
                    'modes': {r[0]: r[1] for r in db.execute('SELECT mode,count(*) FROM runs GROUP BY mode')},
                    'feedback': {r[0]: r[1] for r in db.execute('SELECT rating,count(*) FROM feedback GROUP BY rating')},
                    'ticket_status': {r[0]: r[1] for r in db.execute('SELECT status,count(*) FROM tickets GROUP BY status')},
                    'note': '仅本工作台实际记录；不代表模型准确率或业务提效'}

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'web/index.html')

    app.mount('/static', StaticFiles(directory=ROOT / 'web'), name='static')
    return app


app = create_app()
