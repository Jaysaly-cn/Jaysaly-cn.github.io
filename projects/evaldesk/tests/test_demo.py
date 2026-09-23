import json
import os
import time
from types import SimpleNamespace
from uuid import uuid4
from fastapi.testclient import TestClient
import demo
import jobs
import store


def test_visitors_isolate_suites_reviews_reports_and_jobs(tmp_path):
    app = demo.create_demo_app(tmp_path)
    with TestClient(app) as a, TestClient(app) as b:
        assert a.get('/').status_code == b.get('/').status_code == 200
        one = a.get('/api/suites').json()[0]
        two = b.get('/api/suites').json()[0]
        assert one['suite_id'] != two['suite_id']
        assert b.get('/api/suites/'+one['suite_id']+'/versions').status_code == 404
        rid = a.get('/api/runs').json()[0]['id']
        review = {'version':0,'decision':'rejected','note':'这条输出未遵守标签约束','reviewer':'访客A'}
        assert a.post(f'/api/runs/{rid}/cells/0:1/reviews',json=review).status_code == 201
        other = b.get('/api/runs/'+rid).json()
        assert all(c['review']['version']==0 for c in other['cells'])
        report = a.post(f'/api/runs/{rid}/reports',json={'title':'访客报告','note':'只是合成资料复核记录'}).json()
        assert b.get('/api/reports/'+report['id']).status_code == 404
        assert b.get('/api/jobs/unknown/diagnostics').status_code == 404


def test_limits_idempotency_and_global_active_job(tmp_path,monkeypatch):
    monkeypatch.setattr(jobs.subprocess,'Popen',lambda *a,**k:SimpleNamespace(pid=os.getpid()))
    app=demo.create_demo_app(tmp_path)
    with TestClient(app) as client:
        client.get('/')
        suite=client.get('/api/suites').json()[0]
        payload={'suite_id':suite['suite_id'],'version':1,'request_key':uuid4().hex}
        first=client.post('/api/jobs',json=payload);assert first.status_code==202
        assert client.post('/api/jobs',json=payload).json()['id']==first.json()['id']
        payload['request_key']=uuid4().hex
        assert client.post('/api/jobs',json=payload).status_code==429
        session=next(iter(app.state.demo_sessions.values()))
        assert session['jobs']==1
        with store.connect(session['path']) as db:db.execute("UPDATE jobs SET state='failed'")
        assert client.post('/api/jobs',json=payload).status_code==202
        with store.connect(session['path']) as db:db.execute("UPDATE jobs SET state='failed'")
        payload['request_key']=uuid4().hex
        assert client.post('/api/jobs',json=payload).status_code==429


def test_expired_active_job_directory_retained_then_cleaned(tmp_path,monkeypatch):
    stamp=[0]
    monkeypatch.setattr(jobs.subprocess,'Popen',lambda *a,**k:SimpleNamespace(pid=os.getpid()))
    app=demo.create_demo_app(tmp_path,lambda:stamp[0])
    unrelated=tmp_path/'keep.txt';unrelated.write_text('keep')
    with TestClient(app) as client:
        client.get('/')
        session=next(iter(app.state.demo_sessions.values()))
        suite=client.get('/api/suites').json()[0]
        client.post('/api/jobs',json={'suite_id':suite['suite_id'],'version':1,'request_key':uuid4().hex})
        stamp[0]=1801
        assert client.get('/api/jobs').status_code==401
        assert session['directory'].exists()
        with store.connect(session['path']) as db:db.execute("UPDATE jobs SET state='finished'")
        client.get('/api/jobs')
        assert not session['directory'].exists() and unrelated.exists()


def test_guardrails_cannot_be_bypassed_by_header(tmp_path):
    with TestClient(demo.create_demo_app(tmp_path)) as client:
        assert client.get('/api/runs',headers={'isolated_demo_session':'true'}).status_code==401
        assert client.get('/',headers={'host':'evil.example'}).status_code==403
        assert client.get('/docs').status_code==404
        client.get('/')
        assert client.post('/api/jobs',headers={'origin':'https://evil.example'},json={}).status_code==403
        assert client.post('/api/suites',content=b'x'*40001).status_code==413
        assert client.post('/api/jobs',json=[]).status_code==422
        suite=client.get('/api/suites').json()[0]
        updated=suite['suite']
        for i in range(3):
            case=dict(updated['cases'][0],id='extra-'+str(i));updated['cases'].append(case)
        saved=client.put('/api/suites/'+suite['suite_id'],json={'suite':updated,'version':1,'note':'增加样例以验证演示调用上限'}).json()
        assert saved['version']==2
        assert client.post('/api/jobs',json={'suite_id':suite['suite_id'],'version':2,'request_key':uuid4().hex}).status_code==422


def test_restart_orphan_blocks_other_visitor_until_worker_finishes(tmp_path,monkeypatch):
    monkeypatch.setattr(jobs.subprocess,'Popen',lambda *a,**k:SimpleNamespace(pid=os.getpid()))
    first=demo.create_demo_app(tmp_path)
    with TestClient(first) as a:
        a.get('/')
        suite=a.get('/api/suites').json()[0]
        assert a.post('/api/jobs',json={'suite_id':suite['suite_id'],'version':1,'request_key':uuid4().hex}).status_code==202
        old=next(iter(first.state.demo_sessions.values()))
    earlier=time.time()-demo.TTL-400
    os.utime(old['directory'],(earlier,earlier))
    with TestClient(demo.create_demo_app(tmp_path)) as b:
        b.get('/')
        assert old['directory'].exists()
        suite=b.get('/api/suites').json()[0]
        assert b.post('/api/jobs',json={'suite_id':suite['suite_id'],'version':1,'request_key':uuid4().hex}).status_code==429
        with store.connect(old['path']) as db:db.execute("UPDATE jobs SET state='finished'")
        # SQLite journal creation/removal updates the directory mtime. Orphans
        # are retained for the grace period after that final filesystem activity.
        os.utime(old['directory'],(earlier,earlier))
        b.get('/api/jobs')
        assert not old['directory'].exists()
