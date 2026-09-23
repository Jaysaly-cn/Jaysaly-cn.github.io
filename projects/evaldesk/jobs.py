"""One active local evaluation per database. No automatic retries."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import psutil
import engine
import store

ACTIVE = ('starting', 'running', 'execution_unknown')


def initialize(path):
    with store.connect(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS jobs(
          id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
          suite_id TEXT NOT NULL, suite_version INTEGER NOT NULL, suite_sha256 TEXT NOT NULL,
          snapshot TEXT NOT NULL, state TEXT NOT NULL, worker_pid INTEGER, worker_created REAL,
          engine_pid INTEGER, engine_created REAL, error TEXT, created_at TEXT NOT NULL,
          completed_at TEXT, run_id TEXT)''')
        db.execute('''CREATE TABLE IF NOT EXISTS job_events(
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
          action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL)''')


def alive(pid, created):
    if pid is None:
        return False
    try:
        p = psutil.Process(pid)
        return p.create_time() == created and p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return None


def folder(path):
    return Path(path).resolve().parent / 'job-runs'


def refresh(db, path):
    for row in db.execute("SELECT * FROM jobs WHERE state IN ('starting','running','execution_unknown')").fetchall():
        worker = alive(row['worker_pid'], row['worker_created'])
        child = alive(row['engine_pid'], row['engine_created'])
        if worker is True or child is True:
            continue
        if worker is None or child is None:
            state, reason = 'execution_unknown', '无法读取进程状态，不自动重试。'
        elif row['engine_pid'] is None and (folder(path) / row['id'] / 'manifest.json').exists():
            state, reason = 'execution_unknown', '引擎已创建记录但缺少进程身份，需要人工核查。'
        else:
            state, reason = 'interrupted', '执行进程已退出且没有终态记录；保留原任务，不自动重试。'
        completed = None if state == 'execution_unknown' else store.now()
        db.execute('UPDATE jobs SET state=?,error=?,completed_at=? WHERE id=?', (state, reason, completed, row['id']))


def get_job(db, job_id):
    row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    if not row:
        raise KeyError('job not found')
    return row


def log_tail(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError('log path escapes job directory')
    if not path.is_file():
        return {'text': '', 'present': False, 'truncated': False}
    with path.open('rb') as stream:
        size = stream.seek(0, 2)
        stream.seek(max(0, size - 16000))
        raw = stream.read(16000)
    return {'text': raw.decode('utf-8', errors='replace'), 'present': True, 'truncated': size > 16000}


def diagnostics(path, job_id):
    with store.connect(path) as db:
        row = get_job(db, job_id)
        events = [dict(r) for r in db.execute('SELECT * FROM job_events WHERE job_id=? ORDER BY created_at', (job_id,))]
        return {'job': public(row), 'worker_alive': alive(row['worker_pid'], row['worker_created']),
                'engine_alive': alive(row['engine_pid'], row['engine_created']),
                'worker_log': log_tail(Path(path).parent / 'job-logs' / (job_id + '.log'), Path(path).parent),
                'engine_log': log_tail(folder(path) / job_id / 'engine.log', folder(path)),
                'events': events}


def recover(path, job_id):
    """Import completed evidence without invoking an engine or erasing the failure."""
    with store.connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        row = get_job(db, job_id)
        if row['run_id'] and row['state'] in ('finished', 'failed'):
            return public(row)
        if alive(row['worker_pid'], row['worker_created']) is not False or alive(row['engine_pid'], row['engine_created']) is not False:
            raise RuntimeError('进程仍在运行或无法核实状态，不能恢复导入。')
        if row['engine_pid'] is None:
            raise RuntimeError('缺少引擎进程身份，不能据此断言已停止；请人工核查。')
        try:
            evidence = store.load_evidence(folder(path) / job_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError('结果证据尚不完整或校验失败，未改变任务：' + str(exc)) from exc
        manifest = evidence['manifest']
        expected = {'suite_id': row['suite_id'], 'version': row['suite_version'], 'sha256': row['suite_sha256']}
        if manifest['id'] != job_id or manifest.get('suite_sha256') != row['suite_sha256'] or manifest.get('suite_version') != expected or evidence['suite'] != json.loads(row['snapshot']):
            raise ValueError('结果与任务绑定的测试集版本不一致，拒绝导入。')
        run_id = store.insert_snapshot(db, evidence)
        state = 'finished' if manifest['status'] == 'finished' else 'failed'
        error = None if state == 'finished' else manifest.get('error', '引擎失败记录已恢复，未重新调用模型。')
        detail = {'previous_state': row['state'], 'previous_error': row['error'], 'new_state': state, 'run_id': run_id}
        db.execute('INSERT INTO job_events VALUES(?,?,?,?,?)', (uuid4().hex, job_id, 'recover_import', json.dumps(detail, ensure_ascii=False), store.now()))
        db.execute('UPDATE jobs SET state=?,error=?,run_id=?,completed_at=? WHERE id=?', (state, error, run_id, store.now(), job_id))
        return public(get_job(db, job_id))


def public(row):
    result = dict(row)
    suite = json.loads(result.pop('snapshot'))
    result['name'] = suite['name']
    result['planned_calls'] = len(suite['cases']) * len(suite['prompts'])
    return result


def launch(path, suite_id, version, request_key):
    path = Path(path).resolve()
    with store.connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM jobs WHERE request_key=?', (request_key,)).fetchone()
        if old:
            if old['suite_id'] != suite_id or old['suite_version'] != version:
                raise RuntimeError('request key belongs to another suite version')
            return public(old)
        refresh(db, path)
        if db.execute("SELECT 1 FROM jobs WHERE state IN ('starting','running','execution_unknown')").fetchone():
            raise RuntimeError('已有活动或状态待核查的任务，请等待完成。')
        suite = store.get_suite(db, suite_id, version)
        job_id = uuid4().hex
        db.execute('''INSERT INTO jobs(id,request_key,suite_id,suite_version,suite_sha256,snapshot,state,created_at)
                    VALUES(?,?,?,?,?,?,'starting',?)''',
                   (job_id, request_key, suite_id, version, suite['sha256'], engine.encode(suite['suite']).decode(), store.now()))
        log_dir = path.parent / 'job-logs'
        log_dir.mkdir(exist_ok=True)
        try:
            with (log_dir / (job_id + '.log')).open('xb') as log:
                options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
                child = subprocess.Popen([sys.executable, str(engine.ROOT / 'jobs.py'), str(path), job_id],
                                         cwd=engine.ROOT, stdout=log, stderr=subprocess.STDOUT, **options)
                created = psutil.Process(child.pid).create_time()
            db.execute('UPDATE jobs SET worker_pid=?,worker_created=? WHERE id=?', (child.pid, created, job_id))
        except (OSError, psutil.Error) as exc:
            db.execute("UPDATE jobs SET state='failed',error=?,completed_at=? WHERE id=?", (str(exc), store.now(), job_id))
        return public(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())


def execute(path, job_id):
    try:
        with store.connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row['state'] != 'starting':
                return
            suite = json.loads(row['snapshot'])
            provenance = {'suite_id': row['suite_id'], 'version': row['suite_version'], 'sha256': row['suite_sha256']}
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (job_id,))
        def track(pid):
            created = psutil.Process(pid).create_time()
            with store.connect(path) as db:
                db.execute('UPDATE jobs SET engine_pid=?,engine_created=? WHERE id=?', (pid, created, job_id))
        result = engine.run(suite, folder(path), run_id=job_id, provenance=provenance, on_process=track)
        manifest = json.loads((result / 'manifest.json').read_text(encoding='utf-8'))
        run_id = store.import_run(result, path)
        state = 'finished' if manifest['status'] == 'finished' else 'failed'
        error = None if state == 'finished' else manifest.get('error', '引擎未产生完整结果；请查看本机运行日志。')
        with store.connect(path) as db:
            db.execute('UPDATE jobs SET state=?,error=?,run_id=?,completed_at=? WHERE id=?', (state, error, run_id, store.now(), job_id))
    except Exception as exc:
        with store.connect(path) as db:
            db.execute("UPDATE jobs SET state='failed',error=?,completed_at=? WHERE id=?", (str(exc)[:3000], store.now(), job_id))


if __name__ == '__main__':
    execute(Path(sys.argv[1]), sys.argv[2])
