"""Real HTTP acceptance; only synthetic input, never saves visitor cookies."""
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
import httpx


def run(base, output):
    if output.exists():
        raise RuntimeError('refusing to overwrite acceptance evidence')
    with httpx.Client(base_url=base, timeout=30) as a, httpx.Client(base_url=base, timeout=30) as b:
        assert a.get('/').status_code == b.get('/').status_code == 200
        sa, sb = a.get('/api/suites').json()[0], b.get('/api/suites').json()[0]
        assert sa['suite_id'] != sb['suite_id']
        assert b.get('/api/suites/'+sa['suite_id']+'/versions').status_code == 404
        payload = {'suite_id':sa['suite_id'],'version':1,'request_key':uuid4().hex}
        r = a.post('/api/jobs',json=payload);r.raise_for_status();job = r.json()
        assert a.post('/api/jobs',json=payload).json()['id'] == job['id']
        assert b.get('/api/jobs/'+job['id']+'/diagnostics').status_code == 404
        print('Started public job',job['id'],flush=True)
        for _ in range(45):
            job = next(j for j in a.get('/api/jobs').json() if j['id']==job['id'])
            if job['state'] not in ('starting','running'):
                break
            time.sleep(2)
        assert job['state']=='finished',job
        rid = job['run_id']
        assert b.get('/api/runs/'+rid).status_code == 404
        result = a.get('/api/runs/'+rid).json()
        assert len(result['cells'])==8
        note = {'version':0,'decision':'rejected','note':'该合成样例要求账单标签，输出技术不符合诉求。','reviewer':'HTTP验收'}
        r = a.post(f'/api/runs/{rid}/cells/3:1/reviews',json=note);r.raise_for_status()
        r = a.post(f'/api/runs/{rid}/reports',json={'title':'公网隔离验收','note':'仅复核指令干扰单元，其余七项仍待复核。'});r.raise_for_status();report=r.json()
        raw = a.get('/api/reports/'+report['id']);raw.raise_for_status()
        assert b.get('/api/reports/'+report['id']).status_code==404
        assert a.post('/api/jobs',headers={'Origin':'https://invalid.example'},json=payload).status_code==403
        assert a.get('/docs').status_code==404
        record={'url':base,'job':job,'summary':result['summary'],'report_id':report['id'],
                'report_sha256':hashlib.sha256(raw.content).hexdigest(),
                'checks':['two visitor suite isolation','job and run visibility isolation','request-key idempotency','real local model task via public URL','manual review and frozen report','cross-visitor report 404','cross-origin write 403','docs 404'],
                'limits':'temporary development-machine tunnel; session cookies intentionally omitted; real results not a business accuracy estimate'}
        output.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Public workflow complete',rid,flush=True)


if __name__=='__main__':
    run(sys.argv[1].rstrip('/'),Path(sys.argv[2]))
