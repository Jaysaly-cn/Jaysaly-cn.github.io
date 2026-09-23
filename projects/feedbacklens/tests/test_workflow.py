import pytest
from fastapi.testclient import TestClient
from app.main import create_app

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'test.db')) as c:
        r=c.post('/api/imports',content='source_id,channel,text\na,app,希望导出功能，也希望加快加载。\nb,email,不希望导出功能。\n'.encode())
        assert r.status_code==201
        yield c

def add(c,theme='导出'):
    return c.post('/api/annotations',json={'source_id':'a','theme':theme,'kind':'request','quote':'希望导出功能'}).json()

def confirm(c,a):
    return c.post('/api/annotations/'+a['id']+'/review',json={'version':a['version'],'decision':'confirmed','note':'核对原文与归类内容'})

def test_report_unique_counts_and_frozen(client):
    a=add(client);confirm(client,a)
    confirm(client,add(client))
    confirm(client,add(client,'另一主题'))
    report=client.post('/api/reports',json={'title':'开发验收','note':'合成数据，仅验证统计口径'}).json()
    assert report['total_feedback']==2 and report['confirmed_feedback']==1
    assert [t['feedback_count'] for t in report['themes']]==[1,1]
    assert len(report['evidence'])==3
    client.post('/api/annotations/'+a['id']+'/review',json={'version':2,'decision':'rejected','note':'发现归类需要重新核对'})
    client.post('/api/imports',content='source_id,channel,text\nc,web,新的反馈记录。\n'.encode())
    assert client.get('/api/reports/'+report['id']).json()==report

def test_drafts_excluded_and_review_conflict(client):
    a=add(client)
    report=client.post('/api/reports',json={'title':'草稿排除','note':'尚未完成审核的记录'}).json()
    assert report['confirmed_feedback']==0
    assert confirm(client,a).status_code==200
    assert confirm(client,a).status_code==409

def test_wrong_quote_rejected(client):
    assert client.post('/api/annotations',json={'source_id':'a','theme':'导出','kind':'request','quote':'不在原文中的引用'}).status_code==422
    assert client.get('/api/annotations').json()==[]

def test_cross_origin(client):
    assert client.get('/api/feedback',headers={'Origin':'https://evil.test'}).status_code==403

def test_revision_requires_new_approval_and_retains_old_report(client):
    a=add(client);confirm(client,a)
    report=client.post('/api/reports',json={'title':'修订前报告','note':'保留当时已确认的归类'}).json()
    payload={'theme':'导出能力','kind':'request','quote':'希望导出功能','version':2,'note':'修正为更明确的主题'}
    result=client.post('/api/annotations/'+a['id']+'/revise',json=payload)
    assert result.status_code==200 and result.json()['state']=='draft'
    assert client.post('/api/annotations/'+a['id']+'/revise',json=payload).status_code==409
    history=client.get('/api/annotations/'+a['id']+'/history').json()
    assert len(history)==2 and 'previous' in history[-1]['snapshot']
    assert client.get('/api/reports/'+report['id']).json()==report
    latest=client.post('/api/reports',json={'title':'修订后报告','note':'待确认修订不参与统计'}).json()
    assert latest['confirmed_feedback']==0

def test_bad_revision_does_not_change_annotation(client):
    a=add(client)
    r=client.post('/api/annotations/'+a['id']+'/revise',json={'theme':'其他主题','kind':'other','quote':'引用不存在','version':1,'note':'测试错误引用不能入库'})
    assert r.status_code==422
    assert client.get('/api/annotations').json()[0]==a
