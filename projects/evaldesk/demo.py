"""Temporary single-process demo, adapted from the portfolio's FeedbackLens demo."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import time
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from app import create_app
import jobs
import store

TTL = 1800
MAX_SESSIONS = 12
COOKIE = 'ed_demo_session'
DIR_PATTERN = r'edemo-[0-9a-f]{24}-[0-9a-f]{32}'


def create_demo_app(root=None, clock=time.monotonic):
    folder = Path(root or store.ROOT / 'data/public-demo').resolve()
    folder.mkdir(parents=True, exist_ok=True)
    namespace = secrets.token_hex(12)
    current = ContextVar('evaldesk_demo_db')
    app = create_app(lambda: current.get())
    sessions, creations, starts = {}, deque(), deque()
    launch_lock = asyncio.Lock()
    app.state.demo_sessions = sessions

    def directories():
        return [p for p in folder.iterdir() if p.is_dir() and re.fullmatch(DIR_PATTERN, p.name) and not p.is_symlink()]

    def active(directory):
        db_path = directory / 'eval.sqlite3'
        if not db_path.exists():
            return False
        try:
            with store.connect(db_path) as db:
                db.execute('BEGIN IMMEDIATE')
                jobs.refresh(db, db_path)
                return bool(db.execute("SELECT 1 FROM jobs WHERE state IN ('starting','running','execution_unknown')").fetchone())
        except Exception:
            # Unreadable state cannot justify deleting a possibly active task.
            return True

    def remove(directory):
        if directory.resolve().parent != folder or not re.fullmatch(DIR_PATTERN, directory.name) or directory.is_symlink():
            raise RuntimeError('cleanup target is outside demo workspace')
        shutil.rmtree(directory)

    def clean():
        for sid, session in list(sessions.items()):
            if session['expires'] <= clock() and session['active'] == 0 and not active(session['directory']):
                remove(session['directory'])
                del sessions[sid]
        known = {s['directory'] for s in sessions.values()}
        for directory in directories():
            if directory not in known and time.time() - directory.stat().st_mtime > TTL + 300 and not active(directory):
                remove(directory)

    @asynccontextmanager
    async def lifespan(app):
        async def cleanup():
            while True:
                await asyncio.sleep(20)
                clean()
        task = asyncio.create_task(cleanup())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # Workers outlive the web server; never delete their directories here.
    app.router.lifespan_context = lifespan

    def seed(directory):
        directory.mkdir()
        path = directory / 'eval.sqlite3'
        store.initialize(path)
        jobs.initialize(path)
        store.import_run(store.ROOT / 'artifacts/engine-spike', path)
        with store.connect(path) as db:
            sample = json.loads((store.ROOT / 'samples/ticket-routing.json').read_text(encoding='utf-8'))
            store.save_suite(db, sample, '演示合成工单基线，可编辑或直接运行')
        return path

    @app.middleware('http')
    async def sandbox(request, call_next):
        route = request.url.path
        host = request.url.hostname or ''
        if host not in ('127.0.0.1', 'localhost', 'testserver') and host != os.getenv('ED_DEMO_HOST', ''):
            return JSONResponse({'detail': '演示域名未配置'}, 403)
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '不允许跨站访问'}, 403)
        if request.method not in ('GET', 'HEAD') and request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '不允许跨站写入'}, 403)
        if route in ('/docs', '/redoc', '/openapi.json'):
            return JSONResponse({'detail': '演示接口文档不开放'}, 404)
        if route == '/robots.txt':
            return PlainTextResponse('User-agent: *\nDisallow: /\n')
        if route == '/demo/status':
            return JSONResponse({'temporary': True, 'session_minutes': 30, 'jobs_per_session': 2, 'max_calls_per_job': 12})
        clean()
        stamp = clock()
        sid = request.cookies.get(COOKIE, '')
        session = sessions.get(sid)
        fresh = False
        if not session or session['expires'] <= stamp:
            if route != '/' or request.method not in ('GET', 'HEAD'):
                return JSONResponse({'detail': '演示会话已过期，请重新进入首页'}, 401)
            while creations and stamp - creations[0] > 3600:
                creations.popleft()
            if len(sessions) >= MAX_SESSIONS or len(directories()) >= MAX_SESSIONS or len(creations) >= 30:
                return JSONResponse({'detail': '演示席位暂满，请稍后再试'}, 429)
            directory = folder / f'edemo-{namespace}-{secrets.token_hex(16)}'
            database = seed(directory)
            session = {'directory': directory, 'path': database, 'expires': stamp + TTL, 'writes': 0, 'jobs': 0, 'active': 0}
            sid = secrets.token_urlsafe(32)
            sessions[sid] = session
            creations.append(stamp)
            fresh = True
        session['active'] += 1
        token = current.set(session['path'])
        request.scope['isolated_demo_session'] = True
        locked = False
        try:
            payload = None
            if request.method not in ('GET', 'HEAD'):
                if session['writes'] >= 60:
                    return JSONResponse({'detail': '本次会话写入额度已用完'}, 429)
                body = bytearray()
                async for part in request.stream():
                    if len(body) + len(part) > 40000:
                        return JSONResponse({'detail': '演示单次输入最多40KB'}, 413)
                    body.extend(part)
                request._body = bytes(body)
                session['writes'] += 1
            is_launch = request.method == 'POST' and route == '/api/jobs'
            if is_launch:
                try:
                    payload = json.loads(request._body)
                    if not isinstance(payload, dict):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    return JSONResponse({'detail': '无效任务请求'}, 422)
            if is_launch:
                await launch_lock.acquire()
                locked = True
                with store.connect(session['path']) as db:
                    key = payload.get('request_key')
                    if not isinstance(key, str):
                        return JSONResponse({'detail': '缺少请求标识'}, 422)
                    existing = db.execute('SELECT 1 FROM jobs WHERE request_key=?', (key,)).fetchone()
                    if not existing:
                        if not isinstance(payload.get('suite_id'), str) or type(payload.get('version')) is not int:
                            return JSONResponse({'detail': '测试集和版本无效'}, 422)
                        try:
                            suite = store.get_suite(db, payload['suite_id'], payload['version'])['suite']
                        except KeyError:
                            return JSONResponse({'detail': '测试集版本不存在'}, 404)
                        if len(suite['cases']) * len(suite['prompts']) > 12:
                            return JSONResponse({'detail': '公开演示每任务最多12次模型调用'}, 422)
                while starts and stamp - starts[0] > 3600:
                    starts.popleft()
                if not existing:
                    if session['jobs'] >= 2 or len(starts) >= 8:
                        return JSONResponse({'detail': '免费评测额度暂时用完，仍可编辑和复核已有结果'}, 429)
                    if any(active(p) for p in directories()):
                        return JSONResponse({'detail': '演示模型正处理其他任务，请稍后再试'}, 429)
                response = await call_next(request)
                if response.status_code == 202 and not existing:
                    session['jobs'] += 1
                    starts.append(stamp)
            elif route in ('/', '/suites.html', '/jobs.html') and request.method in ('GET', 'HEAD'):
                filename = 'index.html' if route == '/' else route[1:]
                html = (store.ROOT / 'web' / filename).read_text(encoding='utf-8')
                banner = '<aside class="demo-banner" role="note"><strong>临时公开演示 · 独立访客空间</strong><p>已放入合成测试集和真实模型示例结果。会话30分钟后失效，结束的任务随后清理；运行中或状态待核查的数据会延后清理。最多2个免费评测任务，每任务12次调用，全站串行。请仅使用合成资料，输入在演示服务器处理。请及时下载报告；重启后会话失效，入口依赖开发机在线。</p><a href="/">会话过期后重新进入 →</a></aside>'
                response = HTMLResponse(html.replace('<main>', '<main>' + banner, 1).replace('本地开发版', '临时访客版').replace('运行本地评测', '运行演示评测'))
            else:
                response = await call_next(request)
            if fresh:
                response.set_cookie(COOKIE, sid, max_age=TTL, httponly=True, secure=request.url.scheme == 'https', samesite='strict')
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
            return response
        finally:
            if locked:
                launch_lock.release()
            current.reset(token)
            session['active'] -= 1
    return app


app = create_demo_app()
