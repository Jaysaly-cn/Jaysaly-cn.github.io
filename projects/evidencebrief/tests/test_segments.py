import pytest
from fastapi.testclient import TestClient
from app import model, segments
from app.main import create_app
from test_research import client, project, source


def enable(monkeypatch):
    monkeypatch.setenv('EB_MODEL','local-test')
    monkeypatch.setenv('EB_MODEL_BASE_URL','http://127.0.0.1:8771/v1')


@pytest.mark.parametrize('length',[10,3600,3601,100000])
def test_plan_covers_every_character_with_bounded_overlap(length):
    text=('段落。\n'*20000)[:length]
    windows=segments.plan(text)
    assert windows[0]['start']==0 and windows[-1]['end']==len(text)
    assert all(0<w['end']-w['start']<=3600 for w in windows)
    assert all(b['start']==a['end']-240 for a,b in zip(windows,windows[1:]))
    assert segments.covered(windows)==len(text)
    assert segments.covered(windows+windows)==len(text)


def test_tail_processed_offsets_and_cached_retry(client,monkeypatch):
    enable(monkeypatch);pid=project(client)
    text='背景资料。'*800+'Alpha 团队版每月 19 元。'
    s=source(client,pid,content=text);base=f'/api/projects/{pid}/sources/{s["id"]}'
    calls=[]
    async def suggest(src,dims):
        calls.append(src['content'])
        return [{'dimension':'价格','statement':'团队版每月19元','quote':'Alpha 团队版每月 19 元。'}] if 'Alpha' in src['content'] else []
    monkeypatch.setattr(model,'suggest',suggest)
    plan=client.get(base+'/segments').json()
    for w in plan['segments']:
        assert client.post(base+f'/suggest?segment={w["index"]}').status_code==201
    state=client.get(base+'/segments').json()
    assert state['complete'] and state['covered_characters']==len(text)
    claims=client.get('/api/projects/'+pid).json()['claims']
    assert len(claims)==1 and claims[0]['quote_start']==text.index('Alpha') and claims[0]['state']=='draft'
    assert client.post(base+'/suggest?segment=1').json()['cached']
    assert len(calls)==len(plan['segments'])
    report=client.post(f'/api/projects/{pid}/reports').json()
    assert report['snapshot']['sources'][0]['extraction_coverage']['complete']
    assert f'{len(text)}/{len(text)} 字符' in report['markdown']


def test_failed_segment_can_retry_without_losing_success(client,monkeypatch):
    enable(monkeypatch);pid=project(client);s=source(client,pid,content='背景资料。'*800+'最后一段价格资料。')
    base=f'/api/projects/{pid}/sources/{s["id"]}'
    async def empty(*args):return []
    monkeypatch.setattr(model,'suggest',empty)
    assert client.post(base+'/suggest?segment=0').status_code==201
    async def broken(*args):raise ValueError('synthetic failure')
    monkeypatch.setattr(model,'suggest',broken)
    assert client.post(base+'/suggest?segment=1').status_code==502
    state=client.get(base+'/segments').json()
    assert [w['state'] for w in state['segments']]==['success','failed']
    assert not state['complete']
    monkeypatch.setattr(model,'suggest',empty)
    assert client.post(base+'/suggest?segment=1').status_code==201
    state=client.get(base+'/segments').json()
    assert state['complete'] and state['segments'][1]['attempts']==2


def test_quote_outside_current_segment_rejected(client,monkeypatch):
    enable(monkeypatch);pid=project(client);s=source(client,pid,content='Alpha 团队版每月 19 元。'+'背景资料。'*1000)
    async def wrong(*args):return [{'dimension':'价格','statement':'团队版每月19元','quote':'Alpha 团队版每月 19 元。'}]
    monkeypatch.setattr(model,'suggest',wrong)
    base=f'/api/projects/{pid}/sources/{s["id"]}'
    assert client.post(base+'/suggest?segment=1').status_code==502
    assert client.get('/api/projects/'+pid).json()['claims']==[]


def test_ambiguous_quote_inside_segment_rejected(client,monkeypatch):
    enable(monkeypatch);pid=project(client);s=source(client,pid,content='每月19元。每月19元。所有内容均为合成。')
    async def ambiguous(*args):return [{'dimension':'价格','statement':'每月19元','quote':'每月19元。'}]
    monkeypatch.setattr(model,'suggest',ambiguous)
    assert client.post(f'/api/projects/{pid}/sources/{s["id"]}/suggest').status_code==502


def test_invalid_index_and_archived_source(client,monkeypatch):
    enable(monkeypatch);pid=project(client);s=source(client,pid)
    base=f'/api/projects/{pid}/sources/{s["id"]}'
    assert client.post(base+'/suggest?segment=99').status_code==422
    assert client.post(base+'/suggest?segment=-1').status_code==422
    client.patch(base,json={'archived':True})
    assert client.post(base+'/suggest').status_code==409


def test_segment_progress_survives_restart(tmp_path,monkeypatch):
    enable(monkeypatch)
    async def empty(*args):return []
    monkeypatch.setattr(model,'suggest',empty)
    path=tmp_path/'persistent.db'
    with TestClient(create_app(path)) as c:
        pid=project(c);s=source(c,pid);base=f'/api/projects/{pid}/sources/{s["id"]}'
        c.post(base+'/suggest')
    with TestClient(create_app(path)) as c:
        assert c.get(base+'/segments').json()['complete']
