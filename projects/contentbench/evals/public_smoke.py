"""Live synthetic public workflow, with two isolated visitors. No external publication."""
import json
import sys
import time
from pathlib import Path
import httpx


def main(base):
    report={'url':base,'synthetic_only':True}
    with httpx.Client(base_url=base,timeout=110) as a,httpx.Client(base_url=base,timeout=30) as b:
        for c in (a,b):c.get('/').raise_for_status()
        cid=a.get('/api/campaigns').json()[0]['id'];other=b.get('/api/campaigns').json()[0]['id']
        start=time.monotonic();r=a.post(f'/api/campaigns/{cid}/generate',json={'channel':'邮件'})
        report['generation']={'status':r.status_code,'elapsed_ms':round((time.monotonic()-start)*1000),'output':r.json()}
        r.raise_for_status();old=r.json()
        # Explicitly reviewed revision; never approve the entire raw model output.
        body='拾光任务本支持手动添加任务和设置截止日期，也支持按周查看任务清单。\n示例产品，仅供学习'
        revised=a.post('/api/drafts/'+old['draft_id']+'/revisions',json={
            'expected_revision':old['id'],'title':'整理本周任务','body':body,'fact_ids':['F1','F2']})
        revised.raise_for_status();new=revised.json()
        approval=a.post('/api/revisions/'+new['id']+'/review',json={
            'state':'approved','version':new['version'],'facts_checked':True,'note':'逐字核对F1/F2合成规格并补齐学习用途说明'})
        approval.raise_for_status()
        frozen=a.post(f'/api/campaigns/{cid}/exports');frozen.raise_for_status();snapshot=frozen.json()
        eid=snapshot['id'];md=a.get('/api/exports/'+eid+'?format=markdown');md.raise_for_status()
        assert body in md.text and snapshot['copies'][0]['id']==new['id']
        report['delivery']={'export_id':eid,'approved_revision':new['id'],'json_status':a.get('/api/exports/'+eid).status_code,
                            'markdown_status':md.status_code,'markdown_bytes':len(md.content),'copies':len(snapshot['copies'])}
        checks={'campaign':b.get('/api/campaigns/'+cid).status_code,
                'revision':b.post('/api/drafts/'+old['draft_id']+'/revisions',json={
                    'expected_revision':new['id'],'title':'isolation probe','body':body,'fact_ids':['F1']}).status_code,
                'compare':b.get('/api/drafts/'+old['draft_id']+'/compare',params={'before':old['id'],'after':new['id']}).status_code,
                'json':b.get('/api/exports/'+eid).status_code,
                'markdown':b.get('/api/exports/'+eid+'?format=markdown').status_code}
        assert all(v==404 for v in checks.values()) and cid!=other
        assert b.get('/api/campaigns/'+other).json()['drafts']==[]
        report['cross_visitor']=checks
    Path('artifacts/public-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main(sys.argv[1])
