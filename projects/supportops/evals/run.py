"""python -m evals.run; fixed synthetic retrieval benchmark, NOT live LLM evaluation."""
import json
import platform
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def main():
    cases = json.loads((ROOT / 'evals/cases.json').read_text(encoding='utf-8'))
    results = []
    with tempfile.TemporaryDirectory() as directory:
        with TestClient(create_app(str(Path(directory) / 'eval.db'))) as client:
            assert client.post('/api/seed').status_code == 200
            for case in cases:
                response = client.post('/api/ask', json={'question': case['question'], 'audience': case.get('audience', 'public')})
                assert response.status_code == 201, response.text
                run = response.json()
                ids = [c['document_id'] for c in run['citations']]
                expected = case['expected']
                passed = expected in ids if expected else not ids
                results.append({**case, 'retrieved': ids, 'pass': passed, 'top1': ids[0] == expected if ids else expected is None, 'elapsed_ms': run['elapsed_ms']})
    answerable = [r for r in results if r['expected']]
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'dataset': '20 synthetic development cases; not a held-out or production benchmark',
              'python': platform.python_version(), 'live_model_tested': False,
              'total': len(results), 'passed': sum(r['pass'] for r in results),
              'recall_at_4': sum(r['pass'] for r in answerable) / len(answerable),
              'top1_accuracy_answerable': sum(r['top1'] for r in answerable) / len(answerable),
              'results': results}
    target = ROOT / 'artifacts/evaluation.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}, ensure_ascii=False))
    raise SystemExit(0 if all(r['pass'] for r in results) else 1)


if __name__ == '__main__':
    main()
