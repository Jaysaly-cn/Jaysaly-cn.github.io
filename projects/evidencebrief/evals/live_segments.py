"""Real local model integration on a synthetic long source; no semantic score."""
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from app.main import create_app


def main():
    if os.getenv('EB_MODEL_BASE_URL')!='http://127.0.0.1:8771/v1':
        raise SystemExit('Only the local model is allowed for this evaluation')
    content=('本段仅包含背景介绍，不提供产品定价或导入格式的信息。\n'*170)+'Alpha 团队版每月 19 元，支持导入 Markdown 文档。'
    raw=[];original=httpx.AsyncClient
    async def capture(r):
        await r.aread();raw.append(r.json())
    def recorder(**kw):return original(event_hooks={'response':[capture]},**kw)
    results=[]
    with tempfile.TemporaryDirectory() as directory:
        with patch('app.model.httpx.AsyncClient',recorder),TestClient(create_app(Path(directory)/'long.db')) as c:
            p=c.post('/api/projects',json={'title':'合成长文验证','question':'研究正文末尾定价和格式','entities':['Alpha'],'dimensions':['价格','导入格式']}).json()
            s=c.post(f'/api/projects/{p["id"]}/sources',json={'entity':'Alpha','title':'合成长文','content':content}).json()
            base=f'/api/projects/{p["id"]}/sources/{s["id"]}'
            for w in c.get(base+'/segments').json()['segments']:
                raw.clear();r=c.post(base+f'/suggest?segment={w["index"]}')
                results.append({'segment':w,'status':r.status_code,'result':r.json(),'provider_responses':list(raw)})
                print(json.dumps({'segment':w['index'],'status':r.status_code,'result':r.json()},ensure_ascii=False),flush=True)
            coverage=c.get(base+'/segments').json()
    Path('artifacts/live-segments.json').write_text(json.dumps({'at':datetime.now(timezone.utc).isoformat(),
        'scope':'One synthetic long document, development integration only; not recall or accuracy',
        'model':os.getenv('EB_MODEL'),'content':content,'tail_offset':content.index('Alpha'),
        'results':results,'coverage':coverage},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
