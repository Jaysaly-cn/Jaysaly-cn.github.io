"""Restricted evaluation runner. Test-suite JSON is data, never a promptfoo config."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid
from schemas import SCHEMAS

ROOT = Path(__file__).resolve().parent
ENGINE_VERSION = '0.123.1'


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{name}: expected non-empty text <= {limit} characters')
    return value


def literal(value):
    if value.lstrip().startswith(('file://', 'package:')) or any(t in value for t in ('{{', '{%', '{#')):
        raise ValueError('file/package references and template syntax are not allowed')
    return value


def compile_suite(suite):
    if not isinstance(suite, dict) or set(suite) != {'name', 'prompts', 'cases'}:
        raise ValueError('suite requires exactly name, prompts, cases')
    text(suite['name'], 'name', 120)
    prompts, cases = suite['prompts'], suite['cases']
    if not isinstance(prompts, list) or not 2 <= len(prompts) <= 3:
        raise ValueError('compare 2–3 prompts')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
        raise ValueError('expected 1–20 cases')
    compiled_prompts = []
    seen = set()
    for p in prompts:
        if not isinstance(p, dict) or set(p) != {'id', 'instruction'}:
            raise ValueError('prompt requires id and instruction')
        name = text(p['id'], 'prompt id', 60)
        if name in seen:
            raise ValueError('duplicate prompt id')
        seen.add(name)
        instruction = text(p['instruction'], 'instruction', 6000)
        # Only our fixed template may contain template syntax. Prevent file://
        # loaders and arbitrary Nunjucks expressions in supplied prompt text.
        if any(token in instruction for token in ('{{', '{%', '{#')):
            raise ValueError('template syntax is not allowed in instructions')
        compiled_prompts.append({'id': name, 'label': name, 'raw': json.dumps([
            {'role': 'system', 'content': instruction},
            {'role': 'user', 'content': '{{input}}'},
        ], ensure_ascii=False)})
    tests = []
    seen = set()
    for c in cases:
        if not isinstance(c, dict) or set(c) != {'id', 'input', 'rubric', 'checks'}:
            raise ValueError('case requires id, input, rubric, checks')
        cid = text(c['id'], 'case id', 60)
        if cid in seen:
            raise ValueError('duplicate case id')
        seen.add(cid)
        literal(text(c['input'], 'input', 8000))
        text(c['rubric'], 'rubric', 2000)
        checks = c['checks']
        if not isinstance(checks, list) or not 1 <= len(checks) <= 8:
            raise ValueError('expected 1–8 deterministic checks')
        assertions = []
        for check in checks:
            if not isinstance(check, dict) or not isinstance(check.get('type'), str) or check['type'] not in {'equals', 'contains', 'not-contains', 'is-json', *SCHEMAS}:
                raise ValueError('unsupported check; executable/model-based checks are forbidden')
            kind = check['type']
            keys = {'type'} if kind == 'is-json' or kind in SCHEMAS else {'type', 'value'}
            if set(check) != keys:
                raise ValueError('unexpected check fields')
            if kind != 'is-json' and kind not in SCHEMAS:
                literal(text(check['value'], 'check value', 2000))
            assertions.append({'type': 'is-json', 'value': json.loads(json.dumps(SCHEMAS[kind]))}
                              if kind in SCHEMAS else dict(check))
        tests.append({'description': cid, 'vars': {'input': c['input']}, 'assert': assertions,
                      'metadata': {'case_id': cid, 'human_rubric': c['rubric']}})
    return {'description': suite['name'], 'prompts': compiled_prompts,
            'providers': [{'id': 'openai:chat:portfolio-qwen-1.5b', 'config': {
                'apiBaseUrl': 'http://127.0.0.1:8771/v1', 'apiKey': 'local-only',
                'temperature': 0, 'max_tokens': 500, 'maxRetries': 0}}],
            'tests': tests, 'sharing': False}


def run(suite, directory=ROOT / 'data' / 'runs', *, run_id=None, provenance=None, on_process=None):
    config = compile_suite(suite)
    installed = json.loads((ROOT / 'node_modules/promptfoo/package.json').read_text(encoding='utf-8'))
    if installed['version'] != ENGINE_VERSION:
        raise RuntimeError('run npm ci: installed engine version differs from lock')
    run_id = run_id or uuid.uuid4().hex
    if len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
        raise ValueError('invalid run id')
    target = Path(directory) / run_id
    target.mkdir(parents=True, exist_ok=False)
    snapshot = encode(suite)
    (target / 'suite.json').write_bytes(snapshot)
    (target / 'config.json').write_bytes(encode(config))
    manifest = {'id': run_id, 'engine': 'promptfoo', 'engine_version': ENGINE_VERSION,
                'suite_sha256': hashlib.sha256(snapshot).hexdigest(),
                'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'running',
                'semantic_review': 'pending', 'scope': 'synthetic development evaluation; assertions are not semantic accuracy'}
    if provenance is not None:
        manifest['suite_version'] = provenance
    path = target / 'manifest.json'
    path.write_bytes(encode(manifest))
    env = dict(os.environ, PROMPTFOO_DISABLE_TELEMETRY='1', PROMPTFOO_DISABLE_UPDATE='1',
               PROMPTFOO_CONFIG_DIR=str(target / 'engine-state'), PROMPTFOO_DISABLE_REMOTE_GENERATION='true')
    node = os.environ.get('ED_NODE_BIN', 'node')
    command = [node, str(ROOT / 'node_modules/promptfoo/dist/src/entrypoint.js'),
               'eval', '-c', str(target / 'config.json'), '-o', str(target / 'results.json'),
               '--no-cache', '--no-write', '--no-share', '--no-progress-bar', '--no-table', '-j', '1']
    try:
        with (target / 'engine.log').open('wb') as log:
            if on_process is None:
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                        timeout=1800, check=False)
                exit_code = result.returncode
            else:
                with subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT) as process:
                    try:
                        on_process(process.pid)
                        exit_code = process.wait(timeout=1800)
                    except BaseException:
                        process.kill()
                        process.wait()
                        raise
        manifest['exit_code'] = exit_code
        manifest['status'] = 'finished' if (target / 'results.json').exists() else 'engine_error'
    except (OSError, subprocess.TimeoutExpired) as exc:
        manifest.update(status='engine_error', error=str(exc))
    manifest['completed_at'] = datetime.now(timezone.utc).isoformat()
    for name in ('config.json', 'results.json', 'engine.log'):
        if (target / name).exists():
            manifest[name + '_sha256'] = hashlib.sha256((target / name).read_bytes()).hexdigest()
    path.write_bytes(encode(manifest))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('suite', type=Path)
    args = parser.parse_args()
    print(run(json.loads(args.suite.read_text(encoding='utf-8-sig'))), flush=True)
