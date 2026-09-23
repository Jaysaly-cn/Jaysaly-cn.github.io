import copy
import json
from pathlib import Path
import pytest
from engine import compile_suite
import engine
import subprocess
from types import SimpleNamespace

SAMPLE = json.loads((Path(__file__).parents[1] / 'samples/ticket-routing.json').read_text(encoding='utf-8'))


def test_compilation_pins_local_provider_and_keeps_rubric():
    config = compile_suite(SAMPLE)
    assert len(config['prompts']) * len(config['tests']) == 8
    assert config['providers'][0]['config']['apiBaseUrl'] == 'http://127.0.0.1:8771/v1'
    assert config['tests'][3]['metadata']['human_rubric'] == SAMPLE['cases'][3]['rubric']
    assert config['sharing'] is False


@pytest.mark.parametrize('check', [
    {'type': 'javascript', 'value': 'process.exit()'},
    {'type': 'python', 'value': 'file://evil.py'},
    {'type': 'llm-rubric', 'value': 'call cloud'},
    {'type': 'is-json', 'transform': 'output'},
    {'type': 'contains', 'value': ''},
    {'type': 'equals', 'value': 'file://secret.txt'},
    {'type': 'equals', 'value': 'package:module:function'},
    {'type': 'contains', 'value': '{{input}}'},
])
def test_rejects_executable_or_invalid_assertions(check):
    suite = copy.deepcopy(SAMPLE)
    suite['cases'][0]['checks'] = [check]
    with pytest.raises(ValueError):
        compile_suite(suite)


def test_rejects_duplicate_cases():
    suite = copy.deepcopy(SAMPLE)
    suite['cases'].append(suite['cases'][0])
    with pytest.raises(ValueError):
        compile_suite(suite)


@pytest.mark.parametrize('value', ['file://secret.txt', 'package:module:fn', '{{input}}'])
def test_input_cannot_load_files_or_templates(value):
    suite = copy.deepcopy(SAMPLE)
    suite['cases'][0]['input'] = value
    with pytest.raises(ValueError):
        compile_suite(suite)


def test_rejects_prompt_templates_and_provider_override():
    suite = copy.deepcopy(SAMPLE)
    suite['prompts'][0]['instruction'] = '{{ dangerous }}'
    with pytest.raises(ValueError):
        compile_suite(suite)
    suite = copy.deepcopy(SAMPLE)
    suite['providers'] = ['external']
    with pytest.raises(ValueError):
        compile_suite(suite)


def test_runner_preserves_failed_process_and_unique_snapshots(tmp_path, monkeypatch):
    package = tmp_path / 'node_modules/promptfoo/package.json'
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"0.123.1"}')
    monkeypatch.setattr(engine, 'ROOT', tmp_path)
    commands = []
    def fail(command, **kwargs):
        commands.append(command)
        assert kwargs['env']['PROMPTFOO_DISABLE_TELEMETRY'] == '1'
        kwargs['stdout'].write(b'engine unavailable')
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(engine.subprocess, 'run', fail)
    first = engine.run(SAMPLE, tmp_path / 'runs')
    second = engine.run(SAMPLE, tmp_path / 'runs')
    assert first != second
    manifest = json.loads((first / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'engine_error'
    assert manifest['exit_code'] == 1
    assert manifest['semantic_review'] == 'pending'
    assert (first / 'suite.json').read_bytes() == engine.encode(SAMPLE)
    assert '--no-share' in commands[0] and '--no-write' in commands[0]


def test_timeout_is_recorded(tmp_path, monkeypatch):
    package = tmp_path / 'node_modules/promptfoo/package.json'
    package.parent.mkdir(parents=True)
    package.write_text('{"version":"0.123.1"}')
    monkeypatch.setattr(engine, 'ROOT', tmp_path)
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1800)
    monkeypatch.setattr(engine.subprocess, 'run', timeout)
    folder = engine.run(SAMPLE, tmp_path / 'runs')
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'engine_error'
    assert 'completed_at' in manifest
