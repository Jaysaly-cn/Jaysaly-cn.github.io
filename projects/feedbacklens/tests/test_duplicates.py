import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'duplicates.db')) as c:
        assert c.post('/api/imports',content='source_id,channel,text\na,app,希望导出功能。\nb,email,希望导出功能。\nc,web,不希望导出功能。\n'.encode()).status_code==201
        yield c

def decide(c,source='b',target='a',version=0):
    return c.post('/api/duplicates',json={'source_id':source,'target_id':target,'version':version,'note':'合成验收：核对同一记录重复收录'})

def report(c):
    return c.post('/api/reports',json={'title':'重复判断验收','note':'合成资料，不代表真实用户数量'}).json()

def confirm(c,source,theme):
    a=c.post('/api/annotations',json={'source_id':source,'theme':theme,'kind':'request','quote':'希望导出功能'}).json()
    assert c.post('/api/annotations/'+a['id']+'/review',json={'version':1,'decision':'confirmed','note':'核对合成资料原文证据'}).status_code==200

def test_explicit_decision_and_reversal_preserve_frozen_evidence(client):
    confirm(client,'a','导出功能');confirm(client,'b','导出功能');confirm(client,'b','另一个主题')
    before=report(client)
    assert before['total_feedback']==before['deduplicated_total_feedback']==3
    assert before['confirmed_feedback']==before['deduplicated_confirmed_feedback']==2
    assert decide(client).status_code==200
    frozen=report(client)
    assert frozen['total_feedback']==3 and frozen['deduplicated_total_feedback']==2
    assert frozen['confirmed_feedback']==2 and frozen['deduplicated_confirmed_feedback']==1
    themes={t['theme']:t for t in frozen['themes']}
    assert themes['导出功能']['feedback_count']==2
    assert themes['导出功能']['deduplicated_feedback_count']==1
    assert themes['另一个主题']['source_ids']==['b']
    assert themes['另一个主题']['representative_ids']==['a']
    assert len(frozen['evidence'])==3
    assert decide(client,target=None,version=1).status_code==200
    assert report(client)['deduplicated_total_feedback']==3
    assert client.get('/api/reports/'+frozen['id']).json()==frozen
    events=client.get('/api/duplicates/b/history').json()
    assert len(events)==2
    assert json.loads(events[-1]['snapshot'])['previous']['target_id']=='a'
    assert len(client.get('/api/feedback').json())==3

@pytest.mark.parametrize('source,target,code',[('a','a',422),('missing','a',404),('b','missing',404)])
def test_invalid_decisions_do_not_write(client,source,target,code):
    assert decide(client,source,target).status_code==code
    assert client.get('/api/duplicates').json()==[]
    assert client.get('/api/duplicates/'+source+'/history').json()==[]

def test_conflicts_chains_and_cycles_rejected_atomically(client):
    assert decide(client).status_code==200
    assert decide(client,target=None).status_code==409
    assert decide(client,source='a',target='b').status_code==422
    assert decide(client,source='a',target='c').status_code==422
    assert decide(client,source='c',target='b').status_code==422
    assert len(client.get('/api/duplicates').json())==1
    assert len(client.get('/api/duplicates/b/history').json())==1
    assert decide(client,target='c',version=1).status_code==200

def test_representative_does_not_need_its_own_annotation(client):
    confirm(client,'b','导出功能')
    assert decide(client).status_code==200
    result=report(client)
    assert result['confirmed_feedback']==result['deduplicated_confirmed_feedback']==1
    assert result['themes'][0]['source_ids']==['b']
    assert result['themes'][0]['representative_ids']==['a']
