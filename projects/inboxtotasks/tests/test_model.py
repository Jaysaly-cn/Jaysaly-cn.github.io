import json
import pytest
from test_workflow import client
from test_ingest import mail
from app import model


def setup(c,monkeypatch,items,body='小林，请在周五前提交方案。'):
    monkeypatch.setenv('IT_MODEL','synthetic-test')
    monkeypatch.setattr(model,'configured',lambda:True)
    async def extract(source):return json.dumps({'actions':items},ensure_ascii=False)
    monkeypatch.setattr(model,'extract',extract)
    mid=c.post('/api/messages',content=mail(body).as_bytes()).json()['id']
    return f'/api/messages/{mid}'


GOOD={'title':'提交方案','quote':'小林，请在周五前提交方案。','owner':'小林','due_phrase':'周五前'}


def test_model_candidates_remain_unconfirmed_and_retry_deduplicates(client,monkeypatch):
    base=setup(client,monkeypatch,[GOOD])
    r=client.post(base+'/suggest');assert r.status_code==201
    t=r.json()['tasks'][0]
    assert t['state']=='draft' and t['owner']=='' and t['due_date'] is None
    assert t['proposed_owner']=='小林' and t['proposed_due']=='周五前'
    assert client.post(base+'/suggest').json()['tasks'][0]['id']==t['id']
    assert client.post('/api/exports').status_code==409
    assert len(client.get(base).json()['tasks'])==1


@pytest.mark.parametrize('bad',[{**GOOD,'quote':'不存在的引用'},{**GOOD,'owner':'张三'},{**GOOD,'due_phrase':'明天'}])
def test_invalid_batch_rolls_back_and_retains_raw(client,monkeypatch,bad):
    base=setup(client,monkeypatch,[GOOD,bad])
    assert client.post(base+'/suggest').status_code==502
    assert client.get(base).json()['tasks']==[]
    run=client.get(base+'/model-runs').json()[0]
    assert run['state']=='failed' and len(json.loads(run['raw'])['actions'])==2


def test_empty_results_are_not_error(client,monkeypatch):
    base=setup(client,monkeypatch,[],body='这件事不用做了。')
    assert client.post(base+'/suggest').json()['tasks']==[]
    assert client.get(base+'/model-runs').json()[0]['state']=='succeeded'


def test_long_mail_not_silently_truncated(client,monkeypatch):
    base=setup(client,monkeypatch,[],body='任务'*2100)
    assert client.post(base+'/suggest').status_code==422
    assert client.get(base+'/model-runs').json()==[]


def test_unconfigured_model_preserves_manual_flow(client,monkeypatch):
    monkeypatch.setattr(model,'configured',lambda:False)
    mid=client.post('/api/messages',content=mail().as_bytes()).json()['id']
    assert client.post(f'/api/messages/{mid}/suggest').status_code==503
