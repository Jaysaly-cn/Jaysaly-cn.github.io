import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from fastapi.testclient import TestClient
from app.demo import create_demo_app, COOKIE
from app.main import create_app
from app import model


def enter(c):
    r=c.get('/')
    assert r.status_code==200 and '临时公开演示' in r.text
    assert 'id="auth"' not in r.text
    assert 'secure' in r.headers['set-cookie'].lower()
    return c.get('/api/meetings').json()[0]['id']


def candidate(c, mid):
    r=c.post(f'/api/meetings/{mid}/candidates',json={
        'title':'完成接口文档','quote':'小林：我明天完成接口文档。','owner':'小林','due_phrase':'明天'})
    assert r.status_code==201
    return r.json()


def test_isolated_meetings_actions_board_and_exports(tmp_path):
    with TestClient(create_demo_app(tmp_path/'sandbox'),base_url='https://testserver') as c:
        mid=enter(c);a=candidate(c,mid)
        r=c.post('/api/actions/'+a['id']+'/review',json={'version':1,'decision':'confirm',
            'title':a['title'],'owner':'小林','due_date':'2026-09-24','note':'合成承诺已经逐字核对'})
        assert r.status_code==200
        assert len(c.get('/api/board').json())==1
        assert 'BEGIN:VEVENT' in c.get('/api/export/ics').text
        cookie=c.cookies.get(COOKIE)
        c.cookies.clear();other=enter(c)
        assert other!=mid
        assert c.get('/api/meetings/'+mid).status_code==404
        assert c.post('/api/actions/'+a['id']+'/state',json={'version':2,'state':'in_progress','note':'跨访客请求必须失败'}).status_code==404
        assert c.get('/api/board').json()==[]
        assert c.get('/api/export/json').json()['actions']==[]
        assert 'BEGIN:VEVENT' not in c.get('/api/export/ics').text
        assert a['id'] not in c.get('/api/export/csv').text
        c.cookies.clear();c.cookies.set(COOKIE,cookie,domain='testserver.local',path='/')
        assert c.get('/api/board').json()[0]['id']==a['id']


def test_attempt_quota_success_reuse_and_manual_fallback(tmp_path,monkeypatch):
    monkeypatch.setenv('MA_MODEL','test-local')
    monkeypatch.setattr(model,'configured',lambda:True)
    calls=[]
    async def generate(*args):
        calls.append(1)
        if len(calls)>1:raise ValueError('synthetic failure')
        return []
    monkeypatch.setattr(model,'extract',generate)
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        mid=enter(c);url=f'/api/meetings/{mid}/extract'
        assert c.post(url,json={'segment':999}).status_code==422
        assert c.post('/api/meetings/missing/extract',json={}).status_code==404
        assert c.post(url,json={}).status_code==201
        assert c.post(url,json={}).json()['reused'] and len(calls)==1
        for _ in range(2):assert c.post(url,json={'rerun':True}).status_code==502
        assert c.post(url,json={'rerun':True}).status_code==429 and len(calls)==3
        assert c.post(url,json={}).json()['reused'] and len(calls)==3
        candidate(c,mid)
        assert len(c.get('/api/meetings/'+mid).json()['runs'])==3
        c.cookies.clear();other=enter(c)
        assert c.get('/api/meetings/'+other).json()['runs']==[]


def test_expiry_retains_inflight_request_then_cleans(tmp_path,monkeypatch):
    clock=[0];started=threading.Event();release=threading.Event()
    monkeypatch.setenv('MA_MODEL','test-local')
    monkeypatch.setattr(model,'configured',lambda:True)
    async def slow(*args):
        started.set()
        while not release.is_set():await asyncio.sleep(.01)
        return []
    monkeypatch.setattr(model,'extract',slow)
    app=create_demo_app(tmp_path/'sandbox',clock=lambda:clock[0])
    with TestClient(app,base_url='https://testserver') as c,ThreadPoolExecutor(max_workers=1) as pool:
        mid=enter(c);path=next(iter(app.state.demo_sessions.values()))['path']
        future=pool.submit(c.post,f'/api/meetings/{mid}/extract',json={})
        try:
            assert started.wait(3)
            clock[0]=1801
            assert c.get('/api/meetings').status_code==401
            assert path.exists()
        finally:release.set()
        assert future.result(timeout=5).status_code==201
        assert c.get('/api/meetings').status_code==401
        assert not path.exists()


def test_capacity_origin_size_and_private_header_protection(tmp_path,monkeypatch):
    with TestClient(create_demo_app(tmp_path/'sandbox'),base_url='https://testserver') as c:
        assert c.get('/api/meetings',headers={'isolated_demo_session':'true'}).status_code==401
        enter(c)
        assert c.get('/api/meetings',headers={'Origin':'https://evil.test'}).status_code==403
        assert c.get('/',headers={'Host':'evil.test'}).status_code==403
        assert c.post('/api/meetings',content=b'x'*40001).status_code==413
        assert c.get('/openapi.json').status_code==404
        for _ in range(11):c.cookies.clear();enter(c)
        c.cookies.clear();assert c.get('/').status_code==429
    monkeypatch.setenv('MEETINGACTIONS_ACCESS_TOKEN','private-secret')
    with TestClient(create_app(tmp_path/'private.db')) as c:
        assert c.get('/api/meetings',headers={'isolated_demo_session':'true'}).status_code==401


def test_global_model_budget_across_sessions(tmp_path,monkeypatch):
    monkeypatch.setenv('MA_MODEL','test-local')
    monkeypatch.setattr(model,'configured',lambda:True)
    async def fail(*args):raise ValueError('synthetic failure')
    monkeypatch.setattr(model,'extract',fail)
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        for _ in range(8):
            c.cookies.clear();mid=enter(c)
            for _ in range(3):assert c.post(f'/api/meetings/{mid}/extract',json={}).status_code==502
        c.cookies.clear();mid=enter(c)
        assert c.post(f'/api/meetings/{mid}/extract',json={}).status_code==429
