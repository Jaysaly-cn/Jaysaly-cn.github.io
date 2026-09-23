"""Offline rule evaluation: synthetic development examples, not model accuracy."""
import json
from pathlib import Path
from app.checks import check


def main():
    brief = {'facts': [{'id': 'F1', 'text': '支持 10 项任务', 'source': '合成规格'},
                       {'id': 'F2', 'text': '支持按周查看', 'source': '合成规格'}],
             'forbidden': ['保证', 'BEST'], 'required_phrase': '仅供学习'}
    cases = [('grounded', '支持10项任务。仅供学习', ['F1'], []),
             ('missing_disclaimer', '支持10项任务', ['F1'], ['required']),
             ('invented_number', '支持99项任务。仅供学习', ['F1'], ['numbers']),
             ('wrong_fact', '支持10项任务。仅供学习', ['F2'], ['numbers']),
             ('fullwidth', '支持１０项任务。仅供学习', ['F1'], []),
             ('forbidden_word', '保证完成任务。仅供学习', ['F1'], ['forbidden']),
             ('casefold', 'The best。仅供学习', ['F1'], ['forbidden']),
             ('no_refs', '任务清单。仅供学习', [], ['facts']),
             ('length', '任务' * 40 + '仅供学习', ['F1'], ['length']),
             ('semantic_limit', '支持自动发送短信。仅供学习', ['F1'], [])]
    results = []
    for name, body, refs, expected in cases:
        actual = sorted({i['code'] for i in check(brief, '短信', '任务清单', body, refs)['blockers']})
        results.append({'case': name, 'expected': sorted(expected), 'actual': actual, 'passed': actual == sorted(expected)})
    output = {'suite': 'synthetic lexical guard development cases', 'passed': sum(r['passed'] for r in results),
              'total': len(results), 'results': results,
              'limitation': 'semantic_limit intentionally demonstrates that invented capabilities can pass lexical checks; human review is required.'}
    Path('artifacts').mkdir(exist_ok=True)
    Path('artifacts/evaluation.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{output["passed"]}/{output["total"]} lexical guard cases passed; not semantic or model accuracy.')
    if output['passed'] != output['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
