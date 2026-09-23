import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from fastapi.testclient import TestClient
from app.demo import create_demo_app, COOKIE
from app.main import create_app
from app import model
from test_workflow import COPY


def enter(c):
    r=c.get('/')
    assert r.status_code==200 and '实验性小模型' in r.text and 'id="auth"' not in r.text
    assert 'secure' in r.headers['set-cookie'].lower()
    return c.get('/api/campaigns').json()[0]['id']


def test_visitors_cannot_read_revise_review_compare_or_export_others(tmp_path):
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        cid=enter(c)
        old=c.post(f'/api/campaigns/{cid}/drafts',json=COPY).json()
        assert c.post('/api/revisions/'+old['id']+'/review',json={
            'state':'approved','version':1,'note':'已逐句核对合成事实','facts_checked':True}).status_code==200
        snapshot=c.post(f'/api/campaigns/{cid}/exports').json()
        before=c.get('/api/exports/'+snapshot['id']+'?format=markdown').content
        revision={k:v for k,v in COPY.items() if k!='channel'}
        revision.update(expected_revision=old['id'],title='修订标题')
        new=c.post('/api/drafts/'+old['draft_id']+'/revisions',json=revision).json()
        assert c.get('/api/exports/'+snapshot['id']+'?format=markdown').content==before
        cookie=c.cookies.get(COOKIE)
        c.cookies.clear(); other=enter(c)
        assert cid!=other
        assert c.get('/api/campaigns/'+cid).status_code==404
        assert c.post('/api/drafts/'+old['draft_id']+'/revisions',json=revision).status_code==404
        assert c.post('/api/revisions/'+new['id']+'/review',json={
            'state':'approved','version':1,'note':'cross visitor probe','facts_checked':True}).status_code==404
        assert c.get('/api/drafts/'+old['draft_id']+'/compare',params={'before':old['id'],'after':new['id']}).status_code==404
        for suffix in ('','?format=markdown'):
            assert c.get('/api/exports/'+snapshot['id']+suffix).status_code==404
        assert c.get('/api/campaigns/'+other).json()['drafts']==[]
        c.cookies.clear();c.cookies.set(COOKIE,cookie,domain='testserver.local',path='/')
        assert c.get('/api/exports/'+snapshot['id']+'?format=markdown').content==before


def test_model_attempts_count_failures_but_manual_work_remains(tmp_path,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:True)
    calls=[]
    async def generated(*args):
        calls.append(1)
        if len(calls)>1:raise ValueError('synthetic failure')
        return {k:v for k,v in COPY.items() if k!='channel'},'test-local'
    monkeypatch.setattr(model,'generate',generated)
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        cid=enter(c);url=f'/api/campaigns/{cid}/generate'
        assert c.post('/api/campaigns/missing/generate',json={'channel':'邮件'}).status_code==404
        assert c.post(url,json={'channel':'invalid'}).status_code==422
        assert c.post(url,json={'channel':'邮件'}).status_code==201
        for _ in range(2):assert c.post(url,json={'channel':'邮件'}).status_code==502
        assert c.post(url,json={'channel':'邮件'}).status_code==429 and len(calls)==3
        assert c.post(f'/api/campaigns/{cid}/drafts',json=COPY).status_code==201
        detail=c.get('/api/campaigns/'+cid).json()
        assert len(detail['drafts'])==2
        assert sum(e['action']=='generation_failed' for e in detail['events'])==2


def test_expired_space_kept_until_active_generation_finishes(tmp_path,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:True)
    clock=[0];started=threading.Event();release=threading.Event()
    async def slow(*args):
        started.set()
        while not release.is_set():await asyncio.sleep(.01)
        return {k:v for k,v in COPY.items() if k!='channel'},'test-local'
    monkeypatch.setattr(model,'generate',slow)
    app=create_demo_app(tmp_path,clock=lambda:clock[0])
    with TestClient(app,base_url='https://testserver') as c,ThreadPoolExecutor(max_workers=1) as pool:
        cid=enter(c);path=next(iter(app.state.demo_sessions.values()))['path']
        future=pool.submit(c.post,f'/api/campaigns/{cid}/generate',json={'channel':'邮件'})
        try:
            assert started.wait(3)
            clock[0]=1801
            assert c.get('/api/campaigns').status_code==401 and path.exists()
        finally:release.set()
        assert future.result(timeout=5).status_code==201
        assert c.get('/api/campaigns').status_code==401 and not path.exists()


def test_host_origin_body_capacity_and_private_access(tmp_path,monkeypatch):
    with TestClient(create_demo_app(tmp_path/'demo'),base_url='https://testserver') as c:
        assert c.get('/api/campaigns',headers={'isolated_demo_session':'true'}).status_code==401
        enter(c)
        assert c.get('/',headers={'Host':'evil.test'}).status_code==403
        assert c.post('/api/campaigns',json={},headers={'Origin':'https://evil.test'}).status_code==403
        assert c.post('/api/campaigns',content='x'*40001).status_code==413
        assert c.get('/docs').status_code==404
        for _ in range(11):c.cookies.clear();enter(c)
        c.cookies.clear();assert c.get('/').status_code==429
    monkeypatch.setenv('CONTENTBENCH_ACCESS_TOKEN','private-secret')
    with TestClient(create_app(tmp_path/'private.sqlite3')) as c:
        assert c.get('/api/campaigns',headers={'isolated_demo_session':'true'}).status_code==401


def test_global_attempt_budget(tmp_path,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:True)
    async def fail(*args):raise ValueError('synthetic failure')
    monkeypatch.setattr(model,'generate',fail)
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        for _ in range(8):
            c.cookies.clear();cid=enter(c)
            for _ in range(3):assert c.post(f'/api/campaigns/{cid}/generate',json={'channel':'邮件'}).status_code==502
        c.cookies.clear();cid=enter(c)
        assert c.post(f'/api/campaigns/{cid}/generate',json={'channel':'邮件'}).status_code==429
