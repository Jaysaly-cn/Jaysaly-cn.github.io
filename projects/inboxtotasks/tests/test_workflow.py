import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from test_ingest import mail


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.delenv('INBOXTOTASKS_ACCESS_TOKEN',raising=False)
    with TestClient(create_app(tmp_path/'tasks.db')) as c:yield c


def setup(c,body='请小林在周五前提交方案。'):
    response=c.post('/api/messages',content=mail(body).as_bytes())
    assert response.status_code==201
    mid=response.json()['id']
    candidate=c.post(f'/api/messages/{mid}/tasks',json={'title':'提交方案','quote':body})
    assert candidate.status_code==201
    return mid,candidate.json()


def confirm(c,t,**changes):
    return c.post(f'/api/tasks/{t["id"]}/confirm',json={'version':t['version'],'owner':'小林',
        'due_date':'2026-09-25','note':'已核对邮件责任人与具体日期',**changes})


def test_confirm_complete_and_export_snapshot(client):
    mid,t=setup(client)
    assert client.post('/api/exports').status_code==409
    approved=confirm(client,t).json()
    assert approved['state']=='open' and approved['version']==2
    frozen=client.post('/api/exports').json()
    state=client.post(f'/api/tasks/{t["id"]}/state',json={'version':2,'state':'done','note':'已经提交方案给项目同事'})
    assert state.status_code==200 and state.json()['version']==3
    response=client.get('/api/exports/'+frozen['id'])
    assert response.json()==frozen and '.json' in response.headers['content-disposition']
    assert frozen['sources'][0]['body_sha256']==t['body_sha256']
    events=client.get(f'/api/tasks/{t["id"]}/history').json()
    assert [x['snapshot']['state'] for x in events]==['draft','open','done']


def test_version_conflicts_and_draft_cannot_skip_confirmation(client):
    mid,t=setup(client)
    assert client.post(f'/api/tasks/{t["id"]}/state',json={'version':1,'state':'done','note':'不能跳过人工确认流程'}).status_code==409
    assert confirm(client,t).status_code==200
    assert confirm(client,t).status_code==409
    assert client.post(f'/api/tasks/{t["id"]}/state',json={'version':1,'state':'doing','note':'旧页面提交应拒绝写入'}).status_code==409
    assert len(client.get(f'/api/tasks/{t["id"]}/history').json())==2


def test_revision_resets_confirmation_and_preserves_history(client):
    mid,t=setup(client);confirm(client,t)
    new=client.post(f'/api/tasks/{t["id"]}/revise',json={'version':2,'title':'提交项目方案','quote':t['quote'],'note':'明确任务对象，重新核对责任'}).json()
    assert new['state']=='draft' and new['owner']=='' and new['due_date'] is None
    assert client.post('/api/exports').status_code==409
    events=client.get(f'/api/tasks/{t["id"]}/history').json()
    assert events[1]['snapshot']['owner']=='小林' and events[2]['snapshot']['title']=='提交项目方案'


def test_exact_quote_ambiguity_and_duplicate_candidate(client):
    mid,t=setup(client,'请提交方案。请提交方案。')
    url=f'/api/messages/{mid}/tasks'
    assert client.post(url,json={'title':'提交','quote':'请提交方案。'}).status_code==422
    payload={'title':'提交','quote':'请提交方案。','quote_start':6}
    one=client.post(url,json=payload);assert one.status_code==201
    assert client.post(url,json=payload).json()['id']==one.json()['id']
    assert client.post(url,json={**payload,'quote_start':1}).status_code==422
    assert client.post(url,json={'title':'虚构事项','quote':'立即支付费用'}).status_code==422


def test_message_conflict_requires_explicit_current_acknowledgement(client):
    mid,t=setup(client)
    newer=client.post('/api/messages',content=mail('改期到下周一提交方案。').as_bytes()).json()
    assert confirm(client,t).status_code==409
    assert confirm(client,t,conflict_ids=[newer['id']]).status_code==200
    events=client.get(f'/api/tasks/{t["id"]}/history').json()
    assert len(events)==2 and events[-1]['snapshot']['acknowledged_conflicts']==[newer['id']]
    assert client.post('/api/exports').json()['sources'][0]['message_id_conflicts']==[newer['id']]


def test_reject_and_reopen_confirmed_task(client):
    mid,t=setup(client)
    r=client.post(f'/api/tasks/{t["id"]}/state',json={'version':1,'state':'rejected','note':'旧引用不构成当前待办事项'})
    assert r.status_code==200 and confirm(client,r.json()).status_code==409
    mid,other=setup(client,'请在下周提交修改稿。')
    conflict=client.get('/api/messages/'+mid).json()['message_id_conflicts']
    active=confirm(client,other,due_date=None,conflict_ids=conflict).json()
    for version,state in [(2,'cancelled'),(3,'open')]:
        r=client.post(f'/api/tasks/{other["id"]}/state',json={'version':version,'state':state,'note':'人工核对后变更跟进状态'})
        assert r.status_code==200
    assert r.json()['due_date'] is None


def test_security_and_invalid_import(client,monkeypatch):
    assert client.post('/api/messages',content=b'bad').status_code==422
    assert client.get('/api/messages/unknown').status_code==404
    assert client.get('/api/messages',headers={'Origin':'https://evil.invalid'}).status_code==403
    assert client.get('/api/messages',headers={'Host':'evil.invalid'}).status_code==403
    monkeypatch.setenv('INBOXTOTASKS_ACCESS_TOKEN','synthetic-secret')
    assert client.get('/api/messages').status_code==401
    assert client.get('/api/messages',headers={'Authorization':'Bearer synthetic-secret'}).status_code==200


def test_workspace_assets_sample_and_export_listing(client):
    page=client.get('/')
    assert page.status_code==200 and 'InboxToTasks' in page.text
    assert "script-src 'self'" in page.headers['content-security-policy']
    assert client.get('/static/app.js').status_code==200
    sample=client.get('/sample.eml');assert sample.status_code==200
    assert client.post('/api/messages',content=sample.content).status_code==201
    assert client.get('/api/exports').json()==[]
    mid,t=setup(client);confirm(client,t)
    exported=client.post('/api/exports').json()
    assert client.get('/api/exports').json()[0]['id']==exported['id']
