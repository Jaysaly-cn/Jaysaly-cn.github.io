"""Creates two synthetic visitor sessions and validates actual HTTP isolation."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import httpx

def run(base, output):
    result={'url':base,'created_at':datetime.now(timezone.utc).isoformat(),'synthetic':True,'checks':[]}
    with httpx.Client(base_url=base,timeout=150) as first, httpx.Client(base_url=base,timeout=150) as second:
        for client in (first,second):
            response=client.get('/');response.raise_for_status()
            assert 'httponly' in response.headers['set-cookie'].lower()
            if base.startswith('https:'):assert 'secure' in response.headers['set-cookie'].lower()
        a=first.get('/api/materials').json()[0];b=second.get('/api/materials').json()[0]
        assert a['id']!=b['id']
        draft={'question':'缓存命中时如何处理？','answer':'直接返回缓存内容。','quote':'缓存命中时直接返回缓存内容。'}
        response=first.post('/api/materials/'+a['id']+'/cards',json=draft);response.raise_for_status();card=response.json()
        assert second.post('/api/cards/'+card['id']+'/transition',json={'version':1,'action':'reject'}).status_code==404
        assert second.get('/api/export').json()['cards']==[]
        result['checks'].append('cross-session mutation 404 and export empty')
        response=first.post('/api/cards/'+card['id']+'/approve',json={**draft,'version':1,'checked':True});response.raise_for_status()
        response=first.post('/api/cards/'+card['id']+'/review',json={'version':2,'rating':3});response.raise_for_status()
        assert first.get('/api/due').json()==[]
        exported=first.get('/api/export').json()
        assert [e['action'] for e in exported['events']]==['created','approved','reviewed']
        result['checks'].append('manual draft approval review export')
        assert first.get('/api/cards',headers={'Origin':'https://invalid.example'}).status_code==403
        result['checks'].append('foreign origin 403')
        response=first.post('/api/materials/'+a['id']+'/generate')
        result['model']={'status':response.status_code,'body':response.json()}
        result['reviewed_snapshot']=exported
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':result['checks'],'model_status':result['model']['status']}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('url');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Choose a new output file')
    run(args.url,args.output)
