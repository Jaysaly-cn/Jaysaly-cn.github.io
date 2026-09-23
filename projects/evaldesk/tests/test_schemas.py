import copy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import create_app
from engine import compile_suite
from store import load_evidence

ROOT = Path(__file__).parents[1]


def test_schema_versions_compile_and_roundtrip_without_rewriting_old_evidence(tmp_path):
    suite = json.loads((ROOT / 'samples/feedbacklens-regression.json').read_text(encoding='utf-8'))
    before = load_evidence(ROOT / 'artifacts/feedbacklens-regression-run')
    with TestClient(create_app(tmp_path / 'schema.sqlite3')) as client:
        original = client.post('/api/suites', json={'suite': suite, 'note': '原始 JSON 语法规则'}).json()
        suite['cases'][0]['checks'] = [{'type': 'json-feedback-v1'}]
        updated = client.put('/api/suites/' + original['suite_id'], json={
            'suite': suite, 'version': 1, 'note': '新增反馈对象结构规则'}).json()
        assert updated['version'] == 2
        assert updated['suite']['cases'][0]['checks'] == [{'type': 'json-feedback-v1'}]
        old = client.get('/api/suites/' + original['suite_id'] + '/versions/1/download').json()
        assert old['cases'][0]['checks'] == [{'type': 'is-json'}]
    config = compile_suite(suite)
    schema = config['tests'][0]['assert'][0]['value']
    assert schema['additionalProperties'] is False
    schema['required'].clear()
    assert compile_suite(suite)['tests'][0]['assert'][0]['value']['required'] == ['suggestions']
    assert load_evidence(ROOT / 'artifacts/feedbacklens-regression-run') == before


@pytest.mark.parametrize('check', [
    {'type': 'json-feedback-v1', 'value': {'$ref': 'https://example.com/schema'}},
    {'type': 'json-change-v1', 'schema': {'type': 'object'}},
    {'type': 'json-custom-v1'},
])
def test_schema_checks_reject_custom_payload_and_unknown_profiles(check):
    suite = json.loads((ROOT / 'samples/ticket-routing.json').read_text(encoding='utf-8'))
    suite['cases'][0]['checks'] = [copy.deepcopy(check)]
    with pytest.raises(ValueError):
        compile_suite(suite)
