from fastapi.testclient import TestClient
from app.main import create_app
from app.db import connect, initialize


def test_revision_changes_retrieval_without_rewriting_old_answer(tmp_path):
    with TestClient(create_app(tmp_path/'versions.db')) as c:
        payload={'title':'激活码恢复','content':'离线激活码失效后，由管理员核对设备，再重新生成。','source':'合成初版','audience':'public'}
        did=c.post('/api/documents',json=payload).json()['id']
        old=c.post('/api/ask',json={'question':'离线激活码恢复流程'}).json()
        update={**payload,'version':1,'content':'离线激活码失效后，必须先撤销旧码，再核对设备授权并重新生成。','change_note':'补充撤销旧码这一必要步骤'}
        revised=c.patch('/api/documents/'+did,json=update)
        assert revised.status_code==200 and revised.json()['version']==2
        check=c.post('/api/runs/'+old['id']+'/rechecks').json()
        assert check['snapshot']['before']==old
        assert check['snapshot']['after']['citations'][0]['version']==2
        assert '撤销旧码' in check['snapshot']['after']['citations'][0]['content']
        assert c.get('/api/runs/'+old['id']).json()==old
        history=c.get('/api/documents/'+did+'/history').json()
        assert [v['version'] for v in history['versions']]==[1,2]
        assert history['versions'][0]['snapshot']['content']==payload['content']
        assert history['versions'][1]['change_note']==update['change_note']
        assert c.patch('/api/documents/'+did,json=update).status_code==409
        assert c.patch('/api/documents/'+did,json={**update,'version':2}).status_code==422
        c.delete('/api/documents/'+did)
        deleted=c.get('/api/documents/'+did+'/history').json()
        assert deleted['current'] is None and deleted['versions']==history['versions']


def test_scope_change_and_restored_seed_preserve_history(tmp_path):
    with TestClient(create_app(tmp_path/'scope.db')) as c:
        c.post('/api/seed')
        doc=next(d for d in c.get('/api/documents').json() if d['id']=='kb-refund')
        update={key:doc[key] for key in ('title','content','source','audience','version')}
        update.update(audience='internal',change_note='合成演示转为内部核对范围')
        assert c.patch('/api/documents/kb-refund',json=update).status_code==200
        run=c.post('/api/ask',json={'question':'首次购买订阅退款条件'}).json()
        assert all(x['document_id']!='kb-refund' for x in run['citations'])
        c.delete('/api/documents/kb-refund')
        assert c.post('/api/seed').json()['inserted']==1
        history=c.get('/api/documents/kb-refund/history').json()
        assert [r['version'] for r in history['versions']]==[1,2,3]
        assert history['versions'][1]['snapshot']['audience']=='internal'
        assert history['current']['audience']=='public'


def test_existing_database_migration_records_current_only_and_is_idempotent(tmp_path):
    path=tmp_path/'legacy.db'
    with connect(path) as db:
        db.execute('CREATE TABLE documents(id TEXT PRIMARY KEY,title TEXT,content TEXT,source TEXT,audience TEXT,version INTEGER,created_at TEXT)')
        db.execute("INSERT INTO documents VALUES('legacy','资料','历史正文','旧库','internal',7,'2026-01-01')")
    initialize(path);initialize(path)
    with TestClient(create_app(path)) as c:
        history=c.get('/api/documents/legacy/history').json()
        assert len(history['versions'])==1 and history['versions'][0]['version']==7
        assert '更早历史不可恢复' in history['versions'][0]['change_note']
        assert c.get('/api/documents/missing/history').status_code==404


def test_demo_revision_and_history_are_visitor_local(tmp_path):
    from app.demo import create_demo_app
    with TestClient(create_demo_app(tmp_path),base_url='https://testserver') as c:
        c.get('/')
        doc=next(d for d in c.get('/api/documents').json() if d['id']=='kb-refund')
        update={key:doc[key] for key in ('title','content','source','audience','version')}
        update.update(content='合成修订：退款必须由人工核对，演示不承诺批准。',change_note='第一位访客的独立修改说明')
        assert c.patch('/api/documents/kb-refund',json=update).status_code==200
        c.cookies.clear();c.get('/')
        history=c.get('/api/documents/kb-refund/history').json()
        assert len(history['versions'])==1 and history['current']['content']==doc['content']
