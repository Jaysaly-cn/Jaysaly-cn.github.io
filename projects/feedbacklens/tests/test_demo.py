import json
from fastapi.testclient import TestClient
from app.demo import create_demo_app, COOKIE
from app import model


def enter(c):
    response=c.get('/')
    assert response.status_code==200 and '临时公开演示' in response.text
    assert 'secure' in response.headers['set-cookie'].lower()
    assert len(c.get('/api/feedback').json())==4


def test_all_records_and_imports_are_isolated(tmp_path):
    with TestClient(create_demo_app(tmp_path/'sandbox'),base_url='https://testserver') as c:
        enter(c)
        a=c.post('/api/annotations',json={'source_id':'s1','theme':'离线导出','kind':'request','quote':'希望增加离线导出功能'}).json()
        assert c.post('/api/annotations/'+a['id']+'/review',json={'version':1,'decision':'confirmed','note':'核对合成反馈的引用'}).status_code==200
        assert c.post('/api/duplicates',json={'source_id':'s2','target_id':'s1','version':0,'note':'合成数据重复判断验收'}).status_code==200
        report=c.post('/api/reports',json={'title':'访客独立报告','note':'合成验收用于隔离检查'}).json()
        assert c.post('/api/imports',content='source_id,channel,text\nprivate,web,首位访客独有的反馈\n'.encode()).status_code==201
        cookie=c.cookies.get(COOKIE)
        c.cookies.clear();enter(c)
        for endpoint in ['annotations','duplicates','reports','model-runs','duplicates/s2/history']:
            assert c.get('/api/'+endpoint).json()==[]
        assert c.get('/api/reports/'+report['id']).status_code==404
        assert c.post('/api/annotations/'+a['id']+'/review',json={'version':2,'decision':'rejected','note':'测试跨访客写入应拒绝'}).status_code==404
        assert not any(r['source_id']=='private' for r in c.get('/api/feedback').json())
        c.cookies.clear();c.cookies.set(COOKIE,cookie,domain='testserver.local',path='/')
        assert c.get('/api/reports/'+report['id']).json()==report
        assert len(c.get('/api/feedback').json())==5


def test_expiry_cleanup_and_capacity(tmp_path):
    clock=[0];app=create_demo_app(tmp_path/'sandbox',clock=lambda:clock[0])
    keep=tmp_path/'keep.txt';keep.write_text('keep')
    with TestClient(app,base_url='https://testserver') as c:
        for _ in range(12):c.cookies.clear();enter(c)
        paths=[s['path'] for s in app.state.demo_sessions.values()]
        c.cookies.clear();assert c.get('/').status_code==429
        clock[0]=1801
        assert c.get('/api/feedback').status_code==401
        assert all(not p.exists() for p in paths)
        assert keep.read_text()=='keep'
        enter(c)


def test_origin_host_size_and_session_forgery(tmp_path):
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        assert c.get('/api/feedback',headers={'isolated_demo_session':'true'}).status_code==401
        enter(c)
        assert c.get('/api/feedback',headers={'Origin':'https://evil.test'}).status_code==403
        assert c.get('/',headers={'Host':'evil.test'}).status_code==403
        assert c.post('/api/imports',content=b'x'*40001).status_code==413
        assert c.get('/openapi.json').status_code==404
        assert c.get('/style.css?v=2').status_code==200


def test_model_quota_history_isolation_and_manual_fallback(tmp_path,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:True)
    async def fail(source):raise ValueError('synthetic')
    monkeypatch.setattr(model,'propose',fail)
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        enter(c)
        for _ in range(3):assert c.post('/api/suggestions',json={'source_id':'s1'}).status_code==502
        assert c.post('/api/suggestions',json={'source_id':'s1'}).status_code==429
        assert len(c.get('/api/model-runs').json())==3
        assert c.post('/api/annotations',json={'source_id':'s1','theme':'离线导出','kind':'request','quote':'希望增加离线导出功能'}).status_code==201
        c.cookies.clear();enter(c)
        assert c.get('/api/model-runs').json()==[]


def test_private_token_cannot_be_bypassed(tmp_path,monkeypatch):
    from app.main import create_app
    monkeypatch.setenv('FEEDBACKLENS_ACCESS_TOKEN','secret')
    with TestClient(create_app(tmp_path/'private.db')) as c:
        assert c.get('/api/feedback',headers={'isolated_demo_session':'true'}).status_code==401
