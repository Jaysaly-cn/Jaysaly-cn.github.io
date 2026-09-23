import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import model, segments


@pytest.mark.parametrize('text', ['😀'*8010, ('小林：讨论进展。\n'*900), '甲'*80000], ids=['emoji', 'paragraphs', 'maximum'])
def test_partition_has_no_gap_overlap_or_lost_unicode(text):
    plan=segments.split(text)
    assert ''.join(text[p['start']:p['end']] for p in plan)==text
    assert all(0<p['chars']<=4000 for p in plan)
    assert plan[0]['start']==0 and plan[-1]['end']==len(text)
    assert all(a['end']==b['start'] for a,b in zip(plan,plan[1:]))


def test_late_segment_retry_reuse_restart_and_atomic_failure(tmp_path,monkeypatch):
    monkeypatch.delenv('MEETINGACTIONS_ACCESS_TOKEN',raising=False)
    monkeypatch.setenv('MA_MODEL','test-local')
    monkeypatch.setenv('MA_MODEL_BASE_URL','http://127.0.0.1:8771/v1')
    path=tmp_path/'segments.db'
    prefix='背景讨论，无需行动。\n'*430
    quote='小林：我明天完成验收文档。'
    transcript=prefix+quote
    calls=[]
    async def extract(text, attendees):
        calls.append(text)
        return [{'title':'完成验收文档','quote':quote,'owner':'小林','due_phrase':'明天'}]
    monkeypatch.setattr(model,'extract',extract)
    with TestClient(create_app(path)) as c:
        meeting=c.post('/api/meetings',json={'title':'长会议','meeting_date':'2026-09-23','attendees':['小林'],'transcript':transcript}).json()
        mid=meeting['id'];url=f'/api/meetings/{mid}'
        plan=c.get(url).json()['segments'];last=len(plan)-1
        first=c.post(url+'/extract',json={'segment':last})
        assert first.status_code==201
        run=first.json();aid=run['actions'][0]['id']
        assert run['truncated'] is True
        assert calls==[transcript[plan[last]['start']:plan[last]['end']]]
        assert run['actions'][0]['quote_start']==len(prefix)
        assert run['actions'][0]['state']=='draft'
        repeat=c.post(url+'/extract',json={'segment':last}).json()
        assert repeat['reused'] and repeat['id']==run['id'] and len(calls)==1
        assert c.get(url).json()['segments'][0]['state']=='pending'
        assert c.post(url+'/extract',json={'segment':999}).status_code==422
        assert c.post(url+'/extract',json={'segment':-1}).status_code==422
        # A globally valid quotation cannot be falsely attributed to another segment.
        assert c.post(url+'/extract',json={'segment':0}).status_code==502
        assert len(c.get(url).json()['actions'])==1
        async def broken(*args):
            return [{'title':'新增草稿','quote':quote,'owner':'小林','due_phrase':'明天'},
                    {'title':'另一个草稿','quote':quote,'owner':'小王'}]
        monkeypatch.setattr(model,'extract',broken)
        assert c.post(url+'/extract',json={'segment':last,'rerun':True}).status_code==502
        result=c.get(url).json()
        assert len(result['actions'])==1 and result['actions'][0]['id']==aid
        assert result['segments'][last]['state']=='success'
        assert result['segments'][last]['last_attempt']=='failed'
        assert c.post(url+'/extract',json={'segment':last}).json()['reused']
        assert c.get('/api/board').json()==[]
    async def never(*args):
        raise AssertionError('Restart must reuse successful evidence')
    monkeypatch.setattr(model,'extract',never)
    with TestClient(create_app(path)) as c:
        assert c.post(url+'/extract',json={'segment':last}).json()['id']==run['id']
        assert len(c.get(url).json()['runs'])==3
