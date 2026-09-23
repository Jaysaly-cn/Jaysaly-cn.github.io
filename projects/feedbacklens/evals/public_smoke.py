import json,sys
from pathlib import Path
import httpx
base=sys.argv[1]
output=Path('artifacts/public-acceptance.json')
if output.exists():raise SystemExit('Refusing to overwrite evidence')
with httpx.Client(base_url=base,timeout=150) as a,httpx.Client(base_url=base,timeout=30) as b:
    assert a.get('/').status_code==200 and b.get('/').status_code==200
    annotation=a.post('/api/annotations',json={'source_id':'s1','theme':'离线导出','kind':'request','quote':'希望增加离线导出功能'});assert annotation.status_code==201
    aid=annotation.json()['id']
    assert a.post('/api/annotations/'+aid+'/review',json={'version':1,'decision':'confirmed','note':'公网合成验收核对引用'}).status_code==200
    report=a.post('/api/reports',json={'title':'公网合成验收','note':'仅验证访客独立流程'});assert report.status_code==201
    assert b.get('/api/annotations').json()==[]
    hidden=b.get('/api/reports/'+report.json()['id']);assert hidden.status_code==404
    origin=b.get('/api/feedback',headers={'Origin':'https://evil.test'});assert origin.status_code==403
    generated=a.post('/api/suggestions',json={'source_id':'s4'})
    assert generated.status_code in (201,422,502)
    assert b.get('/api/model-runs').json()==[]
    output.write_text(json.dumps({'base':base,'data':'synthetic','two_visitors':True,'foreign_report_status':hidden.status_code,'foreign_origin_status':origin.status_code,'frozen_report':report.json(),'model_status':generated.status_code,'model_runs':a.get('/api/model-runs').json()},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Public isolation and workflow passed; model status',generated.status_code)
