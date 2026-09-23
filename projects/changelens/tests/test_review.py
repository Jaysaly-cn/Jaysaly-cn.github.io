import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import model

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'review.db')) as c:
        d=c.post('/api/documents',json={'title':'规则'}).json()['id']
        ids=[c.post('/api/documents/'+d+'/versions',json={'label':str(i),'text':t}).json()['id'] for i,t in enumerate(['允许导出。\n保持不变。\n','不允许导出。\n保持不变。\n增加审计。\n'])]
        cid=c.post('/api/comparisons',json={'old_id':ids[0],'new_id':ids[1]}).json()['id']
        yield c,cid

ITEM={'summary':'导出规则由允许变为不允许。','old_quote':'允许导出。','new_quote':'不允许导出。'}

def create(c,cid):return c.post(f'/api/comparisons/{cid}/operations/0/impacts',json=ITEM)
def freeze(c,cid):return c.post(f'/api/comparisons/{cid}/briefs',json={'title':'规则变更','note':'合成数据人工复核验收'}).json()

def test_review_revision_and_frozen_brief(client):
    c,cid=client;a=create(c,cid).json();before=freeze(c,cid)
    assert before['confirmed_impacts']==[] and before['unreviewed_operations']==[0,2]
    reviewed=c.post('/api/impacts/'+a['id']+'/review',json={'version':1,'decision':'confirmed','note':'已核对双方引用与说明'})
    assert reviewed.status_code==200
    frozen=freeze(c,cid);assert len(frozen['confirmed_impacts'])==1 and frozen['unreviewed_operations']==[2]
    revision={**ITEM,'summary':'原文改为不允许导出，具体执行范围待业务确认。','version':2,'note':'补充影响边界避免过度推断'}
    assert c.post('/api/impacts/'+a['id']+'/revise',json=revision).json()['state']=='draft'
    assert c.post('/api/impacts/'+a['id']+'/revise',json=revision).status_code==409
    assert freeze(c,cid)['unreviewed_operations']==[0,2]
    assert c.get('/api/briefs/'+frozen['id']).json()==frozen
    assert any(row['id']==frozen['id'] for row in c.get(f'/api/comparisons/{cid}/briefs').json())
    assert len(c.get('/api/impacts/'+a['id']+'/history').json())==2

@pytest.mark.parametrize('index,item,code',[(1,ITEM,422),(-1,ITEM,404),(0,{**ITEM,'old_quote':'不允许导出。'},422),(2,{**ITEM,'old_quote':'原版不存在','new_quote':'增加审计。'},422)])
def test_invalid_evidence_or_blocks_rejected(client,index,item,code):
    c,cid=client
    assert c.post(f'/api/comparisons/{cid}/operations/{index}/impacts',json=item).status_code==code
    assert c.get(f'/api/comparisons/{cid}/impacts').json()==[]

def test_insert_allows_only_empty_old_quote(client):
    c,cid=client
    assert c.post(f'/api/comparisons/{cid}/operations/2/impacts',json={'summary':'新版增加审计记录条款。','old_quote':'','new_quote':'增加审计。'}).status_code==201

def test_model_failures_keep_raw_and_valid_output_stays_draft(client,monkeypatch):
    c,cid=client;monkeypatch.setattr(model,'configured',lambda:True)
    async def invalid(source):return json.dumps({**ITEM,'new_quote':'错误引文'})
    monkeypatch.setattr(model,'propose',invalid)
    assert c.post(f'/api/comparisons/{cid}/operations/0/suggest').status_code==422
    run=c.get(f'/api/comparisons/{cid}/model-runs').json()[0]
    assert run['raw'] and run['error']=='new_quote_mismatch' and run['impact_id'] is None
    async def valid(source):return json.dumps(ITEM)
    monkeypatch.setattr(model,'propose',valid)
    assert c.post(f'/api/comparisons/{cid}/operations/0/suggest').json()['state']=='draft'
    assert freeze(c,cid)['confirmed_impacts']==[]

@pytest.mark.parametrize('index',[0,1])
def test_real_model_outputs_replayed_without_auto_approval(client,monkeypatch,index):
    from pathlib import Path
    record=json.loads((Path(__file__).resolve().parents[1]/'artifacts/model-live.json').read_text(encoding='utf-8'))['records'][index]
    c,_=client;old=record['comparison']['old_version']['text'];new=record['comparison']['new_version']['text']
    did=c.post('/api/documents',json={'title':'真实输出回放'}).json()['id']
    ids=[c.post(f'/api/documents/{did}/versions',json={'label':str(i),'text':text}).json()['id'] for i,text in enumerate([old,new])]
    cid=c.post('/api/comparisons',json={'old_id':ids[0],'new_id':ids[1]}).json()['id']
    monkeypatch.setattr(model,'configured',lambda:True)
    async def replay(source):return record['runs'][0]['raw']
    monkeypatch.setattr(model,'propose',replay)
    assert c.post(f'/api/comparisons/{cid}/operations/0/suggest').status_code==record['status']
    assert freeze(c,cid)['confirmed_impacts']==[]
    assert freeze(c,cid)['unreviewed_operations']==[0]


def test_export_contains_exact_frozen_evidence_and_is_deterministic(client):
    import io,hashlib
    from zipfile import ZipFile
    c,cid=client;a=create(c,cid).json()
    assert c.post('/api/impacts/'+a['id']+'/review',json={'version':1,'decision':'confirmed','note':'核对导出引用与原文'}).status_code==200
    brief=freeze(c,cid);url='/api/briefs/'+brief['id']+'/export'
    first=c.get(url);assert first.status_code==200 and first.headers['content-type']=='application/zip'
    assert 'attachment' in first.headers['content-disposition']
    with ZipFile(io.BytesIO(first.content)) as z:
        assert set(z.namelist())=={'brief.html','brief.json','old-version.txt','new-version.txt','README.txt','manifest.json'}
        assert json.loads(z.read('brief.json'))==brief
        assert z.read('old-version.txt').decode()==brief['comparison']['old_version']['text']
        assert z.read('new-version.txt').decode()==brief['comparison']['new_version']['text']
        for name,sha in json.loads(z.read('manifest.json')).items():assert hashlib.sha256(z.read(name)).hexdigest()==sha
        assert '#2' in z.read('brief.html').decode()
    c.post('/api/impacts/'+a['id']+'/review',json={'version':2,'decision':'rejected','note':'后续审核发现仍有疑问'})
    assert c.get(url).content==first.content
    assert c.get('/api/briefs/missing/export').status_code==404


def test_export_escapes_untrusted_content(client):
    import io
    from zipfile import ZipFile
    c,cid=client
    brief=c.post(f'/api/comparisons/{cid}/briefs',json={'title':'<script>alert(1)</script>','note':'<img src=x onerror=alert(1)>'}).json()
    with ZipFile(io.BytesIO(c.get('/api/briefs/'+brief['id']+'/export').content)) as z:
        html=z.read('brief.html').decode()
        assert '<script>' not in html and '<img ' not in html
        assert '&lt;script&gt;' in html and '&lt;img ' in html
        assert "default-src 'none'" in html
