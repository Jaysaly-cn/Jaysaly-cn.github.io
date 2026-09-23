import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app import model


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key in ('SUPPORTOPS_ACCESS_TOKEN', 'LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL'):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(str(tmp_path / 'test.sqlite3'))) as client:
        yield client


def test_persistent_workflow_and_ticket_guards(client):
    assert client.post('/api/seed').json()['inserted'] == 8
    assert client.post('/api/seed').json()['inserted'] == 0
    response = client.post('/api/ask', json={'question': '首次购买订阅的退款条件是什么？'})
    assert response.status_code == 201
    run = response.json()
    assert run['mode'] == 'extractive'
    assert run['citations'][0]['document_id'] == 'kb-refund'
    assert '7 天' in run['answer']
    assert client.get('/api/runs/' + run['id']).json() == run
    client.post('/api/runs/' + run['id'] + '/feedback', json={'rating': 'unhelpful', 'note': '需要订单核验'})
    assert client.get('/api/badcases').json()[0]['note'] == '需要订单核验'
    ticket = client.post('/api/tickets', json={'run_id': run['id'], 'title': '核查退款资格'}).json()
    assert ticket['status'] == 'open'
    duplicate = client.post('/api/tickets', json={'run_id': run['id'], 'title': '重复创建'}).json()
    assert duplicate['id'] == ticket['id'] and duplicate['deduplicated']
    endpoint = '/api/tickets/' + ticket['id']
    assert client.patch(endpoint, json={'version': 1, 'status': 'resolved', 'assignee': '测试员', 'resolution': '处理'}).status_code == 409
    assert client.patch(endpoint, json={'version': 1, 'status': 'in_progress'}).status_code == 422
    assert client.patch(endpoint, json={'version': 1, 'status': 'in_progress', 'assignee': '测试员'}).status_code == 200
    assert client.patch(endpoint, json={'version': 1, 'status': 'in_progress', 'assignee': '旧页面'}).status_code == 409
    assert client.patch(endpoint, json={'version': 2, 'status': 'resolved', 'assignee': '测试员'}).status_code == 422
    assert client.patch(endpoint, json={'version': 2, 'status': 'resolved', 'assignee': '测试员', 'resolution': '已人工核验订单'}).status_code == 200
    detail = client.get(endpoint).json()
    assert len(detail['events']) == 3 and detail['version'] == 3
    assert client.delete('/api/documents/kb-refund').status_code == 200
    assert client.get('/api/runs/' + run['id']).json()['citations'] == run['citations']
    assert client.get('/api/metrics').json()['ticket_status']['resolved'] == 1


def test_scope_unknown_and_validation(client):
    client.post('/api/seed')
    public = client.post('/api/ask', json={'question': 'ORBIT-47 内部安全泄露处置'}).json()
    assert all(c['document_id'] != 'kb-security' for c in public['citations'])
    internal = client.post('/api/ask', json={'question': 'ORBIT-47 内部安全泄露处置', 'audience': 'internal'}).json()
    assert internal['citations'][0]['document_id'] == 'kb-security'
    unknown = client.post('/api/ask', json={'question': '火星菠萝披萨'}).json()
    assert unknown['mode'] == 'no_evidence' and unknown['citations'] == []
    assert client.post('/api/ask', json={'question': ' '}).status_code == 422
    assert client.post('/api/ask', json={'question': '退款', 'audience': 'admin'}).status_code == 422
    assert client.post('/api/ask', json={'question': '退款', 'use_model': True}).status_code == 409
    assert client.post('/api/tickets', json={'run_id': 'missing', 'title': '不存在'}).status_code == 404
    assert client.post('/api/documents', json={'title': ' ', 'content': '文档'}).status_code == 422


def test_auth_and_origin(client, monkeypatch):
    assert client.post('/api/seed', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.get('/api/documents', headers={'Host': 'evil.example'}).status_code == 403
    monkeypatch.setenv('SUPPORTOPS_ACCESS_TOKEN', 'local-test-token')
    assert client.get('/api/documents').status_code == 401
    assert client.get('/api/documents', headers={'Authorization': 'Bearer wrong'}).status_code == 401
    assert client.get('/api/documents', headers={'Authorization': 'Bearer local-test-token'}).status_code == 200


def test_remote_requires_token(tmp_path, monkeypatch):
    monkeypatch.delenv('SUPPORTOPS_ACCESS_TOKEN', raising=False)
    with TestClient(create_app(str(tmp_path / 'remote.db')), client=('203.0.113.8', 1234)) as c:
        assert c.get('/api/documents').status_code == 403


def test_restart_keeps_data(tmp_path):
    path = str(tmp_path / 'restart.db')
    with TestClient(create_app(path)) as c:
        response = c.post('/api/documents', json={'title': '持久化', 'content': '重启后仍可见'})
        identity = response.json()['id']
    with TestClient(create_app(path)) as c:
        assert c.get('/api/documents').json()[0]['id'] == identity


def test_model_success_and_failure_are_not_disguised(client, monkeypatch):
    client.post('/api/seed')
    for key, value in [('LLM_API_KEY', 'fake-for-test'), ('LLM_BASE_URL', 'https://example.invalid'), ('LLM_MODEL', 'test-model')]:
        monkeypatch.setenv(key, value)

    async def good(*args):
        return {'answer': '首次购买 7 天内可提交申请 [1]。', 'citation_ids': [1], 'insufficient': False, 'usage': {'total_tokens': 42}}
    monkeypatch.setattr(model, 'generate', good)
    result = client.post('/api/ask', json={'question': '订阅退款', 'use_model': True}).json()
    assert result['mode'] == 'model' and result['usage']['total_tokens'] == 42

    async def bad(*args):
        raise RuntimeError('upstream secret-token should never be echoed')
    monkeypatch.setattr(model, 'generate', bad)
    result = client.post('/api/ask', json={'question': '订阅退款', 'use_model': True}).json()
    assert result['mode'] == 'model_error'
    assert 'secret-token' not in json.dumps(result)
    assert result['citations'] and result['trace'][1]['status'] == 'error'


@pytest.mark.parametrize('payload', [
    {'answer': '有效 [1]', 'citation_ids': [1], 'insufficient': False},
    {'answer': '假引用 [999]', 'citation_ids': [999], 'insufficient': False},
    {'answer': '缺失引用', 'citation_ids': [], 'insufficient': False},
    {'answer': '', 'citation_ids': [1], 'insufficient': False},
    {'answer': '错配引用 [2]', 'citation_ids': [1], 'insufficient': False},
])
def test_provider_http_contract(monkeypatch, payload):
    monkeypatch.setenv('LLM_BASE_URL', 'http://127.0.0.1:8770/v1')
    monkeypatch.setenv('LLM_API_KEY', 'fake')
    monkeypatch.setenv('LLM_MODEL', 'test')
    original = httpx.AsyncClient

    def handler(request):
        assert str(request.url) == 'http://127.0.0.1:8770/v1/chat/completions'
        data = json.loads(request.content)
        assert data['model'] == 'test' and len(data['messages']) == 2
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(payload)}}]})
    monkeypatch.setattr(model.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    args = ('问题', [{'title': '证据', 'content': '原文'}])
    if payload['answer'] == '有效 [1]':
        assert asyncio.run(model.generate(*args))['answer'] == '有效 [1]'
    else:
        with pytest.raises(ValueError):
            asyncio.run(model.generate(*args))


def test_request_limit_and_literal_document_content(client):
    assert client.post('/api/documents', content='x' * 240001).status_code == 413
    content = '<script>alert(1)</script> 合成策略：月球会议每周二举行。'
    response = client.post('/api/documents', json={'title': '月球会议', 'content': content})
    assert response.status_code == 201
    run = client.post('/api/ask', json={'question': '月球会议何时举行？'}).json()
    assert run['citations'][0]['content'] == content
    assert run['mode'] == 'extractive'


@pytest.mark.parametrize('base,name', [
    ('https://openrouter.ai/api/v1', 'paid-model'),
    ('https://unapproved.example/v1', 'anything:free'),
    ('http://user:password@localhost/v1', 'local'),
])
def test_only_free_or_local_provider(monkeypatch, base, name):
    monkeypatch.setenv('LLM_BASE_URL', base)
    monkeypatch.setenv('LLM_MODEL', name)
    monkeypatch.setenv('LLM_API_KEY', 'test')
    with pytest.raises(ValueError):
        asyncio.run(model.generate('退款规则', [{'title': '合成政策', 'content': '原文'}]))


def test_local_model_does_not_need_key(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'http://127.0.0.1:8770/v1')
    monkeypatch.setenv('LLM_MODEL', 'local')
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    assert model.configured()


def resolved_ticket(client,audience='public'):
    run=client.post('/api/ask',json={'question':'离线激活码如何恢复？','audience':audience}).json()
    ticket=client.post('/api/tickets',json={'run_id':run['id'],'title':'离线激活码恢复'}).json()
    endpoint='/api/tickets/'+ticket['id']
    client.patch(endpoint,json={'version':1,'status':'in_progress','assignee':'合成测试员'})
    response=client.patch(endpoint,json={'version':2,'status':'resolved','assignee':'合成测试员','resolution':'合成个案：管理员已核对设备标识，重新发放离线激活码。'})
    assert response.status_code==200
    return run,response.json()


def knowledge_payload():
    return {'version':3,'title':'离线激活码恢复流程','content':'离线激活码失效时，由管理员先核对设备标识与授权状态，再通过管理后台重新生成激活码。',
            'review_note':'合成流程，仅适用于管理员核验后的设备，已移除个案信息','reviewed':True}


def test_resolved_ticket_knowledge_is_retrievable_without_rewriting_old_run(client):
    old,ticket=resolved_ticket(client)
    assert old['mode']=='no_evidence'
    response=client.post('/api/tickets/'+ticket['id']+'/knowledge',json=knowledge_payload())
    assert response.status_code==201
    publication=response.json()
    current=client.post('/api/ask',json={'question':'离线激活码如何恢复？'}).json()
    assert current['citations'][0]['document_id']==publication['document_id']
    assert client.get('/api/runs/'+old['id']).json()==old
    detail=client.get('/api/tickets/'+ticket['id']).json()
    snapshot=detail['publications'][0]['snapshot']
    assert snapshot['ticket']['version']==3 and snapshot['run']==old
    assert snapshot['review_note']==knowledge_payload()['review_note']
    assert detail['events'][-1]['event']=='knowledge_published'


def test_publication_requires_review_current_resolved_version_and_is_not_duplicated(client):
    _,ticket=resolved_ticket(client);route='/api/tickets/'+ticket['id'];payload=knowledge_payload()
    assert client.post(route+'/knowledge',json={**payload,'reviewed':False}).status_code==422
    assert client.post(route+'/knowledge',json={**payload,'version':2}).status_code==409
    assert client.post(route+'/knowledge',json=payload).status_code==201
    assert client.post(route+'/knowledge',json=payload).status_code==409
    before=client.get(route).json()['publications']
    doc=before[0]['document_id']
    assert client.delete('/api/documents/'+doc).status_code==200
    assert client.get(route).json()['publications']==before
    assert client.patch(route,json={'version':3,'status':'open','resolution':''}).status_code==200
    assert client.post(route+'/knowledge',json={**payload,'version':4}).status_code==409


def test_internal_knowledge_cannot_be_published_to_public_scope(client):
    _,ticket=resolved_ticket(client,'internal');route='/api/tickets/'+ticket['id']+'/knowledge'
    assert client.post(route,json={**knowledge_payload(),'audience':'public'}).status_code==422
    publication=client.post(route,json=knowledge_payload()).json()
    assert publication['audience']=='internal'
    public=client.post('/api/ask',json={'question':'离线激活码如何恢复？','audience':'public'}).json()
    internal=client.post('/api/ask',json={'question':'离线激活码如何恢复？','audience':'internal'}).json()
    assert public['mode']=='no_evidence'
    assert internal['citations'][0]['document_id']==publication['document_id']


def test_recheck_records_changed_evidence_without_mutating_old_answer_or_feedback(client,monkeypatch):
    old=client.post('/api/ask',json={'question':'离线激活码如何恢复？'}).json()
    client.post('/api/runs/'+old['id']+'/feedback',json={'rating':'unhelpful','note':'缺少操作说明'})
    async def forbidden(*args):raise AssertionError('Recheck must not call model')
    monkeypatch.setattr(model,'generate',forbidden)
    doc=client.post('/api/documents',json={'title':'激活码恢复','content':'离线激活码失效后，由管理员核对授权设备，再重新生成激活码。'}).json()
    check=client.post('/api/runs/'+old['id']+'/rechecks').json()
    assert check['snapshot']['before']==old and check['verdict']==''
    assert check['snapshot']['after']['citations'][0]['document_id']==doc['id']
    assert len(check['snapshot']['after']['manifest'][0]['sha256'])==64
    client.delete('/api/documents/'+doc['id'])
    assert client.get('/api/rechecks').json()[0]==check
    review={'verdict':'improved','note':'新资料覆盖授权核验与重发步骤','reviewed':True}
    endpoint='/api/rechecks/'+check['id']+'/review'
    assert client.post(endpoint,json={**review,'reviewed':False}).status_code==422
    reviewed=client.post(endpoint,json=review).json()
    assert reviewed['snapshot']==check['snapshot'] and reviewed['reviewed_at']
    assert client.post(endpoint,json=review).status_code==409
    assert client.get('/api/runs/'+old['id']).json()==old
    assert client.get('/api/badcases').json()[0]['note']=='缺少操作说明'


def test_recheck_preserves_scope_and_bounds_history(client):
    old=client.post('/api/ask',json={'question':'离线激活码如何恢复？','audience':'public'}).json()
    client.post('/api/documents',json={'title':'激活码内部流程','content':'离线激活码失效后由内部管理员核对授权设备。','audience':'internal'})
    route='/api/runs/'+old['id']+'/rechecks'
    for _ in range(20):
        response=client.post(route);assert response.status_code==201
        assert response.json()['snapshot']['after']['documents_searched']==0
    assert client.post(route).status_code==409
    assert client.post('/api/runs/missing/rechecks').status_code==404
    assert client.post('/api/rechecks/missing/review',json={'verdict':'inconclusive','note':'未找到可核对的记录','reviewed':True}).status_code==404
