import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from test_research import client,project,source,claim,approve


def revise(c,pid,item,**kwargs):
    return c.post(f'/api/projects/{pid}/claims/{item["id"]}/revisions',json={
        'version':item['version'],'dimension':'价格','statement':'Alpha 团队版月费为19元',
        'quote':'Alpha 团队版每月 19 元。','note':'补齐适用套餐名称',**kwargs})


def test_revision_invalidates_approval_but_keeps_frozen_report(client):
    p=project(client);s=source(client,p);first=claim(client,p,s['id']).json()
    approved=approve(client,p,first).json()
    old=client.post(f'/api/projects/{p}/reports').json()
    changed=revise(client,p,approved)
    assert changed.status_code==201
    changed=changed.json()
    assert changed['version']==3 and changed['state']=='draft' and changed['review_note']==''
    assert len(client.get('/api/projects/'+p).json()['gaps'])==4
    assert client.get(f'/api/projects/{p}/reports/{old["id"]}').json()['markdown']==old['markdown']
    versions=client.get(f'/api/projects/{p}/claims/{first["id"]}/versions').json()['versions']
    assert [v['action'] for v in versions]==['created','reviewed','revised']
    assert versions[1]['snapshot']['state']=='approved'
    assert versions[2]['snapshot']['statement']=='Alpha 团队版月费为19元'
    assert approve(client,p,changed).status_code==200


def test_stale_revision_and_invalid_inputs_are_atomic(client):
    p=project(client);s=source(client,p);item=claim(client,p,s['id']).json()
    for changes,status in [({'version':3},409),({'quote':'虚构的价格文本'},422),
                           ({'quote_start':5},422),({'dimension':'不存在'},422),
                           ({'statement':item['statement']},422)]:
        assert revise(client,p,item,**changes).status_code==status
    history=client.get(f'/api/projects/{p}/claims/{item["id"]}/versions').json()
    assert history['current']['version']==1 and len(history['versions'])==1


def test_cross_project_and_archived_revision(client):
    p=project(client);other=project(client);s=source(client,p);item=claim(client,p,s['id']).json()
    assert revise(client,other,item).status_code==404
    assert client.get(f'/api/projects/{other}/claims/{item["id"]}/versions').status_code==404
    client.patch(f'/api/projects/{p}/sources/{s["id"]}',json={'archived':True})
    assert revise(client,p,item).status_code==409


def test_repeated_quote_requires_explicit_offset(client):
    p=project(client);text='第一处每月19元。第二处每月19元。'
    s=source(client,p,content=text);item=claim(client,p,s['id'],quote='第一处每月19元。').json()
    assert revise(client,p,item,quote='每月19元。').status_code==422
    offset=text.rfind('每月19元。')
    changed=revise(client,p,item,quote='每月19元。',quote_start=offset)
    assert changed.status_code==201 and changed.json()['quote_start']==offset


def test_migrated_claim_gets_honest_baseline(tmp_path):
    path=tmp_path/'migration.db'
    with TestClient(create_app(path)) as c:
        p=project(c);s=source(c,p);item=claim(c,p,s['id']).json()
    with sqlite3.connect(path) as db:
        db.execute('DELETE FROM claim_versions')
        db.execute('UPDATE claims SET version=7')
    with TestClient(create_app(path)) as c:
        item['version']=7
        assert revise(c,p,item).status_code==201
        history=c.get(f'/api/projects/{p}/claims/{item["id"]}/versions').json()['versions']
        assert [x['version'] for x in history]==[7,8]
        assert history[0]['action']=='baseline'
