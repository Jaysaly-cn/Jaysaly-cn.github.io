import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import model


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('APPLYTRACK_ACCESS_TOKEN', raising=False)
    with TestClient(create_app(tmp_path / 'db.sqlite')) as c:
        yield c


def job(c):
    r = c.post('/api/jobs', json={'company': '合成公司', 'title': 'AI产品实习生',
        'jd': '负责知识问答产品需求分析。必须具备用户访谈能力。有RAG评测经验优先。'})
    assert r.status_code == 201
    return r.json()


def requirement(c, jid):
    r = c.post(f'/api/jobs/{jid}/requirements', json={'label': '用户访谈', 'quote': '必须具备用户访谈能力', 'kind': 'required'})
    assert r.status_code == 201
    return r.json()


def approve(c, r):
    response = c.post(f'/api/requirements/{r["id"]}/review', json={'version': 1, 'decision': 'approved',
        'label': r['label'], 'kind': r['kind'], 'note': '已核对原文必须要求'})
    assert response.status_code == 200
    return response.json()


def evidence(c):
    r = c.post('/api/evidence', json={'title': '合成访谈项目', 'body': '完成五次用户访谈，整理需求清单与访谈记录。'})
    assert r.status_code == 201
    return r.json()


def test_full_workflow_and_frozen_export(client):
    c = client
    j = job(c); r = approve(c, requirement(c, j['id'])); e = evidence(c)
    linked = c.post(f'/api/requirements/{r["id"]}/evidence', json={'evidence_id': e['id'],
        'quote': '完成五次用户访谈', 'rationale': '访谈记录证明实际执行，仍需人工判断质量'})
    assert linked.status_code == 201
    detail = c.get('/api/jobs/'+j['id']).json()
    assert detail['coverage']['linked_requirements'] == 1
    p = c.post(f'/api/jobs/{j["id"]}/packets').json()
    export = c.get(f'/api/packets/{p["id"]}/export')
    assert hashlib.sha256(export.content).hexdigest() == p['sha256']
    applied = c.post(f'/api/jobs/{j["id"]}/stage', json={'version': 1, 'stage': 'applied',
        'packet_id': p['id'], 'note': '合成验收记录，未真实发送投递'})
    assert applied.status_code == 200
    assert applied.json()['version'] == 2
    assert c.get(f'/api/packets/{p["id"]}/export').content == export.content
    assert export.json()['job']['stage'] == 'saved'


def test_draft_excluded_and_gap_preserved(client):
    j = job(client); r = requirement(client, j['id'])
    assert client.post(f'/api/jobs/{j["id"]}/packets').status_code == 409
    approve(client, r)
    p = client.post(f'/api/jobs/{j["id"]}/packets').json()
    body = client.get(f'/api/packets/{p["id"]}/export').json()
    assert body['job']['coverage']['gaps'] == [r['id']]


def test_fabricated_and_ambiguous_quote_rejected(client):
    j = job(client)
    for quote in ['要求十年产品经验', '不存在的连续原文']:
        assert client.post(f'/api/jobs/{j["id"]}/requirements', json={'label': '错误要求', 'quote': quote, 'kind': 'required'}).status_code == 422
    j = client.post('/api/jobs', json={'company': '合成公司', 'title': '重复要求测试', 'jd': '用户访谈能力。用户访谈能力。'}).json()
    assert client.post(f'/api/jobs/{j["id"]}/requirements', json={'label': '用户访谈', 'quote': '用户访谈能力', 'kind': 'required'}).status_code == 422


def test_evidence_requires_review_and_exact_quote(client):
    j = job(client); r = requirement(client, j['id']); e = evidence(client)
    payload = {'evidence_id': e['id'], 'quote': '完成五次用户访谈', 'rationale': '合成项目能力证据关联'}
    endpoint = f'/api/requirements/{r["id"]}/evidence'
    assert client.post(endpoint, json=payload).status_code == 409
    approve(client, r)
    assert client.post(endpoint, json={**payload, 'quote': '完成一百次用户访谈'}).status_code == 422
    assert client.post(endpoint, json=payload).status_code == 201
    assert client.post(endpoint, json=payload).status_code == 409


def test_stale_review_rejected(client):
    j = job(client); r = requirement(client, j['id']); approve(client, r)
    assert client.post(f'/api/requirements/{r["id"]}/review', json={'version': 1, 'decision': 'rejected',
        'label': r['label'], 'kind': r['kind'], 'note': '旧浏览器发起审核'}).status_code == 409


def test_wrong_job_packet_cannot_be_applied(client):
    a = job(client); b = job(client)
    approve(client, requirement(client, a['id']))
    p = client.post(f'/api/jobs/{a["id"]}/packets').json()
    assert client.post(f'/api/jobs/{b["id"]}/stage', json={'version': 1, 'stage': 'applied',
        'packet_id': p['id'], 'note': '错误岗位材料测试'}).status_code == 422
    assert client.get('/api/jobs/'+b['id']).json()['stage'] == 'saved'


def test_stage_and_followup_conflicts(client):
    j = job(client)
    assert client.post(f'/api/jobs/{j["id"]}/stage', json={'version': 1, 'stage': 'offer', 'note': '越级变更测试记录'}).status_code == 409
    url = f'/api/jobs/{j["id"]}/follow-up'
    assert client.post(url, json={'version': 1, 'due': '2020-01-01', 'note': '合成逾期提醒记录'}).status_code == 200
    assert client.post(url, json={'version': 1, 'due': None, 'note': '旧版本不应覆盖日期'}).status_code == 409
    assert len(client.get('/api/jobs?overdue=true').json()) == 1
    assert client.post(f'/api/jobs/{j["id"]}/stage', json={'version': 2, 'stage': 'withdrawn', 'note': '结束该合成求职流程'}).status_code == 200
    assert client.get('/api/jobs?overdue=true').json() == []


def test_model_atomic_rollback(client, monkeypatch):
    j = job(client)
    monkeypatch.setattr(model, 'configured', lambda: True)
    async def fake(jd):
        return [{'label': '用户访谈', 'quote': '必须具备用户访谈能力', 'kind': 'required'},
                {'label': '虚构要求', 'quote': '必须拥有十年经验', 'kind': 'required'}]
    monkeypatch.setattr(model, 'extract', fake)
    assert client.post(f'/api/jobs/{j["id"]}/extract').status_code == 422
    detail = client.get('/api/jobs/'+j['id']).json()
    assert detail['requirements'] == []
    assert detail['runs'][0]['state'] == 'failed'
    assert len(detail['events']) == 1


def test_model_draft_and_truncation(client, monkeypatch):
    j = client.post('/api/jobs', json={'company': '合成公司', 'title': '输入范围测试', 'jd': '必须具备用户访谈能力。'+'文字'*2200}).json()
    monkeypatch.setattr(model, 'configured', lambda: True)
    async def fake(jd):
        return [{'label': '用户访谈', 'quote': '必须具备用户访谈能力', 'kind': 'required'}]
    monkeypatch.setattr(model, 'extract', fake)
    response = client.post(f'/api/jobs/{j["id"]}/extract').json()
    assert response['truncated'] is True
    assert response['input_chars'] == 4000
    assert response['requirements'][0]['status'] == 'draft'


def test_security_and_url(client, monkeypatch):
    assert client.get('/api/jobs', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/evidence', json={'title': '危险链接测试', 'body': '这是合成证据文本材料', 'source_url': 'javascript:alert(1)'}).status_code == 422
    monkeypatch.setenv('APPLYTRACK_ACCESS_TOKEN', 'test-secret')
    assert client.get('/api/jobs').status_code == 401
    assert client.get('/api/jobs', headers={'Authorization': 'Bearer test-secret'}).status_code == 200


def test_persistence(tmp_path):
    path = tmp_path/'persistent.db'
    with TestClient(create_app(path)) as c:
        identifier = job(c)['id']
    with TestClient(create_app(path)) as c:
        assert c.get('/api/jobs/'+identifier).status_code == 200


def test_paid_provider_rejected(monkeypatch):
    import asyncio
    monkeypatch.setenv('AT_MODEL_BASE_URL', 'https://openrouter.ai/api/v1')
    monkeypatch.setenv('AT_MODEL', 'paid-model')
    monkeypatch.setenv('AT_MODEL_API_KEY', 'dummy')
    with pytest.raises(ValueError):
        asyncio.run(model.extract('合成岗位'))


def test_withdraw_does_not_rewrite_frozen_packet(client):
    j = job(client); r = approve(client, requirement(client, j['id']))
    p = client.post(f'/api/jobs/{j["id"]}/packets').json()
    url = f'/api/packets/{p["id"]}/export'
    original = client.get(url).content
    withdrawn = client.post(f'/api/requirements/{r["id"]}/withdraw', json={'version': r['version'], 'note': '核对后发现要求解读有误，撤回更正'})
    assert withdrawn.status_code == 200
    assert withdrawn.json()['status'] == 'withdrawn'
    assert client.get('/api/jobs/'+j['id']).json()['coverage']['approved_requirements'] == 0
    assert client.get(url).content == original
    assert client.post(f'/api/jobs/{j["id"]}/packets').status_code == 409
