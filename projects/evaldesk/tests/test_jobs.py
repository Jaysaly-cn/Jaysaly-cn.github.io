import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4
import psutil
import pytest
import jobs
import store


def setup(tmp_path, monkeypatch):
    path = tmp_path / 'db.sqlite3'
    store.initialize(path)
    jobs.initialize(path)
    suite = json.loads((store.ROOT / 'samples/ticket-routing.json').read_text(encoding='utf-8'))
    with store.connect(path) as db:
        saved = store.save_suite(db, suite, '创建可复用评测基线')
    monkeypatch.setattr(jobs.subprocess, 'Popen', lambda *a, **k: SimpleNamespace(pid=os.getpid()))
    return path, saved


def test_idempotency_live_process_and_version_binding(tmp_path, monkeypatch):
    path, suite = setup(tmp_path, monkeypatch)
    key = uuid4().hex
    job = jobs.launch(path, suite['suite_id'], 1, key)
    assert jobs.launch(path, suite['suite_id'], 1, key)['id'] == job['id']
    with pytest.raises(RuntimeError, match='活动'):
        jobs.launch(path, suite['suite_id'], 1, uuid4().hex)
    with store.connect(path) as db:
        changed = dict(suite['suite'], name='新版名称')
        store.save_suite(db, changed, '调整测试集名称', suite['suite_id'], 1)
    with store.connect(path) as db:
        jobs.refresh(db, path)
        row = db.execute('SELECT * FROM jobs').fetchone()
        assert row['state'] == 'starting'
        assert json.loads(row['snapshot'])['name'] != '新版名称'
    with pytest.raises(RuntimeError, match='another suite version'):
        jobs.launch(path, suite['suite_id'], 2, key)


def test_execution_auto_imports_and_keeps_failed_assertions(tmp_path, monkeypatch):
    path, suite = setup(tmp_path, monkeypatch)
    job = jobs.launch(path, suite['suite_id'], 1, uuid4().hex)
    def run(value, directory, **kwargs):
        dest = directory / kwargs['run_id']
        shutil.copytree(store.ROOT / 'artifacts/engine-spike', dest)
        manifest = json.loads((dest / 'manifest.json').read_text(encoding='utf-8'))
        manifest.update(id=kwargs['run_id'], suite_version=kwargs['provenance'])
        (dest / 'manifest.json').write_bytes(store.encode(manifest))
        return dest
    monkeypatch.setattr(jobs.engine, 'run', run)
    jobs.execute(path, job['id'])
    with store.connect(path) as db:
        row = db.execute('SELECT * FROM jobs').fetchone()
        assert row['state'] == 'finished'
        result = store.get_run(db, row['run_id'])
        assert result['manifest']['suite_version']['version'] == 1
        assert sum(m['assertion_failed'] for m in result['summary']) == 4
        assert all(c['review']['decision'] == 'pending' for c in result['cells'])


def test_worker_failure_is_terminal_and_retry_is_new_record(tmp_path, monkeypatch):
    path, suite = setup(tmp_path, monkeypatch)
    job = jobs.launch(path, suite['suite_id'], 1, uuid4().hex)
    def fail(*a, **k):
        raise RuntimeError('model unavailable')
    monkeypatch.setattr(jobs.engine, 'run', fail)
    jobs.execute(path, job['id'])
    with store.connect(path) as db:
        assert db.execute('SELECT state FROM jobs').fetchone()['state'] == 'failed'
    retry = jobs.launch(path, suite['suite_id'], 1, uuid4().hex)
    assert retry['id'] != job['id']
    with store.connect(path) as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 2


def test_recovery_checks_engine_and_never_restarts_unknown(tmp_path, monkeypatch):
    path, suite = setup(tmp_path, monkeypatch)
    job = jobs.launch(path, suite['suite_id'], 1, uuid4().hex)
    with store.connect(path) as db:
        db.execute("UPDATE jobs SET state='running',worker_created=-1,engine_pid=?,engine_created=?", (os.getpid(), psutil.Process().create_time()))
        jobs.refresh(db, path)
        assert db.execute('SELECT state FROM jobs').fetchone()[0] == 'running'
        db.execute('UPDATE jobs SET engine_created=-1')
        jobs.refresh(db, path)
        assert db.execute('SELECT state FROM jobs').fetchone()[0] == 'interrupted'
        db.execute("UPDATE jobs SET state='running',engine_pid=NULL")
        folder = jobs.folder(path) / job['id']
        folder.mkdir(parents=True)
        (folder / 'manifest.json').write_text('{}')
        jobs.refresh(db, path)
        assert db.execute('SELECT state FROM jobs').fetchone()[0] == 'execution_unknown'
        assert db.execute('SELECT completed_at FROM jobs').fetchone()[0] is None
    with pytest.raises(RuntimeError):
        jobs.launch(path, suite['suite_id'], 1, uuid4().hex)


def recovery_fixture(tmp_path, monkeypatch):
    path, suite = setup(tmp_path, monkeypatch)
    job = jobs.launch(path, suite['suite_id'], 1, uuid4().hex)
    dest = jobs.folder(path) / job['id']
    shutil.copytree(store.ROOT / 'artifacts/engine-spike', dest)
    m = json.loads((dest / 'manifest.json').read_text(encoding='utf-8'))
    m.update(id=job['id'], suite_version={'suite_id': suite['suite_id'], 'version': 1, 'sha256': suite['sha256']})
    (dest / 'manifest.json').write_bytes(store.encode(m))
    with store.connect(path) as db:
        db.execute("UPDATE jobs SET state='interrupted',error='importer stopped',worker_created=-1,engine_pid=?,engine_created=-1", (os.getpid(),))
    return path, job, dest


def test_recover_import_is_atomic_audited_and_never_calls_model(tmp_path, monkeypatch):
    path, job, _ = recovery_fixture(tmp_path, monkeypatch)
    def forbidden(*a, **k):
        raise AssertionError('recovery must not run the model')
    monkeypatch.setattr(jobs.engine, 'run', forbidden)
    recovered = jobs.recover(path, job['id'])
    assert recovered['state'] == 'finished' and recovered['run_id'] == job['id']
    assert jobs.recover(path, job['id']) == recovered
    with store.connect(path) as db:
        assert len(store.get_run(db, job['id'])['cells']) == 8
        events = db.execute('SELECT * FROM job_events').fetchall()
        assert len(events) == 1
        assert json.loads(events[0]['detail'])['previous_error'] == 'importer stopped'


def test_recover_rejects_live_unknown_and_mismatched_evidence(tmp_path, monkeypatch):
    path, job, dest = recovery_fixture(tmp_path, monkeypatch)
    real_alive = jobs.alive
    for status in (True, None):
        monkeypatch.setattr(jobs, 'alive', lambda *a: status)
        with pytest.raises(RuntimeError):
            jobs.recover(path, job['id'])
    monkeypatch.setattr(jobs, 'alive', real_alive)
    m = json.loads((dest / 'manifest.json').read_text(encoding='utf-8'))
    m['suite_version']['version'] = 2
    (dest / 'manifest.json').write_bytes(store.encode(m))
    with pytest.raises(ValueError, match='版本不一致'):
        jobs.recover(path, job['id'])
    with store.connect(path) as db:
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM job_events').fetchone()[0] == 0
        assert db.execute('SELECT state FROM jobs').fetchone()[0] == 'interrupted'


def test_diagnostics_tail_is_bounded_and_missing_evidence_stays_unmodified(tmp_path, monkeypatch):
    path, job, dest = recovery_fixture(tmp_path, monkeypatch)
    (dest / 'engine.log').write_bytes(b'x' * 17000)
    d = jobs.diagnostics(path, job['id'])
    assert d['engine_log']['truncated'] and len(d['engine_log']['text']) == 16000
    assert d['worker_alive'] is False and d['engine_alive'] is False
    with pytest.raises(ValueError, match='校验失败'):
        jobs.recover(path, job['id'])
    with store.connect(path) as db:
        assert db.execute('SELECT run_id FROM jobs').fetchone()[0] is None
