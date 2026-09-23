"""Adapted from portfolio FeedbackLens MIT demo. Single process, isolated databases."""
import asyncio
import os
import re
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlsplit
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from .main import create_app
from .db import initialize, connect, now
ROOT = Path(__file__).resolve().parents[1]

COOKIE = 'so_demo_session'
TTL = 1800
MAX_SESSIONS = 12
MAX_WRITES = 60


def create_demo_app(root=None, clock=time.monotonic):
    folder = Path(root or ROOT/'data/public-demo').resolve()
    folder.mkdir(parents=True,exist_ok=True)
    # New process = new secrets and namespace; stale sessions cannot reopen prior databases.
    namespace = secrets.token_hex(12)
    current_path = ContextVar('demo_database')
    app = create_app(lambda: current_path.get(), allow_model=False)
    sessions = {}
    creation_times = deque()
    app.state.demo_sessions = sessions

    def remove(session):
        for suffix in ('','-wal','-shm'):
            path = Path(str(session['path'])+suffix)
            if path.resolve().parent != folder:
                raise RuntimeError('Demo cleanup path escaped sandbox')
            path.unlink(missing_ok=True)

    def clean():
        for sid, session in list(sessions.items()):
            if session['expires']<=clock() and not session['active']:
                remove(session)
                del sessions[sid]
        active_paths={s['path'] for s in sessions.values()}
        # Recover files left by a crashed process, only inside this dedicated sandbox.
        for path in folder.glob('sodemo-*.sqlite3'):
            if re.fullmatch(r'sodemo-[0-9a-f]{24}-[0-9a-f]{32}\.sqlite3',path.name) and path not in active_paths:
                if time.time()-path.stat().st_mtime>TTL+300:
                    remove({'path':path})

    @asynccontextmanager
    async def lifespan(app):
        async def cleanup():
            while True:
                await asyncio.sleep(20)
                clean()
        task=asyncio.create_task(cleanup())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            for session in sessions.values():
                if not session['active']:
                    remove(session)
    app.router.lifespan_context = lifespan

    def seed(path):
        initialize(path)
        import json
        source=json.loads((ROOT/'examples/knowledge.json').read_text(encoding='utf-8'))
        with connect(path) as db:
            for doc in source:
                db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?)',(doc['id'],doc['title'],doc['content'],'合成示例 / 星河协作 SaaS',doc['audience'],1,now()))

    @app.middleware('http')
    async def sandbox(request,call_next):
        path=request.url.path
        host=request.url.hostname or ''
        allowed=os.getenv('SO_DEMO_HOST','')
        if host not in ('127.0.0.1','localhost','testserver') and host!=allowed:
            return JSONResponse({'detail':'演示域名未配置'},status_code=403)
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'不允许跨站访问'},status_code=403)
        if request.headers.get('sec-fetch-site')=='cross-site' and request.method not in ('GET','HEAD'):
            return JSONResponse({'detail':'不允许跨站写入'},status_code=403)
        if path=='/robots.txt':
            return PlainTextResponse('User-agent: *\nDisallow: /\n')
        if path=='/demo/status':
            return JSONResponse({'service':'SupportOps temporary demo','temporary':True,'session_minutes':TTL//60})
        if path in ('/docs','/redoc','/openapi.json'):
            return JSONResponse({'detail':'演示入口不开放接口文档'},status_code=404)
        if path.startswith('/static/'):
            return await call_next(request)
        clean()
        stamp=clock()
        sid=request.cookies.get(COOKIE,'')
        session=sessions.get(sid)
        fresh=False
        if not session or session['expires']<=stamp:
            if path!='/' or request.method not in ('GET','HEAD'):
                return JSONResponse({'detail':'演示会话已过期，请重新打开首页'},status_code=401)
            while creation_times and stamp-creation_times[0]>3600:
                creation_times.popleft()
            if len(sessions)>=MAX_SESSIONS or len(creation_times)>=30:
                return JSONResponse({'detail':'演示席位暂满，请稍后再试'},status_code=429)
            sid=secrets.token_urlsafe(32)
            database=folder/f'sodemo-{namespace}-{secrets.token_hex(16)}.sqlite3'
            seed(database)
            session={'path':database,'expires':stamp+TTL,'active':0,'writes':0}
            sessions[sid]=session;creation_times.append(stamp);fresh=True
        if request.method not in ('GET','HEAD'):
            if session['writes']>=MAX_WRITES:
                return JSONResponse({'detail':'本次演示写入额度已用完'},status_code=429)
            body=bytearray()
            async for part in request.stream():
                if len(body)+len(part)>40000:
                    return JSONResponse({'detail':'演示单次输入最多40KB'},status_code=413)
                body.extend(part)
            request._body=bytes(body)
            session['writes']+=1
        session['active']+=1
        context_token=current_path.set(session['path'])
        request.scope['isolated_demo_session']=True
        try:
            if path=='/':
                html=(ROOT/'web/index.html').read_text(encoding='utf-8')
                banner='<aside class="demo-banner" role="note"><strong>临时公开演示 · 每位访客独立空间</strong><p>已放入8篇合成知识。可检索问题、转人工工单、解决后审核发布知识，再复查旧问题。免费小模型答复实测未达标，演示仅提供证据检索。请仅使用合成资料，资料在演示服务器处理。会话30分钟后失效并清理，重启也会失效；最多60次写入，单次输入40KB。请及时导出回答证据。入口依赖开发机在线，尚非稳定服务。</p><a href="/">会话过期后重新进入 →</a></aside>'
                response=HTMLResponse(html.replace('<header>',banner+'<header>',1).replace('本地单人工作台','临时访客工作台'))
                response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
            else:
                response=await call_next(request)
            if fresh:
                response.set_cookie(COOKIE,sid,max_age=TTL,httponly=True,secure=request.url.scheme=='https',samesite='strict')
            response.headers['Cache-Control']='no-store'
            response.headers['X-Robots-Tag']='noindex, nofollow'
            response.headers['Referrer-Policy']='no-referrer'
            response.headers['X-Content-Type-Options']='nosniff'
            return response
        finally:
            current_path.reset(context_token)
            session['active']-=1
    return app


app=create_demo_app()
