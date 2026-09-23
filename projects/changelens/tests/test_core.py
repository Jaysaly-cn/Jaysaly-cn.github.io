import random
import pytest
from fastapi.testclient import TestClient
from app.diff import compare,digest
from app.main import create_app

@pytest.mark.parametrize('old,new',[
 ('允许导出。\n','不允许导出。\n'),('甲\r\n乙\r\n','甲\n乙\n'),
 ('a\nb\na\nb\n','a\nb\nb\n'),('🙂旧版\n','🙂新版\n'),
 ('第一条\n第二条\n','第二条\n第一条\n'),('same','same'),
 ('  规则\n','规则\n'),('只有付费用户可导出。','所有用户可导出。'),
])
def test_exact_offsets_and_reconstruction(old,new):
    result=compare(old,new)
    assert ''.join(op['old_text'] for op in result['operations'])==old
    assert ''.join(op['new_text'] for op in result['operations'])==new
    for op in result['operations']:
        assert old[op['old_start']:op['old_end']]==op['old_text']
        assert new[op['new_start']:op['new_end']]==op['new_text']
    assert result['old_sha256']==digest(old)
    assert (result['change_count']==0)==(old==new)


def test_seeded_repeated_line_edits_reconstruct():
    rng=random.Random(20260923)
    for _ in range(100):
        old=''.join(rng.choice(['规则甲\n','规则乙\n','\n','🙂\r\n']) for _ in range(30))
        new=''.join(rng.choice(['规则甲\n','规则乙\n','\n','🙂\r\n']) for _ in range(30))
        result=compare(old,new)
        assert ''.join(op['old_text'] for op in result['operations'])==old
        assert ''.join(op['new_text'] for op in result['operations'])==new


def test_version_immutability_and_comparison_persistence(tmp_path):
    path=tmp_path/'app.db'
    with TestClient(create_app(path)) as c:
        doc=c.post('/api/documents',json={'title':'合成产品规则'}).json()
        url='/api/documents/'+doc['id']+'/versions'
        a=c.post(url,json={'label':'初版','text':'  允许导出。\r\n'}).json()
        b=c.post(url,json={'label':'修订版','text':'  不允许导出。\r\n'}).json()
        assert a['text']=='  允许导出。\r\n' and b['number']==2
        assert c.post(url,json={'label':'同文','text':b['text']}).status_code==409
        snapshot=c.post('/api/comparisons',json={'old_id':a['id'],'new_id':b['id']}).json()
        assert c.post('/api/comparisons',json={'old_id':a['id'],'new_id':b['id']}).json()==snapshot
        assert c.post(url,json={'label':'第三版','text':'全部禁止导出。'}).status_code==201
        assert c.get('/api/versions/'+a['id']).json()==a
        assert c.get('/api/comparisons/'+snapshot['id']).json()==snapshot
    with TestClient(create_app(path)) as c:
        assert c.get('/api/comparisons/'+snapshot['id']).json()==snapshot


def test_invalid_pairs_and_limits(tmp_path):
    with TestClient(create_app(tmp_path/'app.db')) as c:
        ids=[]
        for title in ['甲','乙']:
            doc=c.post('/api/documents',json={'title':title}).json()
            url='/api/documents/'+doc['id']+'/versions'
            assert c.post(url,json={'label':'超长行','text':'a'*4001}).status_code==422
            assert c.post(url,json={'label':'过多行','text':'a\n'*501}).status_code==422
            ids.append(c.post(url,json={'label':'初版','text':'正文'}).json()['id'])
        assert c.post('/api/comparisons',json={'old_id':ids[0],'new_id':ids[1]}).status_code==422
        assert c.post('/api/comparisons',json={'old_id':ids[0],'new_id':ids[0]}).status_code==422
        assert c.post('/api/comparisons',json={'old_id':ids[0],'new_id':'missing'}).status_code==404
        assert c.get('/api/documents',headers={'Origin':'https://evil.test'}).status_code==403


def test_file_import_preserves_utf8_bytes_and_duplicate_identity(tmp_path):
    with TestClient(create_app(tmp_path/'files.db')) as c:
        doc=c.post('/api/documents',json={'title':'文件导入验收'}).json()['id']
        endpoint=f'/api/documents/{doc}/versions/file'
        raw='\ufeff  中文🙂\r\n第二行\r\n'.encode('utf-8')
        response=c.post(endpoint,params={'label':'文件初版'},content=raw)
        assert response.status_code==201
        version=response.json();assert version['text'].encode('utf-8')==raw
        assert version['sha256']==digest(raw.decode('utf-8'))
        assert c.post(endpoint,params={'label':'重复文件'},content=raw).status_code==409
        assert len(c.get(f'/api/documents/{doc}/versions').json())==1
        lf=raw.replace(b'\r\n',b'\n')
        other=c.post(endpoint,params={'label':'换行变更'},content=lf).json()
        result=c.post('/api/comparisons',json={'old_id':version['id'],'new_id':other['id']}).json()
        assert result['diff']['change_count']>0


@pytest.mark.parametrize('body,code',[(b'\xff\xfe',422),(b'a'*80001,413),(b'',422)],ids=['invalid-utf8','oversize','empty'])
def test_invalid_import_does_not_create_version(tmp_path,body,code):
    with TestClient(create_app(tmp_path/'files.db')) as c:
        doc=c.post('/api/documents',json={'title':'文件导入验收'}).json()['id']
        assert c.post(f'/api/documents/{doc}/versions/file',params={'label':'错误输入'},content=body).status_code==code
        assert c.get(f'/api/documents/{doc}/versions').json()==[]
