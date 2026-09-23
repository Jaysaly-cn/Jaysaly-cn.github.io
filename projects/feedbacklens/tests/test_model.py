import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import model

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:True)
    with TestClient(create_app(tmp_path/'test.db')) as c:
        c.post('/api/imports',content='source_id,channel,text\na,app,导出按钮找不到，页面加载很慢。\n'.encode())
        yield c

def mock(monkeypatch,items):
    async def propose(source):return json.dumps({'suggestions':items},ensure_ascii=False)
    monkeypatch.setattr(model,'propose',propose)

def test_multi_issue_stays_draft(client,monkeypatch):
    mock(monkeypatch,[{'theme':'导出入口','kind':'problem','quote':'导出按钮找不到'},{'theme':'加载性能','kind':'problem','quote':'页面加载很慢'}])
    r=client.post('/api/suggestions',json={'source_id':'a'});assert r.status_code==201
    assert len(json.loads(r.json()['annotation_ids']))==2
    assert {a['state'] for a in client.get('/api/annotations').json()}=={'draft'}
    report=client.post('/api/reports',json={'title':'模型未审核','note':'模型草稿不可参与报告'}).json()
    assert report['confirmed_feedback']==0

def test_invalid_quote_rolls_back_all(client,monkeypatch):
    mock(monkeypatch,[{'theme':'入口问题','kind':'problem','quote':'导出按钮找不到'},{'theme':'加载问题','kind':'problem','quote':'页面加载非常缓慢'}])
    assert client.post('/api/suggestions',json={'source_id':'a'}).status_code==422
    assert client.get('/api/annotations').json()==[]
    record=client.get('/api/model-runs').json()[0]
    assert record['error']=='quote_mismatch' and record['raw']

def test_empty_output_is_explicit(client,monkeypatch):
    mock(monkeypatch,[])
    assert client.post('/api/suggestions',json={'source_id':'a'}).json()['annotation_ids']=='[]'

def test_failure_preserves_only_error_type(client,monkeypatch):
    async def propose(source):raise RuntimeError('private token')
    monkeypatch.setattr(model,'propose',propose)
    assert client.post('/api/suggestions',json={'source_id':'a'}).status_code==502
    record=client.get('/api/model-runs').json()[0]
    assert record['error']=='RuntimeError' and 'private token' not in json.dumps(record)


@pytest.mark.parametrize('source_id',['sarcasm','injection'])
def test_live_probe_replay_cannot_confirm_or_publish(tmp_path,monkeypatch,source_id):
    from pathlib import Path
    record=json.loads((Path(__file__).resolve().parents[1]/'artifacts/model-additional-probes.json').read_text(encoding='utf-8'))
    probe=next(p for p in record['probes'] if p['source_id']==source_id)
    async def propose(source):return probe['response']['raw']
    monkeypatch.setattr(model,'configured',lambda:True)
    monkeypatch.setattr(model,'propose',propose)
    with TestClient(create_app(tmp_path/'replay.db')) as c:
        assert c.post('/api/imports',content=f"source_id,channel,text\n{source_id},synthetic,{probe['text']}\n".encode()).status_code==201
        assert c.post('/api/suggestions',json={'source_id':source_id}).status_code==201
        assert all(a['state']=='draft' for a in c.get('/api/annotations').json())
        assert c.get('/api/reports').json()==[]
        report=c.post('/api/reports',json={'title':'回放审核门槛','note':'所有模型建议尚未由人确认'}).json()
        assert report['confirmed_feedback']==0 and report['evidence']==[]
