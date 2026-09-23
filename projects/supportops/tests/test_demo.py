from fastapi.testclient import TestClient
from app.demo import create_demo_app, COOKIE


def enter(c):
    response=c.get('/')
    assert response.status_code==200 and '临时公开演示' in response.text
    assert 'secure' in response.headers['set-cookie'].lower()
    assert len(c.get('/api/documents').json())==8


def test_full_knowledge_loop_and_visitor_isolation(tmp_path):
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        enter(c)
        question='离线激活码如何恢复？'
        old=c.post('/api/ask',json={'question':question}).json()
        assert old['mode'] in ('extractive','no_evidence')
        assert c.post('/api/runs/'+old['id']+'/feedback',json={'rating':'unhelpful','note':'合成问题缺少专门步骤'}).status_code==200
        ticket=c.post('/api/tickets',json={'run_id':old['id'],'title':'离线激活恢复 · 合成'}).json()
        route='/api/tickets/'+ticket['id']
        assert c.patch(route,json={'version':1,'status':'in_progress','assignee':'合成值班员'}).status_code==200
        assert c.patch(route,json={'version':2,'status':'resolved','assignee':'合成值班员','resolution':'核对授权设备后重新发放激活码。'}).status_code==200
        published=c.post(route+'/knowledge',json={'version':3,'title':'离线激活码恢复步骤','content':'离线激活码失效时，由管理员先核对设备标识与授权状态，再通过管理后台重新生成激活码。','review_note':'合成流程，已核对适用范围','reviewed':True})
        assert published.status_code==201
        check=c.post('/api/runs/'+old['id']+'/rechecks').json()
        assert check['snapshot']['after']['citations'][0]['document_id']==published.json()['document_id']
        assert c.post('/api/rechecks/'+check['id']+'/review',json={'verdict':'improved','note':'新知识出现合成问题的恢复步骤','reviewed':True}).status_code==200
        assert c.get('/api/runs/'+old['id']).json()==old
        cookie=c.cookies.get(COOKIE)
        c.cookies.clear();enter(c)
        for endpoint in ['runs','tickets','rechecks','badcases']:
            assert c.get('/api/'+endpoint).json()==[]
        assert c.get('/api/runs/'+old['id']).status_code==404
        assert c.get(route).status_code==404
        assert c.patch(route,json={'version':3,'status':'open'}).status_code==404
        assert c.post('/api/rechecks/'+check['id']+'/review',json={'verdict':'regressed','note':'跨访客请求必须拒绝','reviewed':True}).status_code==404
        assert c.delete('/api/documents/'+published.json()['document_id']).status_code==404
        # Seed IDs are shared text, but deleting a synthetic seed affects only this visitor.
        assert c.delete('/api/documents/kb-refund').status_code==200
        c.cookies.clear();c.cookies.set(COOKIE,cookie,domain='testserver.local',path='/')
        assert len(c.get('/api/documents').json())==9
        assert c.get('/api/runs/'+old['id']).json()==old
        assert c.get(route).json()['publications'][0]['document_id']==published.json()['document_id']


def test_demo_cannot_generate_even_if_model_is_configured(tmp_path,monkeypatch):
    from app import model
    monkeypatch.setattr(model,'configured',lambda:True)
    async def forbidden(*args):raise AssertionError('Demo must never call model')
    monkeypatch.setattr(model,'generate',forbidden)
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        enter(c)
        health=c.get('/api/health').json()
        assert health['model_configured'] is False and health['model'] is None
        assert c.post('/api/ask',json={'question':'退款条件是什么','use_model':True}).status_code==409
        answer=c.post('/api/ask',json={'question':'退款条件是什么'}).json()
        assert answer['mode']=='extractive' and answer['citations']


def test_expiry_capacity_and_cleanup(tmp_path):
    clock=[0];app=create_demo_app(tmp_path,clock=lambda:clock[0])
    keep=tmp_path/'keep.txt';keep.write_text('keep')
    with TestClient(app,base_url='https://testserver') as c:
        for _ in range(12):c.cookies.clear();enter(c)
        paths=[s['path'] for s in app.state.demo_sessions.values()]
        c.cookies.clear();assert c.get('/').status_code==429
        clock[0]=1801
        assert c.get('/api/runs').status_code==401
        assert all(not p.exists() for p in paths)
        assert keep.read_text()=='keep'
        enter(c)


def test_host_origin_size_and_forged_session(tmp_path):
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        assert c.get('/api/documents',headers={'isolated_demo_session':'true'}).status_code==401
        enter(c)
        assert c.get('/api/documents',headers={'Origin':'https://foreign.example'}).status_code==403
        assert c.get('/',headers={'Host':'foreign.example'}).status_code==403
        assert c.post('/api/seed',headers={'sec-fetch-site':'cross-site'}).status_code==403
        assert c.post('/api/documents',content=b'x'*40001).status_code==413
        assert c.get('/openapi.json').status_code==404
        assert c.get('/static/style.css').status_code==200


def test_private_token_cannot_be_bypassed(tmp_path,monkeypatch):
    from app.main import create_app
    monkeypatch.setenv('SUPPORTOPS_ACCESS_TOKEN','secret')
    with TestClient(create_app(tmp_path/'private.db')) as c:
        assert c.get('/api/documents',headers={'isolated_demo_session':'true'}).status_code==401
