"""Verify synthetic public demo workflow and two-visitor isolation without storing cookies."""
import json
from pathlib import Path
import sys
import httpx

base=sys.argv[1].rstrip('/')
output=Path(sys.argv[2])
if output.exists():raise SystemExit('Refusing to overwrite evidence')
with httpx.Client(base_url=base,timeout=30) as a,httpx.Client(base_url=base,timeout=30) as b:
    for client in (a,b):
        client.get('/').raise_for_status()
        assert len(client.get('/api/documents').json())==8
    old=a.post('/api/ask',json={'question':'离线激活码如何恢复？'}).json()
    a.post('/api/runs/'+old['id']+'/feedback',json={'rating':'unhelpful','note':'合成流程需要补充'}).raise_for_status()
    ticket=a.post('/api/tickets',json={'run_id':old['id'],'title':'公网合成激活问题'}).json()
    route='/api/tickets/'+ticket['id']
    for version,status in [(1,'in_progress'),(2,'resolved')]:
        a.patch(route,json={'version':version,'status':status,'assignee':'合成值班员','resolution':'管理员核对设备授权后重新生成激活码。'}).raise_for_status()
    published=a.post(route+'/knowledge',json={'version':3,'title':'离线激活码恢复流程','content':'离线激活码失效时，由管理员核对设备标识和授权状态，再通过后台重新生成激活码。','review_note':'仅合成测试知识，需核对设备授权','reviewed':True})
    published.raise_for_status()
    check=a.post('/api/runs/'+old['id']+'/rechecks').json()
    assert check['snapshot']['after']['citations'][0]['document_id']==published.json()['document_id']
    a.post('/api/rechecks/'+check['id']+'/review',json={'verdict':'improved','note':'增加了管理员核验和重新生成步骤','reviewed':True}).raise_for_status()
    assert a.get('/api/runs/'+old['id']).json()==old
    isolation={'run':b.get('/api/runs/'+old['id']).status_code,'ticket':b.get(route).status_code,'rechecks':b.get('/api/rechecks').json(),'tickets':b.get('/api/tickets').json(),'documents':len(b.get('/api/documents').json())}
    assert isolation=={'run':404,'ticket':404,'rechecks':[],'tickets':[],'documents':8}
    disabled=a.post('/api/ask',json={'question':'退款条件','use_model':True}).status_code
    origin=b.get('/api/documents',headers={'Origin':'https://foreign.example'}).status_code
    assert disabled==409 and origin==403
    output.write_text(json.dumps({'base':base,'synthetic':True,'old_run':old,'ticket':a.get(route).json(),'recheck':a.get('/api/rechecks').json()[0],'isolation':isolation,'model_request_status':disabled,'foreign_origin_status':origin},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Public knowledge loop and visitor isolation passed; model disabled as intended')
