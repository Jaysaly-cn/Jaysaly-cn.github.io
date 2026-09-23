import pytest
from fastapi.testclient import TestClient
from app.main import create_app

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'test.db')) as c: yield c

def seed(c):
    m=c.post('/api/materials',json={'title':'缓存','body':'缓存命中时直接返回缓存内容，未命中时访问数据源。'}).json()
    draft={'question':'缓存未命中时做什么？','answer':'访问数据源。','quote':'未命中时访问数据源。'}
    card=c.post('/api/materials/'+m['id']+'/cards',json=draft).json()
    return m,draft,card

def test_review_persistence_and_duplicate(client):
    _,draft,card=seed(client)
    assert client.get('/api/due').json()==[]
    approved=client.post('/api/cards/'+card['id']+'/approve',json={**draft,'version':1,'checked':True})
    assert approved.status_code==200
    assert len(client.get('/api/due').json())==1
    url='/api/cards/'+card['id']+'/review'
    result=client.post(url,json={'version':2,'rating':3})
    assert result.status_code==200
    assert result.json()['version']==3
    assert client.post(url,json={'version':2,'rating':3}).status_code==409
    assert client.post(url,json={'version':3,'rating':3}).status_code==409
    events=client.get('/api/export').json()['events']
    assert [e['action'] for e in events]==['created','approved','reviewed']
    assert 'review_log' in events[-1]['snapshot']

def test_quote_and_approval_guard(client):
    m,draft,card=seed(client)
    assert client.post('/api/materials/'+m['id']+'/cards',json={**draft,'quote':'原文不存在'}).status_code==422
    assert client.post('/api/cards/'+card['id']+'/approve',json={**draft,'version':1,'checked':False}).status_code==422
    assert client.post('/api/cards/'+card['id']+'/review',json={'version':1,'rating':3}).status_code==409

def test_generation_atomic(client,monkeypatch):
    m,draft,_=seed(client)
    import json
    from app import model
    monkeypatch.setattr(model,'configured',lambda:True)
    async def propose(source):return json.dumps({'cards':[draft,{**draft,'quote':'无效引用'}]})
    monkeypatch.setattr(model,'propose',propose)
    assert client.post('/api/materials/'+m['id']+'/generate').status_code==422
    assert len(client.get('/api/cards').json())==1

def test_reopen(tmp_path):
    path=tmp_path/'persistent.db'
    with TestClient(create_app(path)) as c:seed(c)
    with TestClient(create_app(path)) as c:assert len(c.get('/api/cards').json())==1

@pytest.mark.parametrize('rating',[0,5])
def test_invalid_rating(client,rating):
    _,_,card=seed(client)
    assert client.post('/api/cards/'+card['id']+'/review',json={'version':1,'rating':rating}).status_code==422

def test_origin_guard(client):
    assert client.get('/api/cards',headers={'Origin':'https://attacker.test'}).status_code==403

def test_pause_resume_preserves_schedule(client):
    _,draft,card=seed(client)
    base='/api/cards/'+card['id']
    active=client.post(base+'/approve',json={**draft,'version':1,'checked':True}).json()
    paused=client.post(base+'/transition',json={'version':2,'action':'pause'}).json()
    assert paused['fsrs']==active['fsrs'] and paused['due']==active['due']
    assert client.get('/api/due').json()==[]
    assert client.post(base+'/review',json={'version':3,'rating':3}).status_code==409
    assert client.post(base+'/transition',json={'version':2,'action':'resume'}).status_code==409
    resumed=client.post(base+'/transition',json={'version':3,'action':'resume'}).json()
    assert resumed['fsrs']==active['fsrs']
    assert len(client.get('/api/due').json())==1
    assert [e['action'] for e in client.get('/api/export').json()['events']][-2:]==['pause','resume']

def test_reject_restore(client):
    _,draft,card=seed(client)
    base='/api/cards/'+card['id']
    assert client.post(base+'/transition',json={'version':1,'action':'pause'}).status_code==409
    assert client.post(base+'/transition',json={'version':1,'action':'reject'}).status_code==200
    assert client.post(base+'/approve',json={**draft,'version':2,'checked':True}).status_code==409
    assert client.post(base+'/transition',json={'version':2,'action':'restore'}).json()['state']=='draft'
    assert client.post(base+'/approve',json={**draft,'version':3,'checked':True}).status_code==200
