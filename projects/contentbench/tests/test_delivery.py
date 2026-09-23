from app.exports import literal
from test_workflow import client, setup, COPY, approve


def test_markdown_uses_frozen_versions_and_evidence(client):
    cid, old = setup(client)
    approve(client, old)
    snapshot = client.post(f'/api/campaigns/{cid}/exports').json()
    url = '/api/exports/'+snapshot['id']+'?format=markdown'
    first = client.get(url)
    assert first.status_code == 200
    assert first.headers['content-type'].startswith('text/markdown')
    assert first.headers['content-disposition'].endswith('.md"')
    assert first.headers['x-content-type-options'] == 'nosniff'
    for expected in (old['id'], old['body'], 'F2', '合成规格 v1', '逐句核对合成规格与措辞'):
        assert expected in first.text
    next_copy = {k: v for k, v in COPY.items() if k != 'channel'}
    next_copy.update(expected_revision=old['id'], title='后续修改的标题')
    assert client.post('/api/drafts/'+old['draft_id']+'/revisions', json=next_copy).status_code == 201
    assert client.get(url).content == first.content
    assert '后续修改的标题' not in first.text
    assert client.get('/api/exports/'+snapshot['id']).json() == snapshot


def test_delivery_literal_fences_preserve_untrusted_text(client):
    cid, old = setup(client)
    text = '```\n<script>alert()</script>\n``````\n[点击](javascript:alert())\n示例产品，仅供学习'
    data = {**COPY, 'body': text}
    new = client.post(f'/api/campaigns/{cid}/drafts', json=data).json()
    assert approve(client, new).status_code == 200
    snapshot = client.post(f'/api/campaigns/{cid}/exports').json()
    result = client.get('/api/exports/'+snapshot['id']+'?format=markdown').text
    assert literal(text) in result
    assert literal(text).startswith('```````text\n')
    assert old['id'] not in result  # unapproved version excluded by snapshot selection


def test_export_format_validation_and_missing_snapshot(client):
    cid, old = setup(client)
    approve(client, old)
    eid = client.post(f'/api/campaigns/{cid}/exports').json()['id']
    assert client.get('/api/exports/'+eid+'?format=html').status_code == 422
    assert client.get('/api/exports/missing?format=markdown').status_code == 404

