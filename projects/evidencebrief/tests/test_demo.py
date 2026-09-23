import httpx
import pytest
from fastapi.testclient import TestClient
from app.demo import create_demo_app,COOKIE
from app import model


@pytest.fixture
def demo(tmp_path,monkeypatch):
    monkeypatch.setenv('EVIDENCEBRIEF_DB',str(tmp_path/'private.sqlite3'))
    monkeypatch.setenv('EVIDENCEBRIEF_ACCESS_TOKEN','private-workspace-secret')
    monkeypatch.setenv('EB_DEMO_HOST','demo.example')
    app=create_demo_app(tmp_path/'sandbox')
    with TestClient(app,base_url='https://demo.example') as c:
        yield c,app,tmp_path


def enter(c):
    r=c.get('/')
    assert r.status_code==200 and '临时公开演示' in r.text
    assert 'httponly' in r.headers['set-cookie'].lower() and 'secure' in r.headers['set-cookie'].lower()
    return c.get('/api/projects').json()[0]


def test_demo_isolation_and_private_db_never_opened(demo):
    c,app,root=demo
    first=enter(c);cookie=c.cookies.get(COOKIE)
    source=c.get('/api/projects/'+first['id']).json()['sources'][0]
    c.cookies.clear();second=enter(c)
    assert first['id']!=second['id']
    assert c.get('/api/projects/'+first['id']).status_code==404
    assert not (root/'private.sqlite3').exists()
    c.cookies.clear();c.cookies.set(COOKIE,cookie,domain='demo.example',path='/')
    assert c.get('/api/projects/'+first['id']).status_code==200
    assert c.get('/api/projects/'+second['id']).status_code==404


def test_demo_external_fetch_origin_host_and_cookie_guards(demo):
    c,app,root=demo
    assert c.get('/api/projects',headers={'isolated_demo_session':'true'}).status_code==401
    enter(c)
    assert c.post('/api/projects/fake/fetch',json={'entity':'Alpha','url':'https://example.com'}).status_code==403
    assert c.get('/api/projects',headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/projects',headers={'Sec-Fetch-Site':'cross-site'},json={}).status_code==403
    assert c.get('/',headers={'Host':'evil.example'}).status_code==403
    assert c.get('/openapi.json').status_code==404
    assert c.post('/api/projects',content='x'*40001).status_code==413
    c.cookies.clear();c.cookies.set(COOKIE,'forged')
    assert c.get('/api/projects').status_code==401


def test_demo_expiration_deletes_only_own_session_files(tmp_path,monkeypatch):
    monkeypatch.delenv('EVIDENCEBRIEF_ACCESS_TOKEN',raising=False)
    tick=[0];app=create_demo_app(tmp_path/'sandbox',clock=lambda:tick[0])
    unrelated=tmp_path/'keep.txt';unrelated.write_text('keep')
    with TestClient(app,base_url='https://testserver') as c:
        enter(c);paths=[s['path'] for s in app.state.demo_sessions.values()]
        tick[0]=1801
        assert c.get('/api/projects').status_code==401
        assert all(not p.exists() for p in paths)
        assert unrelated.read_text()=='keep'


def test_demo_capacity_is_bounded(demo):
    c,app,_=demo
    for _ in range(12):
        c.cookies.clear();enter(c)
    c.cookies.clear()
    assert c.get('/').status_code==429
    assert len(app.state.demo_sessions)==12


def test_demo_model_quota_preserves_manual_workflow(demo,monkeypatch):
    c,app,_=demo;project=enter(c)
    monkeypatch.setattr(model,'configured',lambda:True)
    monkeypatch.setenv('EB_MODEL','synthetic')
    async def fail(*args):raise ValueError('synthetic model failure')
    monkeypatch.setattr(model,'suggest',fail)
    source=c.get('/api/projects/'+project['id']).json()['sources'][0]
    endpoint=f'/api/projects/{project["id"]}/sources/{source["id"]}/suggest'
    for _ in range(3):assert c.post(endpoint).status_code==502
    assert c.post(endpoint).status_code==429
    assert c.post(f'/api/projects/{project["id"]}/claims',json={'source_id':source['id'],'dimension':'价格',
        'statement':'团队版每月19元','quote':'Alpha 团队版每月 19 元'}).status_code==201
