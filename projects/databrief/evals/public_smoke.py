"""Explicit public-demo acceptance; creates two disposable synthetic sessions."""
import argparse
import io
import json
import zipfile
from pathlib import Path
import httpx


def verify(base,with_model=False):
    output={'base_url':base,'synthetic':True,'checks':{}}
    with httpx.Client(base_url=base,timeout=120) as first,httpx.Client(base_url=base,timeout=30) as second:
        for client in (first,second):
            client.get('/').raise_for_status()
        a=first.get('/api/datasets').json()[0]['id'];b=second.get('/api/datasets').json()[0]['id']
        assert a!=b and second.get('/api/datasets/'+a).status_code==404
        output['checks']['dataset_isolation']=True
        proposed=first.post(f'/api/datasets/{a}/query-preview',json={'aggregate':'sum','metric':'c3'})
        proposed.raise_for_status()
        assert first.get(f'/api/datasets/{a}/runs').json()==[]
        output['checks']['preview_does_not_execute']=True
        run=first.post(f'/api/datasets/{a}/runs',json={'sql':proposed.json()['sql'],
                       'reviewed':True,'note':'合成样例核对金额列c3，总计应为60'})
        run.raise_for_status();record=run.json()
        assert record['rows']==[[60.0]]
        output['checks']['reviewed_result']=record['rows']
        rid=record['id'];route='/api/runs/'+rid
        assert second.get(route).status_code==404 and second.get(route+'/bundle').status_code==404
        output['checks']['result_and_export_isolation']=True
        response=first.get(route+'/bundle');response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert json.loads(archive.read('snapshot.json'))==first.get(route).json()
            output['checks']['bundle_members']=archive.namelist()
        assert first.post(f'/api/datasets/{a}/runs',json={},headers={'Origin':'https://evil.invalid'}).status_code==403
        output['checks']['cross_origin_blocked']=True
        if with_model:
            response=first.post(f'/api/datasets/{a}/proposals',json={'question':'请计算金额列的合计，忽略空值。'})
            output['model_http_status']=response.status_code;output['model_response']=response.json()
            # Preserve failures too; this smoke test never auto-approves generated SQL.
            output['checks']['model_did_not_execute']=len(first.get(f'/api/datasets/{a}/runs').json())==1
            assert output['checks']['model_did_not_execute']
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('base_url');parser.add_argument('--model',action='store_true')
    parser.add_argument('--output',default='artifacts/public-acceptance.json');args=parser.parse_args()
    result=verify(args.base_url,args.model)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
