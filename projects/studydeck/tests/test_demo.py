from fastapi.testclient import TestClient
from app.demo import create_demo_app, COOKIE
from app import model

def enter(c):
    response=c.get('/')
    assert response.status_code==200 and '临时公开演示' in response.text
    assert 'secure' in response.headers['set-cookie'].lower()
    return c.get('/api/materials').json()[0]

def test_sessions_isolate_cards_export_and_mutations(tmp_path):
    with TestClient(create_demo_app(tmp_path/'sandbox'),base_url='https://testserver') as c:
        first=enter(c)
        card=c.post('/api/materials/'+first['id']+'/cards',json={'question':'命中时？','answer':'返回缓存内容','quote':'缓存命中时直接返回缓存内容。'}).json()
        cookie=c.cookies.get(COOKIE)
        c.cookies.clear();second=enter(c)
        assert first['id']!=second['id']
        assert c.get('/api/cards').json()==[]
        assert c.get('/api/export').json()['events']==[]
        assert c.post('/api/cards/'+card['id']+'/transition',json={'version':1,'action':'reject'}).status_code==404
        assert c.post('/api/materials/'+first['id']+'/cards',json={'question':'命中时？','answer':'返回缓存内容','quote':'缓存命中时直接返回缓存内容。'}).status_code==404
        c.cookies.clear();c.cookies.set(COOKIE,cookie,domain='testserver.local',path='/')
        assert c.get('/api/cards').json()[0]['id']==card['id']

def test_expiry(tmp_path):
    clock=[0]
    app=create_demo_app(tmp_path/'sandbox',clock=lambda:clock[0])
    unrelated=tmp_path/'keep.txt';unrelated.write_text('keep')
    with TestClient(app,base_url='https://testserver') as c:
        enter(c);paths=[s['path'] for s in app.state.demo_sessions.values()]
        clock[0]=1801
        assert c.get('/api/cards').status_code==401
        assert all(not p.exists() for p in paths)
        assert unrelated.read_text()=='keep'

def test_origin_host_body_and_cookie(tmp_path):
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        assert c.get('/api/cards',headers={'isolated_demo_session':'true'}).status_code==401
        enter(c)
        assert c.get('/api/cards',headers={'Origin':'https://evil.test'}).status_code==403
        assert c.get('/',headers={'Host':'evil.test'}).status_code==403
        assert c.post('/api/materials',content='x'*40001).status_code==413
        assert c.get('/openapi.json').status_code==404

def test_model_quota_preserves_manual_work(tmp_path,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:True)
    async def fail(source):raise ValueError('synthetic')
    monkeypatch.setattr(model,'propose',fail)
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        material=enter(c);url='/api/materials/'+material['id']
        for _ in range(3):assert c.post(url+'/generate').status_code==502
        assert c.post(url+'/generate').status_code==429
        assert c.post(url+'/cards',json={'question':'命中时？','answer':'返回缓存内容','quote':'缓存命中时直接返回缓存内容。'}).status_code==201

def test_capacity(tmp_path):
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        for _ in range(12):c.cookies.clear();enter(c)
        c.cookies.clear();assert c.get('/').status_code==429

def test_private_token_cannot_be_bypassed(tmp_path,monkeypatch):
    from app.main import create_app
    monkeypatch.setenv('STUDYDECK_ACCESS_TOKEN','secret')
    with TestClient(create_app(tmp_path/'private.sqlite3')) as c:
        assert c.get('/api/cards',headers={'isolated_demo_session':'true'}).status_code==401
