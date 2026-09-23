import json
import csv
import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import model
from test_data import RAW


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.delenv('DATABRIEF_ACCESS_TOKEN',raising=False)
    monkeypatch.delenv('DBR_MODEL',raising=False)
    with TestClient(create_app(tmp_path/'api.db')) as c:yield c


def upload(c,raw=RAW):
    r=c.post('/api/datasets?name=synthetic',content=raw);assert r.status_code==201
    return r.json()['id']


def proposal(c,monkeypatch,did,sql='SELECT sum(c3) AS amount FROM data'):
    monkeypatch.setattr(model,'configured',lambda:True)
    async def fake(source,question):return json.dumps({'sql':sql,'explanation':'按金额列求和','limitations':'需核对单位与空值'})
    monkeypatch.setattr(model,'propose',fake)
    r=c.post(f'/api/datasets/{did}/proposals',json={'question':'金额合计多少？'})
    assert r.status_code==201
    return r.json()


def test_proposal_does_not_run_and_reviewed_edit_is_traced(client,monkeypatch):
    did=upload(client);p=proposal(client,monkeypatch,did)
    assert client.get(f'/api/datasets/{did}/runs').json()==[]
    payload={'sql':'SELECT round(sum(c3),2) AS amount FROM data','proposal_id':p['id'],'note':'核对金额列且保留两位小数','reviewed':True}
    r=client.post(f'/api/datasets/{did}/runs',json={**payload,'reviewed':False});assert r.status_code==422
    result=client.post(f'/api/datasets/{did}/runs',json=payload).json()
    assert result['rows']==[[60.0]] and result['review_context']['proposed_sql']==p['sql']
    old=client.get('/api/runs/'+result['id']).json()
    client.post(f'/api/datasets/{did}/runs',json={**payload,'sql':'SELECT count(*) FROM data'})
    assert client.get('/api/runs/'+result['id']).json()==old


def test_proposal_cannot_cross_datasets(client,monkeypatch):
    a=upload(client);b=upload(client,RAW.replace(b'19.5',b'20.5'));p=proposal(client,monkeypatch,a)
    assert client.post(f'/api/datasets/{b}/runs',json={'sql':p['sql'],'proposal_id':p['id'],'note':'不能混用其他数据集的提议','reviewed':True}).status_code==404


def test_malicious_model_sql_not_executed_and_executor_blocks(client,monkeypatch):
    did=upload(client);p=proposal(client,monkeypatch,did,'DROP TABLE data')
    assert client.get(f'/api/datasets/{did}/runs').json()==[]
    result=client.post(f'/api/datasets/{did}/runs',json={'sql':p['sql'],'proposal_id':p['id'],'note':'测试执行层禁止写操作','reviewed':True}).json()
    assert result['state']=='failed'
    assert client.get(f'/api/datasets/{did}').json()['row_count']==3


def test_invalid_model_raw_preserved(client,monkeypatch):
    did=upload(client);monkeypatch.setattr(model,'configured',lambda:True)
    async def bad(*args):return '{broken'
    monkeypatch.setattr(model,'propose',bad)
    assert client.post(f'/api/datasets/{did}/proposals',json={'question':'金额？'}).status_code==502
    row=client.get(f'/api/datasets/{did}/proposals').json()[0]
    assert row['state']=='failed' and row['raw']=='{broken'
    assert client.get(f'/api/datasets/{did}/runs').json()==[]


def test_model_off_manual_query_and_access_guards(client,monkeypatch):
    did=upload(client)
    assert client.post(f'/api/datasets/{did}/proposals',json={'question':'金额？'}).status_code==503
    assert client.post(f'/api/datasets/{did}/runs',json={'sql':'SELECT count(*) FROM data','note':'核对全数据集总行数','reviewed':True}).json()['rows']==[[3]]
    assert client.get('/api/datasets',headers={'Origin':'https://evil.invalid'}).status_code==403
    monkeypatch.setenv('DATABRIEF_ACCESS_TOKEN','synthetic')
    assert client.get('/api/datasets').status_code==401
    assert client.get('/api/datasets',headers={'Authorization':'Bearer synthetic'}).status_code==200


def test_workspace_and_sample_routes(client):
    page=client.get('/')
    assert page.status_code==200 and 'DataBrief' in page.text
    assert "script-src 'self'" in page.headers['content-security-policy']
    assert client.get('/static/app.js').status_code==200
    sample=client.get('/sample.csv')
    assert sample.status_code==200
    did=upload(client,sample.content)
    source=client.get('/api/datasets/'+did).json()
    assert source['row_count']==3 and len(source['preview'])==3 and 'rows' not in source


def test_visual_preview_is_model_free_and_requires_separate_review(client):
    did=upload(client)
    p=client.post(f'/api/datasets/{did}/query-preview',json={'aggregate':'avg','metric':'c2','nulls':'zero'})
    assert p.status_code==200
    assert client.get(f'/api/datasets/{did}/runs').json()==[]
    payload={'sql':p.json()['sql'],'note':'空白订单数按零计算','reviewed':False}
    assert client.post(f'/api/datasets/{did}/runs',json=payload).status_code==422
    r=client.post(f'/api/datasets/{did}/runs',json={**payload,'reviewed':True}).json()
    assert r['rows']==[[5/3]]
    assert client.post(f'/api/datasets/{did}/query-preview',json={'aggregate':'sum','metric':'c99'}).status_code==422
    assert client.post(f'/api/datasets/{did}/query-preview',json={'group':'c1; DROP TABLE data'}).status_code==422
    assert client.post('/api/datasets/missing/query-preview',json={}).status_code==404


def test_result_bundle_is_a_stored_snapshot_not_a_new_query(client):
    did=upload(client)
    payload={'sql':'SELECT c1, c2, c4 FROM data ORDER BY c4','note':'核对列顺序和空值，保留编码','reviewed':True}
    run=client.post(f'/api/datasets/{did}/runs',json=payload).json()
    saved=client.get('/api/runs/'+run['id']).json()
    client.post(f'/api/datasets/{did}/runs',json={**payload,'sql':'SELECT count(*) FROM data'})
    response=client.get('/api/runs/'+run['id']+'/bundle')
    assert response.status_code==200 and response.headers['content-type']=='application/zip'
    assert response.headers['cache-control']=='no-store'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist())=={'snapshot.json','result.csv','query.sql','README.txt'}
        assert json.loads(archive.read('snapshot.json'))==saved
        rows=list(csv.reader(io.StringIO(archive.read('result.csv').decode('utf-8-sig'))))
        assert rows==[['c1','c2','c4'],['搜索','2','001'],['社交','3','002'],['搜索','\\N','003']]
        assert archive.read('query.sql').decode()==payload['sql']
    assert len(client.get(f'/api/datasets/{did}/runs').json())==2
    assert client.get('/api/runs/missing/bundle').status_code==404


def test_binary_result_is_recorded_as_failure_and_not_exported_as_table(client):
    did=upload(client)
    run=client.post(f'/api/datasets/{did}/runs',json={'sql':"SELECT X'4142' AS binary",'note':'测试二进制结果拒绝且留存','reviewed':True}).json()
    assert run['state']=='failed' and '二进制' in run['error']
    assert client.get('/api/runs/'+run['id']).json()['result']['state']=='failed'
    assert client.get('/api/runs/'+run['id']+'/bundle').status_code==422
