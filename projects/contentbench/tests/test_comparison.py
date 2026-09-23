from test_workflow import client, setup, COPY, approve


def revised(client, old, **changes):
    data={k:v for k,v in COPY.items() if k!='channel'}
    data.update(expected_revision=old['id'],**changes)
    response=client.post('/api/drafts/'+old['draft_id']+'/revisions',json=data)
    assert response.status_code==201
    return response.json()


def diff(client,old,new):
    return client.get('/api/drafts/'+old['draft_id']+'/compare',params={'before':old['id'],'after':new['id']})


def test_comparison_reconstructs_exact_text_and_fact_changes(client):
    cid,old=setup(client)
    new=revised(client,old,title='新的标题',body='支持添加任务。\n示例产品，仅供学习',fact_ids=['F1'])
    result=diff(client,old,new).json()
    for field in ('title','body'):
        assert ''.join(x['before'] for x in result['changes'][field])==old[field]
        assert ''.join(x['after'] for x in result['changes'][field])==new[field]
    assert result['facts_added']==['F1'] and result['facts_removed']==['F2']
    assert result['before']['state']==result['after']['state']=='draft'


def test_comparison_cannot_mix_drafts_even_within_campaign(client):
    cid,old=setup(client)
    other=client.post(f'/api/campaigns/{cid}/drafts',json=COPY).json()
    assert diff(client,old,other).status_code==404
    _,foreign=setup(client)
    assert diff(client,old,foreign).status_code==404


def test_comparison_preserves_approval_and_export_and_shows_new_blockers(client):
    cid,old=setup(client);approve(client,old)
    exported=client.post(f'/api/campaigns/{cid}/exports').json()
    new=revised(client,old,body='保证提升效率。')
    result=diff(client,old,new).json()
    assert result['before']['state']=='approved' and result['after']['state']=='draft'
    assert result['before']['checks']['blockers']==[]
    assert {x['code'] for x in result['after']['checks']['blockers']}=={'forbidden','required'}
    assert client.get('/api/exports/'+exported['id']).json()==exported
    assert client.post(f'/api/campaigns/{cid}/exports').status_code==409


def test_same_version_and_reverse_comparison(client):
    cid,old=setup(client);new=revised(client,old,body='示例产品，仅供学习')
    same=diff(client,old,old).json()
    assert all(p['operation']=='equal' for parts in same['changes'].values() for p in parts)
    reverse=diff(client,new,old).json()
    assert ''.join(p['after'] for p in reverse['changes']['body'])==old['body']
