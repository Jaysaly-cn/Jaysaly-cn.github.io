"""Prepare offline validation from verified original output, without model calls."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import encode
from schemas import SCHEMAS
from store import load_evidence

ROOT = Path(__file__).resolve().parents[1]
rows = []
for project, profile in [('feedbacklens', 'json-feedback-v1'), ('changelens', 'json-change-v1')]:
    evidence = load_evidence(ROOT / 'artifacts' / (project + '-regression-run'))
    for cell in evidence['cells']:
        rows.append({'id': project + '/' + cell['id'], 'profile': profile, 'output': cell['output'],
                     'run_id': evidence['manifest']['id'], 'original_status': cell['status']})

feedback = {'suggestions': [{'theme': '导出错误', 'kind': 'problem', 'quote': '导出一直报错'}]}
change = {'summary': '新增导出审计记录。', 'old_quote': '', 'new_quote': '新增审计记录。'}
fixtures = [
    ('feedback-valid', 'json-feedback-v1', feedback, True),
    ('feedback-empty', 'json-feedback-v1', {'suggestions': []}, True),
    ('feedback-array', 'json-feedback-v1', [feedback], False),
    ('feedback-missing', 'json-feedback-v1', {'suggestions': [{'theme': '错误'}]}, False),
    ('feedback-kind', 'json-feedback-v1', {'suggestions': [{**feedback['suggestions'][0], 'kind': 'billing'}]}, False),
    ('feedback-extra', 'json-feedback-v1', {**feedback, 'approved': True}, False),
    ('feedback-item-extra', 'json-feedback-v1', {'suggestions': [{**feedback['suggestions'][0], 'priority': 1}]}, False),
    ('feedback-too-many', 'json-feedback-v1', {'suggestions': feedback['suggestions'] * 6}, False),
    ('feedback-short', 'json-feedback-v1', {'suggestions': [{**feedback['suggestions'][0], 'theme': '错'}]}, False),
    ('change-valid', 'json-change-v1', change, True),
    ('change-missing', 'json-change-v1', {'summary': '新增导出审计记录。'}, False),
    ('change-null', 'json-change-v1', {**change, 'old_quote': None}, False),
    ('change-short', 'json-change-v1', {**change, 'summary': '变化'}, False),
    ('change-extra', 'json-change-v1', {**change, 'approved': True}, False),
    ('change-long', 'json-change-v1', {**change, 'new_quote': '字' * 4001}, False),
    # Semantically false but structurally valid: do not promise meaning validation.
    ('structure-not-truth', 'json-change-v1', {**change, 'summary': '完全无依据的业务结论。'}, True),
]
for identity, profile, output, expected in fixtures:
    rows.append({'id': identity, 'profile': profile, 'output': json.dumps(output, ensure_ascii=False), 'expected': expected})
rows.append({'id': 'fence-preserved', 'profile': 'json-change-v1',
             'output': '```json\n' + json.dumps(change) + '\n```', 'expected': False})
target = ROOT / 'data/schema-probe-input.json'
target.parent.mkdir(exist_ok=True)
target.write_bytes(encode({'schemas': SCHEMAS, 'rows': rows}))
print(target)
