"""Synthetic workflow evaluation, not LLM accuracy or autonomous research scoring."""
import hashlib
import json
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import now

ROOT = Path(__file__).resolve().parents[1]


def main():
    results = []
    def check(name, actual, expected):
        results.append({'case': name, 'actual': actual, 'expected': expected, 'pass': actual == expected})
    with tempfile.TemporaryDirectory() as folder:
        with TestClient(create_app(str(Path(folder) / 'eval.db'))) as c:
            p = c.post('/api/projects', json={'title':'合成选型研究','question':'比较两个方案的价格与能力',
                'entities':['Alpha','Beta'],'dimensions':['价格','导入','协作']}).json()['id']
            base = '/api/projects/' + p
            content = 'Alpha 团队版每月19元。支持 Markdown 导入。此资料仅为合成评测样本。'
            payload = {'title':'合成定价材料','entity':'Alpha','content':content}
            s = c.post(base+'/sources', json=payload).json()
            check('来源正文哈希可重算', s['sha256'], hashlib.sha256(content.encode()).hexdigest())
            check('相同材料去重', c.post(base+'/sources',json=payload).json()['id'], s['id'])
            check('初始比较矩阵保留六个缺口', len(c.get(base).json()['gaps']), 6)
            item = {'source_id':s['id'],'dimension':'价格','statement':'团队版月付19元','quote':'Alpha 团队版每月19元。'}
            check('虚构引用拒绝', c.post(base+'/claims',json={**item,'quote':'不存在的免费方案'}).status_code, 422)
            claim = c.post(base+'/claims',json=item).json()
            check('候选不进入报告', len(c.get(base).json()['gaps']), 6)
            review = {'version':1,'state':'approved','note':'已核对合成材料'}
            c.patch(base+'/claims/'+claim['id'],json=review)
            check('批准后填补一个缺口', len(c.get(base).json()['gaps']), 5)
            check('旧审核版本禁止覆盖', c.patch(base+'/claims/'+claim['id'],json=review).status_code, 409)
            old = c.post(base+'/reports').json()
            check('报告包含逐字原文', 'Alpha 团队版每月19元。' in old['markdown'], True)
            c.patch(base+'/sources/'+s['id'],json={'archived':True})
            check('来源归档后恢复缺口', len(c.get(base).json()['gaps']), 6)
            check('历史报告保持不变', c.get(base+'/reports/'+old['id']).json()['markdown'] == old['markdown'], True)
            c.patch(base+'/sources/'+s['id'],json={'archived':False})
            check('恢复来源后重新纳入证据', len(c.get(base).json()['gaps']), 5)
    report = {'generated_at':now(), 'scope':'Synthetic development workflow; no live model evaluation',
              'total':len(results),'passed':sum(r['pass'] for r in results),'results':results}
    (ROOT/'artifacts').mkdir(exist_ok=True)
    (ROOT/'artifacts/evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False))
    if not all(r['pass'] for r in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
