import json
import pytest
import httpx
from fastapi.testclient import TestClient
from app.main import create_app
from app import model
from app.store import connect
from test_research import client,project,source
from test_segments import enable


def test_plan_resume_failure_and_no_automatic_approval(client,monkeypatch):
    enable(monkeypatch);pid=project(client);a=source(client,pid)
    b=source(client,pid,entity='Beta',content='Beta 标准版每月29元，支持纯文本导入。此处为合成测试材料。')
    batch=client.post(f'/api/projects/{pid}/batches',json={'source_ids':[a['id'],b['id']]}).json()
    route=f'/api/projects/{pid}/batches/{batch["id"]}'
    assert len(batch['steps'])==2 and not client.get('/api/projects/'+pid).json()['claims']
    calls=[]
    async def suggest(src,dims):
        calls.append(src['entity'])
        if src['entity']=='Beta':raise ValueError('synthetic failure')
        return [{'dimension':'价格','statement':'Alpha团队版每月19元','quote':'Alpha 团队版每月 19 元。'}]
    monkeypatch.setattr(model,'suggest',suggest)
    assert client.post(route+'/next',json={}).json()['steps'][0]['state']=='success'
    assert client.post(route+'/next',json={}).json()['steps'][1]['state']=='failed'
    assert not client.post(route+'/next',json={}).json()['complete'] and calls==['Alpha','Beta']
    async def empty(*args):return []
    monkeypatch.setattr(model,'suggest',empty)
    done=client.post(route+'/next',json={'retry_failed':True}).json()
    assert done['complete'] and [s['attempts'] for s in done['steps']]==[1,2]
    claims=client.get('/api/projects/'+pid).json()['claims']
    assert len(claims)==1 and claims[0]['state']=='draft'


def test_pause_scope_archive_and_duplicate_guards(client,monkeypatch):
    enable(monkeypatch);pid=project(client);s=source(client,pid);other=project(client,title='另一项目')
    base=f'/api/projects/{pid}/batches'
    assert client.post(base,json={'source_ids':[s['id'],s['id']]}).status_code==422
    assert client.post(f'/api/projects/{other}/batches',json={'source_ids':[s['id']]}).status_code==404
    batch=client.post(base,json={'source_ids':[s['id']]}).json();route=base+'/'+batch['id']
    assert client.get(f'/api/projects/{other}/batches/'+batch['id']).status_code==404
    client.post(route+'/pause',json={'paused':True})
    assert client.post(route+'/next',json={}).status_code==409
    client.post(route+'/pause',json={'paused':False})
    client.patch(f'/api/projects/{pid}/sources/'+s['id'],json={'archived':True})
    assert client.post(route+'/next',json={}).json()['steps'][0]['state']=='failed'


def test_restart_recovers_step_without_duplicating_committed_segment(tmp_path,monkeypatch):
    enable(monkeypatch);path=str(tmp_path/'restart.db')
    async def empty(*args):return []
    monkeypatch.setattr(model,'suggest',empty)
    with TestClient(create_app(path)) as c:
        pid=project(c);s=source(c,pid)
        batch=c.post(f'/api/projects/{pid}/batches',json={'source_ids':[s['id']]}).json()
        # Simulate interruption after the segment committed but before the plan checkpoint.
        c.post(f'/api/projects/{pid}/sources/{s["id"]}/suggest')
        batch['steps'][0].update(state='running',attempts=1)
        with connect(path) as db:db.execute('UPDATE extraction_batches SET steps=? WHERE id=?',(json.dumps(batch['steps']),batch['id']))
    async def forbidden(*args):raise AssertionError('Successful segment must be reused')
    monkeypatch.setattr(model,'suggest',forbidden)
    with TestClient(create_app(path)) as c:
        route=f'/api/projects/{pid}/batches/{batch["id"]}'
        assert c.get(route).json()['steps'][0]['state']=='interrupted'
        done=c.post(route+'/next',json={}).json()
        assert done['complete'] and done['steps'][0]['cached']


def test_cli_no_empty_bearer_and_failed_step_has_nonzero_exit(monkeypatch):
    from app import agent_cli
    monkeypatch.delenv('EVIDENCEBRIEF_ACCESS_TOKEN',raising=False)
    monkeypatch.setattr('sys.argv',['agent_cli','run','p','--batch','b'])
    original_client=httpx.Client
    def handle(request):
        assert 'authorization' not in request.headers
        failed=request.method=='POST'
        return httpx.Response(200,json={'id':'b','paused':False,'complete':False,'steps':[{'state':'failed' if failed else 'pending','attempts':int(failed)}]})
    monkeypatch.setattr(agent_cli.httpx,'Client',lambda **kwargs:original_client(**kwargs,transport=httpx.MockTransport(handle)))
    with pytest.raises(SystemExit) as caught:agent_cli.main()
    assert caught.value.code==2
