import copy
import hashlib
from pathlib import Path
from fastapi.testclient import TestClient
from app import create_app
import store

EVIDENCE = Path(__file__).parents[1] / 'artifacts/engine-spike'


def test_regression_samples_are_valid_read_only_and_allowlisted(tmp_path):
    from engine import compile_suite
    with TestClient(create_app(tmp_path / 'samples.sqlite3')) as client:
        for name in ('feedbacklens-regression', 'changelens-regression'):
            response = client.get('/api/suite-sample', params={'name': name})
            assert response.status_code == 200
            suite = response.json()
            assert len(suite['cases']) == 6
            compile_suite(suite)
            saved = client.post('/api/suites', json={'suite': suite, 'note': '保存回归样例的新版本'})
            assert saved.status_code == 201
            assert saved.json()['suite'] == suite
        assert len(client.get('/api/suites').json()) == 2
        assert client.get('/api/runs').json() == []
        assert client.get('/api/jobs').json() == []
        assert client.get('/api/suite-sample', params={'name': '../data/evaldesk'}).status_code == 422
        assert client.get('/api/suite-sample', params={'name': 'portfolio-provenance'}).status_code == 422


def test_versions_export_conflict_and_old_run_unchanged(tmp_path):
    db = tmp_path / 'db.sqlite3'
    rid = store.import_run(EVIDENCE, db)
    with TestClient(create_app(db)) as client:
        original = client.get('/api/runs/' + rid).json()
        suite = copy.deepcopy(original['suite'])
        created = client.post('/api/suites', json={'suite': suite, 'note': '复制首轮评测使用的测试集'}).json()
        sid = created['suite_id']
        url = '/api/suites/' + sid
        raw = client.get(url + '/versions/1/download')
        assert raw.json() == suite
        assert hashlib.sha256(raw.content).hexdigest() == created['sha256']
        suite['prompts'][1]['instruction'] += '务必只输出规定类别。'
        update = {'suite': suite, 'note': '明确输出类别约束的措辞', 'version': 1}
        assert client.put(url, json=update).json()['version'] == 2
        assert client.put(url, json=update).status_code == 409
        update['version'] = 2
        assert client.put(url, json=update).status_code == 422
        assert client.get(url + '/versions/1/download').content == raw.content
        assert client.get('/api/runs/' + rid).json() == original
        assert len(client.get(url + '/versions').json()) == 2
    with TestClient(create_app(db)) as client:
        assert client.get('/api/suites').json()[0]['version'] == 2
        assert client.get(url + '/versions/3').status_code == 404


def test_invalid_suite_never_creates_version(tmp_path):
    with TestClient(create_app(tmp_path / 'db.sqlite3')) as client:
        suite = client.get('/api/suite-sample').json()
        for bad in [{'type': []}, {'type': 'javascript', 'value': 'process.exit()'}, {'type': 'equals', 'value': 'file://secret'}]:
            value = copy.deepcopy(suite)
            value['cases'][0]['checks'] = [bad]
            assert client.post('/api/suites', json={'suite': value, 'note': '测试拒绝不安全规则'}).status_code == 422
        assert client.get('/api/suites').json() == []
        assert client.post('/api/suites', json={'suite': suite, 'note': '     '}).status_code == 422
        assert client.get('/api/suites/missing/versions').status_code == 404
