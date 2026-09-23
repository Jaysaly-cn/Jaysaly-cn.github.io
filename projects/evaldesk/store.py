"""Import immutable engine evidence and append human review history."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from engine import ROOT, ENGINE_VERSION, compile_suite, encode

DB = ROOT / 'data/evaldesk.sqlite3'


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, imported_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reviews(run_id TEXT NOT NULL REFERENCES runs(id), cell_id TEXT NOT NULL,
          version INTEGER NOT NULL, decision TEXT NOT NULL, note TEXT NOT NULL, reviewer TEXT NOT NULL,
          created_at TEXT NOT NULL, PRIMARY KEY(run_id,cell_id,version));
        CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
          snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suites(id TEXT PRIMARY KEY, version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS suite_versions(suite_id TEXT NOT NULL REFERENCES suites(id), version INTEGER NOT NULL,
          snapshot TEXT NOT NULL, sha256 TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(suite_id,version));
        ''')


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def normalize(suite, payload):
    """Promptfoo v3: failureReason 1 is assertion failure even with `error`."""
    results = payload.get('results', {})
    if results.get('version') != 3 or not isinstance(results.get('results'), list):
        raise ValueError('unsupported promptfoo result format')
    expected = {(c, p) for c in range(len(suite['cases'])) for p in range(len(suite['prompts']))}
    cells = []
    for row in results['results']:
        ci, pi = row.get('testIdx'), row.get('promptIdx')
        if type(ci) is not int or type(pi) is not int or (ci, pi) not in expected:
            raise ValueError('duplicate or unknown result cell')
        expected.remove((ci, pi))
        case, prompt = suite['cases'][ci], suite['prompts'][pi]
        if row.get('testCase', {}).get('description') != case['id'] or row.get('prompt', {}).get('label') != prompt['id']:
            raise ValueError('result identity differs from suite snapshot')
        reason = row.get('failureReason')
        if type(reason) is not int or reason not in (0, 1, 2):
            raise ValueError('unknown failure reason')
        if row.get('success') is not (reason == 0):
            raise ValueError('inconsistent success status')
        response = row.get('response') or {}
        output = response.get('output')
        if output is not None and not isinstance(output, str):
            raise ValueError('expected text model output')
        if reason != 2 and output is None:
            raise ValueError('successful model call is missing output')
        cells.append({'id': f'{ci}:{pi}', 'case_index': ci, 'prompt_index': pi,
                      'case_id': case['id'], 'prompt_id': prompt['id'],
                      'status': ('passed', 'assertion_failed', 'call_error')[reason],
                      'output': output, 'reason': row.get('error') or (row.get('gradingResult') or {}).get('reason', ''),
                      'grading': row.get('gradingResult'), 'latency_ms': row.get('latencyMs'),
                      'finish_reason': response.get('finishReason'), 'usage': response.get('tokenUsage')})
    if expected:
        raise ValueError('incomplete result matrix; refusing a misleading report')
    return sorted(cells, key=lambda r: (r['case_index'], r['prompt_index']))


def load_evidence(folder):
    folder = Path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if not re.fullmatch('[0-9a-f]{32}', manifest.get('id', '')):
        raise ValueError('invalid run id')
    if manifest.get('engine_version') != ENGINE_VERSION or manifest.get('status') not in ('finished', 'engine_error'):
        raise ValueError('only terminal runs from the pinned engine can be imported')
    files = {}
    for name in ('suite.json', 'config.json', 'results.json', 'engine.log'):
        key = 'suite_sha256' if name == 'suite.json' else name + '_sha256'
        if name == 'results.json' and manifest['status'] == 'engine_error' and key not in manifest:
            continue
        path = folder / name
        if path.stat().st_size > 8_000_000:
            raise ValueError('evidence file exceeds 8 MB')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest.get(key):
            raise ValueError(f'evidence hash mismatch: {name}')
        files[name] = raw.decode('utf-8')
    suite = json.loads(files['suite.json'])
    config = compile_suite(suite)
    if json.loads(files['config.json']) != config:
        raise ValueError('configuration differs from restricted suite compiler')
    cells = normalize(suite, json.loads(files['results.json'])) if manifest['status'] == 'finished' else []
    return {'manifest': manifest, 'suite': suite, 'config': config, 'cells': cells, 'raw_files': files}


def import_run(folder, path=DB):
    snapshot = load_evidence(folder)
    initialize(path)
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        return insert_snapshot(db, snapshot)


def insert_snapshot(db, snapshot):
    """Caller validates evidence and owns the transaction."""
    run_id = snapshot['manifest']['id']
    value = encode(snapshot).decode('utf-8')
    old = db.execute('SELECT snapshot FROM runs WHERE id=?', (run_id,)).fetchone()
    if old and old['snapshot'] != value:
        raise ValueError('run id already exists with different evidence')
    if not old:
        db.execute('INSERT INTO runs VALUES(?,?,?)', (run_id, value, now()))
    return run_id


def get_run(db, run_id):
    row = db.execute('SELECT snapshot FROM runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise KeyError('run not found')
    result = json.loads(row['snapshot'])
    result.pop('raw_files')
    reviews = [dict(r) for r in db.execute('SELECT * FROM reviews WHERE run_id=? ORDER BY version', (run_id,))]
    for cell in result['cells']:
        cell['history'] = [r for r in reviews if r['cell_id'] == cell['id']]
        cell['review'] = cell['history'][-1] if cell['history'] else {
            'version': 0, 'decision': 'pending', 'note': '', 'reviewer': ''}
    result['summary'] = summarize(result)
    return result


def summarize(run):
    summary = []
    for prompt in run['suite']['prompts']:
        cells = [c for c in run['cells'] if c['prompt_id'] == prompt['id']]
        summary.append({'prompt_id': prompt['id'], 'total': len(cells),
                        **{status: sum(c['status'] == status for c in cells)
                           for status in ('passed', 'assertion_failed', 'call_error')},
                        **{state: sum(c['review']['decision'] == state for c in cells)
                           for state in ('pending', 'accepted', 'rejected', 'unclear')}})
    return summary


def review(db, run_id, cell_id, version, decision, note, reviewer):
    db.execute('BEGIN IMMEDIATE')
    run = get_run(db, run_id)
    cell = next((c for c in run['cells'] if c['id'] == cell_id), None)
    if cell is None:
        raise KeyError('cell not found')
    if cell['review']['version'] != version:
        raise RuntimeError('review changed; refresh before saving')
    if decision not in ('accepted', 'rejected', 'unclear') or not 5 <= len(note.strip()) <= 2000 or not 1 <= len(reviewer.strip()) <= 80:
        raise ValueError('decision, reviewer and a 5–2000 character reason are required')
    if cell['status'] == 'call_error' and decision == 'accepted':
        raise ValueError('a failed model call cannot be accepted as a correct answer')
    db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',
               (run_id, cell_id, version + 1, decision, note.strip(), reviewer.strip(), now()))
    return get_run(db, run_id)


def report(db, run_id, title, note):
    db.execute('BEGIN IMMEDIATE')
    run = get_run(db, run_id)
    report_id = uuid4().hex
    snapshot = {'id': report_id, 'title': title, 'note': note, 'created_at': now(),
                'scope': 'Development review; reviewer names are self-declared, not authenticated. Not an independent blind evaluation.',
                'run': run}
    db.execute('INSERT INTO reports VALUES(?,?,?,?)', (report_id, run_id, encode(snapshot).decode(), snapshot['created_at']))
    return snapshot


def get_suite(db, suite_id, version=None):
    row = db.execute('SELECT version FROM suites WHERE id=?', (suite_id,)).fetchone()
    if not row:
        raise KeyError('suite not found')
    requested = row['version'] if version is None else version
    value = db.execute('SELECT * FROM suite_versions WHERE suite_id=? AND version=?', (suite_id, requested)).fetchone()
    if not value:
        raise KeyError('suite version not found')
    result = dict(value)
    result['suite'] = json.loads(result.pop('snapshot'))
    result['current_version'] = row['version']
    return result


def save_suite(db, suite, note, suite_id=None, version=None):
    compile_suite(suite)
    if not isinstance(note, str) or not 5 <= len(note.strip()) <= 2000:
        raise ValueError('a 5–2000 character change note is required')
    snapshot = encode(suite)
    db.execute('BEGIN IMMEDIATE')
    if suite_id is None:
        suite_id = uuid4().hex
        next_version = 1
        db.execute('INSERT INTO suites VALUES(?,?)', (suite_id, next_version))
    else:
        current = get_suite(db, suite_id)
        if current['version'] != version:
            raise RuntimeError('suite changed; reload before saving')
        if current['suite'] == suite:
            raise ValueError('no content changes to save')
        if version >= 100:
            raise ValueError('suite has reached 100 revisions; create a new suite')
        next_version = version + 1
        db.execute('UPDATE suites SET version=? WHERE id=?', (next_version, suite_id))
    db.execute('INSERT INTO suite_versions VALUES(?,?,?,?,?,?)',
               (suite_id, next_version, snapshot.decode(), hashlib.sha256(snapshot).hexdigest(), note.strip(), now()))
    return get_suite(db, suite_id)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    parser.add_argument('--db', type=Path, default=DB)
    args = parser.parse_args()
    print(import_run(args.folder, args.db))
