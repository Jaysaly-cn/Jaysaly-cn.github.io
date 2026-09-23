import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import model

@pytest.mark.parametrize('raw', ['not JSON', '{"cards":[]}'])
def test_bad_schema_recorded_without_cards(tmp_path,monkeypatch,raw):
    monkeypatch.setattr(model,'configured',lambda:True)
    async def propose(source):return raw
    monkeypatch.setattr(model,'propose',propose)
    path=tmp_path/'history.db'
    with TestClient(create_app(path)) as c:
        m=c.post('/api/materials',json={'title':'合成资料','body':'只有幂等请求才可在指定条件下重试。'}).json()
        assert c.post('/api/materials/'+m['id']+'/generate').status_code==502
        assert c.get('/api/cards').json()==[]
        record=c.get('/api/generations').json()[0]
        assert record['raw']==raw and json.loads(record['issues'])[0]['kind']=='schema'
    with TestClient(create_app(path)) as c:
        assert c.get('/api/export').json()['generations'][0]==record

def test_provider_error_does_not_expose_message(tmp_path,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:True)
    async def propose(source):raise RuntimeError('secret credential should not be retained')
    monkeypatch.setattr(model,'propose',propose)
    with TestClient(create_app(tmp_path/'history.db')) as c:
        m=c.post('/api/materials',json={'title':'合成资料','body':'只有幂等请求才可在指定条件下重试。'}).json()
        assert c.post('/api/materials/'+m['id']+'/generate').status_code==502
        record=c.get('/api/generations').json()[0]
        assert record['raw'] is None and 'secret' not in json.dumps(record)
        assert 'RuntimeError' in record['issues']

def test_history_capacity_before_call(tmp_path,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:True)
    async def propose(source):pytest.fail('Must reject before a model call')
    monkeypatch.setattr(model,'propose',propose)
    path=tmp_path/'history.db'
    with TestClient(create_app(path)) as c:
        m=c.post('/api/materials',json={'title':'合成资料','body':'只有幂等请求才可在指定条件下重试。'}).json()
        conn=sqlite3.connect(path)
        try:
            with conn:conn.executemany('INSERT INTO generations VALUES(?,?,?,?,?,?,?)',[(str(i),m['id'],'failed',None,'[]','[]','2026-09-23') for i in range(100)])
        finally:conn.close()
        assert c.post('/api/materials/'+m['id']+'/generate').status_code==409
