from fastapi.testclient import TestClient
from app.demo import create_demo_app, COOKIE
from app import model


def enter(client):
    response=client.get('/')
    assert response.status_code==200 and '临时公开演示' in response.text
    assert 'secure' in response.headers['set-cookie'].lower()
    docs=client.get('/api/documents').json()
    assert len(docs)==1
    versions=client.get('/api/documents/'+docs[0]['id']+'/versions').json()
    assert len(versions)==2
    return docs[0],versions


def compare(client, versions):
    response=client.post('/api/comparisons',json={'old_id':versions[0]['id'],'new_id':versions[1]['id']})
    assert response.status_code==201
    return response.json()


def test_versions_impacts_briefs_and_export_are_isolated(tmp_path):
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        doc,versions=enter(c);snapshot=compare(c,versions)
        cid=snapshot['id'];index=next(i for i,o in enumerate(snapshot['diff']['operations']) if o['kind']!='equal')
        op=snapshot['diff']['operations'][index]
        impact=c.post(f'/api/comparisons/{cid}/operations/{index}/impacts',json={'summary':'保留期由七天改为三天，并新增审计。','old_quote':op['old_text'],'new_quote':op['new_text']}).json()
        assert c.post('/api/impacts/'+impact['id']+'/review',json={'version':1,'decision':'confirmed','note':'核对合成原文后确认'}).status_code==200
        brief=c.post(f'/api/comparisons/{cid}/briefs',json={'title':'访客简报验收','note':'使用合成文档检查隔离'}).json()
        archive=c.get('/api/briefs/'+brief['id']+'/export').content
        cookie=c.cookies.get(COOKIE)
        c.cookies.clear();other,_=enter(c)
        assert other['id']!=doc['id']
        for endpoint in [f'documents/{doc["id"]}/versions',f'versions/{versions[0]["id"]}',f'comparisons/{cid}',f'comparisons/{cid}/impacts',f'comparisons/{cid}/model-runs',f'briefs/{brief["id"]}',f'briefs/{brief["id"]}/export']:
            assert c.get('/api/'+endpoint).status_code==404
        assert c.post('/api/impacts/'+impact['id']+'/review',json={'version':2,'decision':'rejected','note':'跨访客写入必须拒绝'}).status_code==404
        c.cookies.clear();c.cookies.set(COOKIE,cookie,domain='testserver.local',path='/')
        assert c.get('/api/briefs/'+brief['id']).json()==brief
        assert c.get('/api/briefs/'+brief['id']+'/export').content==archive


def test_expiry_cleanup_capacity_and_unrelated_file(tmp_path):
    clock=[0];app=create_demo_app(tmp_path,clock=lambda:clock[0])
    keep=tmp_path/'keep.txt';keep.write_text('keep')
    with TestClient(app,base_url='https://testserver') as c:
        for _ in range(12):c.cookies.clear();enter(c)
        paths=[s['path'] for s in app.state.demo_sessions.values()]
        c.cookies.clear();assert c.get('/').status_code==429
        clock[0]=1801
        assert c.get('/api/documents').status_code==401
        assert all(not p.exists() for p in paths)
        assert keep.read_text()=='keep'
        enter(c)


def test_origins_host_body_and_session_forgery(tmp_path):
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        assert c.get('/api/documents',headers={'isolated_demo_session':'true'}).status_code==401
        doc,_=enter(c)
        assert c.get('/api/documents',headers={'Origin':'https://evil.test'}).status_code==403
        assert c.get('/',headers={'Host':'evil.test'}).status_code==403
        assert c.post('/api/documents',headers={'sec-fetch-site':'cross-site'},json={'title':'跨站'}).status_code==403
        assert c.post('/api/documents/'+doc['id']+'/versions/file?label=test',content=b'x'*40001).status_code==413
        assert c.get('/openapi.json').status_code==404
        assert c.get('/style.css').status_code==200


def test_failed_model_calls_use_quota_and_manual_fallback_remains(tmp_path,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:True)
    async def fail(op):raise ValueError('synthetic')
    monkeypatch.setattr(model,'propose',fail)
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        _,versions=enter(c);snapshot=compare(c,versions);cid=snapshot['id']
        index=next(i for i,o in enumerate(snapshot['diff']['operations']) if o['kind']!='equal')
        endpoint=f'/api/comparisons/{cid}/operations/{index}'
        for _ in range(3):assert c.post(endpoint+'/suggest').status_code==502
        assert c.post(endpoint+'/suggest/').status_code==429
        assert len(c.get(f'/api/comparisons/{cid}/model-runs').json())==3
        op=snapshot['diff']['operations'][index]
        assert c.post(endpoint+'/impacts',json={'summary':'手工核对变更仍可保存','old_quote':op['old_text'],'new_quote':op['new_text']}).status_code==201


def test_private_service_cannot_be_bypassed(tmp_path,monkeypatch):
    from app.main import create_app
    monkeypatch.setenv('CHANGELENS_ACCESS_TOKEN','secret')
    with TestClient(create_app(tmp_path/'private.db')) as c:
        assert c.get('/api/documents',headers={'isolated_demo_session':'true'}).status_code==401
