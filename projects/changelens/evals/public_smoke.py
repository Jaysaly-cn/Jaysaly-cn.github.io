"""Exercise a running public demo with synthetic records; never save session cookies."""
import json
from pathlib import Path
import sys
import httpx

base=sys.argv[1].rstrip('/')
output=Path(sys.argv[2])
if output.exists():raise SystemExit('Refusing to overwrite evidence')
def versions(c):
    home=c.get('/');home.raise_for_status()
    doc=c.get('/api/documents').json()[0]
    return c.get('/api/documents/'+doc['id']+'/versions').json()
with httpx.Client(base_url=base,timeout=180) as a,httpx.Client(base_url=base,timeout=30) as b:
    va,vb=versions(a),versions(b)
    assert va[0]['id']!=vb[0]['id']
    r=a.post('/api/comparisons',json={'old_id':va[0]['id'],'new_id':va[1]['id']});r.raise_for_status();comparison=r.json()
    cid=comparison['id'];index=next(i for i,o in enumerate(comparison['diff']['operations']) if o['kind']!='equal')
    generated=a.post(f'/api/comparisons/{cid}/operations/{index}/suggest')
    runs=a.get(f'/api/comparisons/{cid}/model-runs').json()
    op=comparison['diff']['operations'][index]
    r=a.post(f'/api/comparisons/{cid}/operations/{index}/impacts',json={'summary':'文件保留时间从7天缩短至3天，新增审计记录。','old_quote':op['old_text'],'new_quote':op['new_text']});r.raise_for_status();impact=r.json()
    r=a.post('/api/impacts/'+impact['id']+'/review',json={'version':1,'decision':'confirmed','note':'核对合成条款，不推断执行范围'});r.raise_for_status()
    r=a.post(f'/api/comparisons/{cid}/briefs',json={'title':'公网合成验收','note':'仅用于验证独立访客与交付流程'});r.raise_for_status();brief=r.json()
    exported=a.get('/api/briefs/'+brief['id']+'/export')
    other={endpoint:b.get('/api/'+endpoint).status_code for endpoint in [f'versions/{va[0]["id"]}',f'comparisons/{cid}',f'comparisons/{cid}/model-runs',f'briefs/{brief["id"]}/export']}
    assert all(v==404 for v in other.values())
    assert exported.status_code==200 and exported.content.startswith(b'PK')
    origin=b.get('/api/documents',headers={'Origin':'https://foreign.example'}).status_code
    assert origin==403
    output.write_text(json.dumps({'base':base,'synthetic':True,'model_status':generated.status_code,'model_response':generated.json(),'model_runs':runs,'brief':brief,'other_visitor_status':other,'foreign_origin_status':origin,'zip_bytes':len(exported.content)},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'model_status':generated.status_code,'isolated':other,'zip_bytes':len(exported.content)}))
