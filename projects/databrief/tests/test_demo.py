import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from app.demo import create_demo_app,COOKIE
from app import model


@pytest.fixture
def demo(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABRIEF_DB',str(tmp_path/'private.sqlite3'))
    monkeypatch.setenv('DATABRIEF_ACCESS_TOKEN','private-secret')
    monkeypatch.setenv('DBR_DEMO_HOST','demo.example')
    app=create_demo_app(tmp_path/'sandbox')
    with TestClient(app,base_url='https://demo.example') as client:yield client,app,tmp_path


def enter(client):
    r=client.get('/')
    assert r.status_code==200 and '临时公开演示' in r.text
    assert 'httponly' in r.headers['set-cookie'].lower() and 'secure' in r.headers['set-cookie'].lower()
    return client.get('/api/datasets').json()[0]['id']


def run(client,did):
    preview=client.post(f'/api/datasets/{did}/query-preview',json={'aggregate':'sum','metric':'c3'}).json()
    return client.post(f'/api/datasets/{did}/runs',json={'sql':preview['sql'],'note':'核对合成数据金额列合计','reviewed':True}).json()


def test_visitors_cannot_read_each_others_datasets_results_or_exports(demo):
    client,app,root=demo
    first=enter(client);cookie=client.cookies.get(COOKIE);result=run(client,first)
    assert result['rows']==[[60.0]]
    response=client.get('/api/runs/'+result['id']+'/bundle')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:assert 'result.csv' in archive.namelist()
    client.cookies.clear();second=enter(client)
    assert first!=second
    for path in [f'/api/datasets/{first}',f'/api/runs/{result["id"]}',f'/api/runs/{result["id"]}/bundle']:
        assert client.get(path).status_code==404
    assert not (root/'private.sqlite3').exists()
    client.cookies.clear();client.cookies.set(COOKIE,cookie,domain='demo.example',path='/')
    assert client.get('/api/datasets/'+first).status_code==200
    assert client.get('/api/datasets/'+second).status_code==404


def test_demo_host_origin_and_forged_header_do_not_grant_access(demo):
    client,_,_=demo
    assert client.get('/api/datasets',headers={'isolated_demo_session':'true'}).status_code==401
    enter(client)
    assert client.get('/api/datasets',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/datasets?name=x',content='n\n1',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert client.get('/',headers={'Host':'evil.example'}).status_code==403
    assert client.get('/openapi.json').status_code==404
    assert client.post('/api/datasets?name=x',content='x'*40001).status_code==413
    client.cookies.clear();client.cookies.set(COOKIE,'forged')
    assert client.get('/api/datasets').status_code==401


def test_expiration_cleans_only_sandbox_files(tmp_path):
    tick=[0];app=create_demo_app(tmp_path/'sandbox',clock=lambda:tick[0])
    unrelated=tmp_path/'keep.txt';unrelated.write_text('keep')
    with TestClient(app,base_url='https://testserver') as client:
        enter(client);paths=[s['path'] for s in app.state.demo_sessions.values()]
        tick[0]=1801
        assert client.get('/api/datasets').status_code==401
        assert all(not p.exists() for p in paths) and unrelated.read_text()=='keep'


def test_capacity_is_bounded(demo):
    client,app,_=demo
    for _ in range(12):client.cookies.clear();enter(client)
    client.cookies.clear()
    assert client.get('/').status_code==429 and len(app.state.demo_sessions)==12


def test_model_quota_does_not_consume_history_reads_or_block_visual_queries(demo,monkeypatch):
    client,_,_=demo;did=enter(client)
    monkeypatch.setattr(model,'configured',lambda:True)
    async def fail(*args):raise ValueError('synthetic failure')
    monkeypatch.setattr(model,'propose',fail)
    for _ in range(5):assert client.get(f'/api/datasets/{did}/proposals').status_code==200
    for _ in range(3):assert client.post(f'/api/datasets/{did}/proposals',json={'question':'合计多少'}).status_code==502
    assert client.post(f'/api/datasets/{did}/proposals',json={'question':'合计多少'}).status_code==429
    assert run(client,did)['rows']==[[60.0]]


def test_private_app_cannot_enable_demo_by_header(tmp_path,monkeypatch):
    from app.main import create_app
    monkeypatch.setenv('DATABRIEF_ACCESS_TOKEN','private-secret')
    with TestClient(create_app(tmp_path/'private.sqlite3')) as client:
        assert client.get('/api/datasets',headers={'isolated_demo_session':'true'}).status_code==401
