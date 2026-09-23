import json
from pathlib import Path
from app.dates import resolve

CASES=[('2026-09-23','今天','2026-09-23'),('2026-09-23','明天','2026-09-24'),
       ('2026-12-31','后天','2027-01-02'),('2026-09-27','下周一','2026-09-28'),
       ('2026-09-23','本周五','2026-09-25'),('2026-09-23','下周五','2026-10-02'),
       ('2026-09-23','尽快',''),('2026-09-23','周五',''),('2026-09-23','2026-02-30',''),
       ('2026-09-23','2026-10-01','2026-10-01')]
results=[{'meeting_date':d,'phrase':p,'expected':e,'actual':resolve(p,d),'passed':resolve(p,d)==e} for d,p,e in CASES]
report={'scope':'Synthetic date-rule development cases, not model accuracy','total':len(results),'passed':sum(r['passed'] for r in results),'results':results}
Path('artifacts/evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'{report["passed"]}/{report["total"]} date cases passed')
if report['passed']!=report['total']:
    raise SystemExit(1)
