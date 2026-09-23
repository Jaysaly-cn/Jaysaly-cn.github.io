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
