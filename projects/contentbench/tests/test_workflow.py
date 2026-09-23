import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import model

BRIEF = {'name': '合成任务本', 'audience': '职场新人', 'objective': '邀请体验', 'tone': '克制友好',
         'facts': [{'id': 'F1', 'text': '支持手动添加任务与截止日期', 'source': '合成规格 v1'},
                   {'id': 'F2', 'text': '支持按周查看任务清单', 'source': '合成规格 v1'}],
         'forbidden': ['保证'], 'required_phrase': '示例产品，仅供学习'}
COPY = {'title': '把每周任务放在一起', 'body': '支持按周查看任务清单。示例产品，仅供学习', 'fact_ids': ['F2'], 'channel': '小红书'}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('CONTENTBENCH_ACCESS_TOKEN', raising=False)
    monkeypatch.delenv('CB_MODEL', raising=False)
    with TestClient(create_app(tmp_path / 'test.db')) as c:
        yield c


def setup(client):
    c = client.post('/api/campaigns', json=BRIEF)
    assert c.status_code == 201
    cid = c.json()['id']
    r = client.post(f'/api/campaigns/{cid}/drafts', json=COPY)
    assert r.status_code == 201
    return cid, r.json()


def approve(client, revision, **overrides):
    return client.post('/api/revisions/' + revision['id'] + '/review', json={
        'state': 'approved', 'version': revision['version'], 'note': '逐句核对合成规格与措辞', 'facts_checked': True, **overrides})


def test_export_is_immutable_and_edit_needs_review(client):
    cid, r = setup(client)
    assert client.post(f'/api/campaigns/{cid}/exports').status_code == 409
    assert approve(client, r).status_code == 200
    snapshot = client.post(f'/api/campaigns/{cid}/exports').json()
    revised = {k: v for k, v in COPY.items() if k != 'channel'}
    revised.update(expected_revision=r['id'], title='新的标题')
    next = client.post('/api/drafts/' + r['draft_id'] + '/revisions', json=revised)
    assert next.status_code == 201 and next.json()['state'] == 'draft'
    assert client.post(f'/api/campaigns/{cid}/exports').status_code == 409
    assert client.get('/api/exports/' + snapshot['id']).json() == snapshot
    assert approve(client, r).status_code == 409
    assert client.post('/api/drafts/' + r['draft_id'] + '/revisions', json=revised).status_code == 409


def test_human_attestation_and_review_once(client):
    cid, r = setup(client)
    assert approve(client, r, facts_checked=False).status_code == 422
    assert approve(client, r, note='好').status_code == 422
    assert approve(client, r, version=2).status_code == 409
    assert approve(client, r).status_code == 200
    assert approve(client, r).status_code == 409


@pytest.mark.parametrize('body,code', [('保证提升效率。示例产品，仅供学习', 'forbidden'),
    ('效率提升99%。示例产品，仅供学习', 'numbers'), ('今天开始整理任务。', 'required'),
    ('任务' * 400 + '示例产品，仅供学习', 'length')])
def test_check_blocks_approval(client, body, code):
    cid, _ = setup(client)
    r = client.post(f'/api/campaigns/{cid}/drafts', json={**COPY, 'body': body}).json()
    assert code in [x['code'] for x in r['checks']['blockers']]
    assert approve(client, r).status_code == 422
    assert approve(client, r, state='rejected', facts_checked=False).status_code == 200


@pytest.mark.parametrize('ids', [['F9'], ['F2', 'F2']])
def test_invalid_fact_ids_rollback(client, ids):
    cid, _ = setup(client)
    assert client.post(f'/api/campaigns/{cid}/drafts', json={**COPY, 'fact_ids': ids}).status_code == 422
    assert len(client.get('/api/campaigns/' + cid).json()['drafts']) == 1


def test_no_facts_saved_but_not_approved(client):
    cid, _ = setup(client)
    r = client.post(f'/api/campaigns/{cid}/drafts', json={**COPY, 'fact_ids': []}).json()
    assert approve(client, r).status_code == 422


def test_model_is_never_auto_approved(client, monkeypatch):
    cid, _ = setup(client)
    monkeypatch.setattr(model, 'configured', lambda: True)
    async def generated(*args):
        return {k: v for k, v in COPY.items() if k != 'channel'}, 'test-model'
    monkeypatch.setattr(model, 'generate', generated)
    r = client.post(f'/api/campaigns/{cid}/generate', json={'channel': '小红书'})
    assert r.status_code == 201
    assert r.json()['state'] == 'draft' and r.json()['origin'] == 'model'
    assert client.post(f'/api/campaigns/{cid}/exports').status_code == 409


def test_invalid_model_result_does_not_create_draft(client, monkeypatch):
    cid, _ = setup(client)
    monkeypatch.setattr(model, 'configured', lambda: True)
    async def invalid(*args):
        return {'title': 'Invalid', 'body': 'bad', 'fact_ids': ['F99']}, 'test-model'
    monkeypatch.setattr(model, 'generate', invalid)
    assert client.post(f'/api/campaigns/{cid}/generate', json={'channel': '邮件'}).status_code == 502
    detail = client.get('/api/campaigns/' + cid).json()
    assert len(detail['drafts']) == 1 and detail['events'][0]['action'] == 'generation_failed'


def test_unconfigured_model_is_explicit(client):
    cid, _ = setup(client)
    assert client.post(f'/api/campaigns/{cid}/generate', json={'channel': '邮件'}).status_code == 503


def test_api_guard_and_body_limit(client, monkeypatch):
    assert client.get('/api/status', headers={'Host': 'evil.test'}).status_code == 403
    assert client.post('/api/campaigns', json=BRIEF, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.post('/api/campaigns', content='x'*400001).status_code == 413
    monkeypatch.setenv('CONTENTBENCH_ACCESS_TOKEN', 'test-secret')
    assert client.get('/api/status').status_code == 401
    assert client.get('/api/status', headers={'Authorization': 'Bearer test-secret'}).status_code == 200


def test_persistence(tmp_path, monkeypatch):
    monkeypatch.delenv('CONTENTBENCH_ACCESS_TOKEN', raising=False)
    path = tmp_path / 'persistent.db'
    with TestClient(create_app(path)) as c:
        cid, r = setup(c)
        approve(c, r)
    with TestClient(create_app(path)) as c:
        assert c.get('/api/campaigns/' + cid).json()['drafts'][0]['revisions'][0]['state'] == 'approved'


def test_paid_provider_is_rejected_before_network(monkeypatch):
    import asyncio
    monkeypatch.setenv('CB_MODEL_BASE_URL', 'https://openrouter.ai/api/v1')
    monkeypatch.setenv('CB_MODEL', 'paid-model')
    monkeypatch.setenv('CB_MODEL_API_KEY', 'test')
    with pytest.raises(ValueError):
        asyncio.run(model.generate(BRIEF, '短信', 70))


def test_numeric_normalization_and_reference_scope():
    from app.checks import check
    brief = {**BRIEF, 'facts': [{'id':'F1', 'text':'支持 10 项任务', 'source':'合成规格'},
                              {'id':'F2', 'text':'试用 30 天', 'source':'合成规格'}]}
    a = check(brief, '短信', '清单', '支持１０项任务。示例产品，仅供学习', ['F1'])
    assert not a['blockers']
    b = check(brief, '短信', '清单', '试用30天。示例产品，仅供学习', ['F1'])
    assert 'numbers' in [i['code'] for i in b['blockers']]
