"""Explicit bounded runner for persisted extraction plans; no auto-approval or web collection."""
import argparse
import json
import os
import httpx


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['plan','run','status','pause','resume'])
    p.add_argument('project');p.add_argument('--batch');p.add_argument('--source',action='append',default=[])
    p.add_argument('--base-url',default='http://127.0.0.1:8766')
    p.add_argument('--steps',type=int,default=1);p.add_argument('--retry-failed',action='store_true')
    args=p.parse_args()
    if not 1<=args.steps<=32:p.error('--steps must be between 1 and 32')
    if args.command!='plan' and not args.batch:p.error('--batch is required')
    if args.command=='plan' and not args.source:p.error('select at least one --source')
    token=os.getenv('EVIDENCEBRIEF_ACCESS_TOKEN','')
    headers={'Authorization':'Bearer '+token} if token else {}
    with httpx.Client(base_url=args.base_url,headers=headers,timeout=120,follow_redirects=False) as c:
        base=f'/api/projects/{args.project}/batches'
        def call(method,route,body=None):
            r=c.request(method,route,json=body);r.raise_for_status();return r.json()
        if args.command=='plan':result=call('POST',base,{'source_ids':args.source})
        else:
            base+='/'+args.batch
            if args.command=='status':result=call('GET',base)
            elif args.command in ('pause','resume'):result=call('POST',base+'/pause',{'paused':args.command=='pause'})
            else:
                result=call('GET',base)
                for _ in range(args.steps):
                    if result['paused'] or result['complete']:break
                    before=sum(s['attempts'] for s in result['steps'])
                    previous_failed={i:s['attempts'] for i,s in enumerate(result['steps']) if s['state']=='failed'}
                    result=call('POST',base+'/next',{'retry_failed':args.retry_failed})
                    print(json.dumps({'batch':result['id'],'states':[s['state'] for s in result['steps']]},ensure_ascii=False),flush=True)
                    if sum(s['attempts'] for s in result['steps'])==before:break
                    if any(s['state']=='failed' and s['attempts']>previous_failed.get(i,0) for i,s in enumerate(result['steps'])):break
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if args.command=='run' and any(s['state']=='failed' for s in result['steps']):raise SystemExit(2)


if __name__=='__main__':
    try:main()
    except httpx.HTTPError as exc:raise SystemExit('请求未完成：'+type(exc).__name__+'；用status核对计划后再继续。')
