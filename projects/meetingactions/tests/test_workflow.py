import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import dates, exports, model

MEETING = {'title':'合成发布周会','meeting_date':'2026-09-23','attendees':['小林','小周'],
           'transcript':'小林：我明天完成接口文档。小周：我下周一检查发布清单。主持人：先不要发布公告。'}
CANDIDATE = {'title':'完成接口文档','quote':'小林：我明天完成接口文档。','owner':'小林','due_phrase':'明天'}


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.delenv('MEETINGACTIONS_ACCESS_TOKEN',raising=False)
    monkeypatch.delenv('MA_MODEL',raising=False)
    with TestClient(create_app(tmp_path/'test.db')) as c:
        yield c


def setup(c):
    r = c.post('/api/meetings',json=MEETING)
    assert r.status_code==201
    mid = r.json()['id']
    a = c.post(f'/api/meetings/{mid}/candidates',json=CANDIDATE)
    assert a.status_code==201
    return mid,a.json()


def confirm(c,a,**kw):
    return c.post(f'/api/actions/{a["id"]}/review',json={'version':a['version'],'decision':'confirm',
        'title':a['title'],'owner':'小林','due_date':'2026-09-24','note':'已核对原文并确认负责人及期限',**kw})


def move(c,a,state):
    return c.post(f'/api/actions/{a["id"]}/state',json={'version':a['version'],'state':state,'note':'验收步骤记录与成果说明'})


def test_review_board_and_state_machine(client):
    mid,a = setup(client)
    assert a['proposed_due']=='2026-09-24' and a['state']=='draft'
    assert not client.get('/api/board').json()
    assert 'BEGIN:VEVENT' not in client.get('/api/export/ics').text
    assert move(client,a,'done').status_code==409
    confirmed=confirm(client,a).json()
    assert confirm(client,a).status_code==409
    assert move(client,confirmed,'done').status_code==409
    active=move(client,confirmed,'in_progress').json()
    assert len(client.get('/api/board?overdue=true&today=2026-09-25').json())==1
    done=move(client,active,'done').json()
    assert done['completion_note']
    assert not client.get('/api/board?overdue=true&today=2026-09-25').json()
    assert 'BEGIN:VEVENT' not in client.get('/api/export/ics').text
    assert move(client,done,'open').json()['completion_note']==''
    assert len(client.get(f'/api/meetings/{mid}').json()['events'])>=5


@pytest.mark.parametrize('change',[{'quote':'未在记录里出现的任务'},{'owner':'小王'},
    {'owner':'小周'},{'due_phrase':'后天'}])
def test_source_anchors_reject_fabrication(client,change):
    mid,_=setup(client)
    assert client.post(f'/api/meetings/{mid}/candidates',json={**CANDIDATE,**change}).status_code==422
    assert len(client.get(f'/api/meetings/{mid}').json()['actions'])==1


def test_dedup_and_explicit_confirmation(client):
    mid,a=setup(client)
    duplicate=client.post(f'/api/meetings/{mid}/candidates',json=CANDIDATE).json()
    assert duplicate['id']==a['id'] and duplicate['deduplicated']
    assert confirm(client,a,owner='小王').status_code==422
    assert confirm(client,a,due_date=None).status_code==422
    assert confirm(client,a,no_deadline=True).status_code==422
    r=confirm(client,a,due_date=None,no_deadline=True).json()
    assert r['state']=='open' and not r['due_date']


def test_reschedule_is_audited_and_versioned(client):
    mid,a=setup(client)
    a=confirm(client,a).json()
    body={'version':a['version'],'owner':'小周','due_date':'2026-10-01','note':'确认转交与调整期限原因'}
    r=client.post(f'/api/actions/{a["id"]}/schedule',json=body)
    assert r.status_code==200 and r.json()['owner']=='小周'
    assert client.post(f'/api/actions/{a["id"]}/schedule',json=body).status_code==409
    events=client.get(f'/api/meetings/{mid}').json()['events']
    assert json.loads(events[0]['detail'])['previous_owner']=='小林'


def test_model_batch_rollback_and_trace(client,monkeypatch):
    mid,_=setup(client)
    monkeypatch.setenv('MA_MODEL','test-local')
    monkeypatch.setenv('MA_MODEL_BASE_URL','http://127.0.0.1:8771/v1')
    async def invalid(*args):
        return [{**CANDIDATE,'title':'一个新任务'},{**CANDIDATE,'quote':'不存在的逐字引用'}]
    monkeypatch.setattr(model,'extract',invalid)
    assert client.post(f'/api/meetings/{mid}/extract').status_code==502
    data=client.get(f'/api/meetings/{mid}').json()
    assert len(data['actions'])==1 and data['runs'][0]['state']=='failed'
    async def valid(*args):
        return [{**CANDIDATE,'title':'重新整理接口文档'}]
    monkeypatch.setattr(model,'extract',valid)
    r=client.post(f'/api/meetings/{mid}/extract').json()
    assert r['actions'][0]['state']=='draft'
    assert r['trace'][0]['processed']==len(MEETING['transcript'])
    assert not client.get('/api/board').json()


@pytest.mark.parametrize('phrase,expected',[('明天','2026-09-24'),('下周一','2026-09-28'),
    ('本周一','2026-09-21'),('尽快',''),('周五',''),('2026-02-30',''),('2026-12-31','2026-12-31')])
def test_date_resolution(phrase,expected):
    assert dates.resolve(phrase,'2026-09-23')==expected


def test_exports_are_escaped_folded_and_not_invitations(client):
    _,a=setup(client)
    a=confirm(client,a,title='=危险公式,'+'中文任务'*35).json()
    text=client.get('/api/export/csv').text
    assert "'=危险公式" in text
    ics=client.get('/api/export/ics').text
    assert 'METHOD:' not in ics and 'ATTENDEE:' not in ics
    assert f'UID:{a["id"]}@meetingactions.local' in ics and 'DTSTART;VALUE=DATE:20260924' in ics
    assert all(len(line.encode())<=75 for line in ics.split('\r\n'))
    assert 'DURATION:P1D' in ics
    assert exports.escape('x\r\nBEGIN:VEVENT')==r'x\nBEGIN:VEVENT'


def test_security_and_free_provider(client,monkeypatch):
    assert client.get('/api/board',headers={'Host':'evil.example'}).status_code==403
    assert client.post('/api/meetings',json=MEETING,headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/meetings',content='x'*400001).status_code==413
    monkeypatch.setenv('MA_MODEL_BASE_URL','https://openrouter.ai/api/v1')
    monkeypatch.setenv('MA_MODEL','paid-model')
    monkeypatch.setenv('MA_MODEL_API_KEY','test')
    with pytest.raises(ValueError):
        asyncio.run(model.extract('原文',[]))


def test_restart_keeps_confirmed_tasks(tmp_path):
    path=tmp_path/'persist.db'
    with TestClient(create_app(path)) as c:
        _,a=setup(c)
        confirm(c,a)
    with TestClient(create_app(path)) as c:
        assert c.get('/api/board').json()[0]['owner']=='小林'


def test_speaker_prefix_is_exact_evidence():
    from app.anchors import locate
    text='小林：我明天完成接口文档。小周：我下周一检查发布清单。'
    start,kind=locate(text,'我下周一检查发布清单','小周',['小林','小周'])
    assert text[start:].startswith('我下周一') and kind=='speaker_prefix'
    with pytest.raises(ValueError):
        locate(text,'我下周一检查发布清单','小林',['小林','小周'])


def test_duplicate_quote_requires_disambiguation():
    from app.anchors import locate
    text='小林：我明天完成文档。\n小周：我明天完成文档。'
    with pytest.raises(ValueError):
        locate(text,'我明天完成文档','',['小林','小周'])
    start,_=locate(text,'我明天完成文档','小周',['小林','小周'])
    assert start>text.index('\n')


def test_date_overflow_is_unresolved():
    assert dates.resolve('明天','9999-12-31')==''
