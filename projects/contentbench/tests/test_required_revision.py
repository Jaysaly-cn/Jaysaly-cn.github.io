from test_workflow import client, setup, COPY, BRIEF, approve


def test_appended_disclosure_is_new_unapproved_revision(client):
    cid, _ = setup(client)
    old = client.post(f'/api/campaigns/{cid}/drafts', json={**COPY, 'body': '支持按周查看任务清单。'}).json()
    new = client.post('/api/drafts/'+old['draft_id']+'/revisions', json={
        'expected_revision': old['id'], 'title': old['title'], 'body': old['body']+'\n'+BRIEF['required_phrase'],
        'fact_ids': old['fact_ids']}).json()
    assert new['state'] == 'draft' and new['checks']['blockers'] == [] and new['origin'] == 'manual'
    detail = client.get('/api/campaigns/'+cid).json()
    versions = next(d for d in detail['drafts'] if d['id'] == old['draft_id'])['revisions']
    assert versions[1]['body'] == old['body']
    assert client.post(f'/api/campaigns/{cid}/exports').status_code == 409
    assert approve(client, new, facts_checked=False).status_code == 422


def test_appended_disclosure_does_not_bypass_sms_limit(client):
    cid, _ = setup(client)
    old = client.post(f'/api/campaigns/{cid}/drafts', json={**COPY, 'channel': '短信', 'body': '任'*65}).json()
    new = client.post('/api/drafts/'+old['draft_id']+'/revisions', json={
        'expected_revision': old['id'], 'title': old['title'], 'body': old['body']+'\n'+BRIEF['required_phrase'],
        'fact_ids': old['fact_ids']}).json()
    assert [x['code'] for x in new['checks']['blockers']] == ['length']
    assert approve(client, new).status_code == 422
