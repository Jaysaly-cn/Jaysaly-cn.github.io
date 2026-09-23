import copy
import json
from pathlib import Path
import shutil
import pytest
from fastapi.testclient import TestClient
from app import create_app
import store

EVIDENCE = Path(__file__).parents[1] / 'artifacts/engine-spike'


def client_for(tmp_path):
    db = tmp_path / 'review.sqlite3'
    run_id = store.import_run(EVIDENCE, db)
    return TestClient(create_app(db)), run_id, db


def test_real_result_failure_is_not_call_error_and_import_idempotent(tmp_path):
    client, run_id, db = client_for(tmp_path)
    assert store.import_run(EVIDENCE, db) == run_id
    with client:
        run = client.get('/api/runs/' + run_id).json()
        assert [m['passed'] for m in run['summary']] == [2, 2]
        assert sum(m['assertion_failed'] for m in run['summary']) == 4
        assert sum(m['call_error'] for m in run['summary']) == 0
        assert len(client.get('/api/runs').json()) == 1
        assert all(c['review']['decision'] == 'pending' for c in run['cells'])


def test_review_conflict_history_frozen_report_and_restart(tmp_path):
    client, rid, db = client_for(tmp_path)
    url = f'/api/runs/{rid}/cells/0:1/reviews'
    with client:
        value = {'version': 0, 'decision': 'rejected', 'note': '输出退款，不属于允许的分类标签。', 'reviewer': '开发者'}
        assert client.post(url, json=value).status_code == 201
        assert client.post(url, json=value).status_code == 409
        report = client.post(f'/api/runs/{rid}/reports', json={'title': '首轮对比', 'note': '还有七项未完成业务复核，不建议直接上线。'}).json()
        raw = client.get('/api/reports/' + report['id']).content
        assert report['run']['summary'][1]['rejected'] == 1
        assert sum(m['pending'] for m in report['run']['summary']) == 7
        value.update(version=1, decision='unclear', note='需要重新确认分类标签的业务约定。')
        revised = client.post(url, json=value).json()
        cell = next(c for c in revised['cells'] if c['id'] == '0:1')
        assert [h['decision'] for h in cell['history']] == ['rejected', 'unclear']
        assert cell['status'] == 'assertion_failed'
        assert client.get('/api/reports/' + report['id']).content == raw
    with TestClient(create_app(db)) as restarted:
        run = restarted.get('/api/runs/' + rid).json()
        assert next(c for c in run['cells'] if c['id'] == '0:1')['review']['version'] == 2
        assert restarted.get('/api/reports/' + report['id']).content == raw


def test_hash_or_incomplete_matrix_rejected_atomically(tmp_path):
    folder = tmp_path / 'copy'
    shutil.copytree(EVIDENCE, folder)
    (folder / 'suite.json').write_text('{}')
    with pytest.raises(ValueError, match='hash mismatch'):
        store.import_run(folder, tmp_path / 'empty.sqlite3')
    assert not (tmp_path / 'empty.sqlite3').exists()
    suite = json.loads((EVIDENCE / 'suite.json').read_text(encoding='utf-8'))
    raw = json.loads((EVIDENCE / 'results.json').read_text(encoding='utf-8'))
    raw['results']['results'].pop()
    with pytest.raises(ValueError, match='incomplete'):
        store.normalize(suite, raw)


def test_call_errors_cannot_be_accepted_and_unknown_cells_rejected(tmp_path):
    client, rid, db = client_for(tmp_path)
    with store.connect(db) as con:
        row = con.execute('SELECT snapshot FROM runs').fetchone()
        snapshot = json.loads(row['snapshot'])
        snapshot['cells'][0].update(status='call_error', output=None, reason='connection failed')
        con.execute('UPDATE runs SET snapshot=?', (store.encode(snapshot).decode(),))
    with client:
        value = {'version': 0, 'decision': 'accepted', 'note': '这个没有输出的调用不能判定为正确', 'reviewer': 'test'}
        assert client.post(f'/api/runs/{rid}/cells/0:0/reviews', json=value).status_code == 422
        assert client.post(f'/api/runs/{rid}/cells/99:9/reviews', json=value).status_code == 404
        value['decision'] = 'unclear'
        assert client.post(f'/api/runs/{rid}/cells/0:0/reviews', json=value).status_code == 201


def test_normalization_distinguishes_call_error_and_duplicate_cells():
    suite = json.loads((EVIDENCE / 'suite.json').read_text(encoding='utf-8'))
    raw = json.loads((EVIDENCE / 'results.json').read_text(encoding='utf-8'))
    row = raw['results']['results'][0]
    row.update(failureReason=2, success=False, response={'error': 'timeout'}, error='timeout')
    assert store.normalize(suite, raw)[0]['status'] == 'call_error'
    raw['results']['results'].append(copy.deepcopy(row))
    with pytest.raises(ValueError, match='duplicate'):
        store.normalize(suite, raw)


def test_local_origin_validation_and_missing_records(tmp_path):
    client, rid, _ = client_for(tmp_path)
    with client:
        assert client.get('/api/runs', headers={'host': 'evil.example'}).status_code == 403
        assert client.post(f'/api/runs/{rid}/reports', headers={'origin': 'https://evil.example'}, json={}).status_code == 403
        assert client.post(f'/api/runs/{rid}/reports', json={'title': 'bad', 'note': 'short', 'extra': 'no'}).status_code == 422
        assert client.get('/api/runs/missing').status_code == 404
        assert client.get('/api/reports/missing').status_code == 404
        assert client.get('/').status_code == 200
