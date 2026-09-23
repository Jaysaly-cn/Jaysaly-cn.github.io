import json
import pytest
from app import data

RAW='渠道,订单数,金额,编码\n搜索,2,19.5,001\n社交,3,30.0,002\n搜索,,10.5,003\n'.encode()


def test_profile_preserves_ids_and_counts_missing():
    parsed=data.parse(RAW)
    assert [c['type'] for c in parsed['columns']]==['TEXT','INTEGER','REAL','TEXT']
    assert parsed['columns'][1]['missing']==1
    assert parsed['rows'][0][3]=='001'
    assert parsed['columns'][2]['min']==10.5


def test_grouped_aggregation_and_null_semantics():
    result=data.query(data.parse(RAW),'SELECT c1 AS channel, sum(c2) AS orders, round(sum(c3),2) AS amount FROM data GROUP BY c1 ORDER BY c1')
    assert sorted(result['rows'])==sorted([['搜索',2,30.0],['社交',3,30.0]])
    assert result['columns']==['channel','orders','amount']
    assert data.query(data.parse(RAW),'SELECT count(*),count(c2) FROM data')['rows']==[[3,2]]


@pytest.mark.parametrize('sql',[
    'DROP TABLE data','DELETE FROM data','UPDATE data SET c1="bad"',
    "ATTACH DATABASE 'file.db' AS secret",'PRAGMA table_info(data)',
    'SELECT name FROM sqlite_master','SELECT randomblob(1000000000)',
    "SELECT load_extension('anything')",'SELECT * FROM data; SELECT * FROM data',
    'WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT * FROM x',
])
def test_unsafe_or_unbounded_operations_rejected(sql):
    with pytest.raises(ValueError):data.query(data.parse(RAW),sql)


def test_result_row_cap_is_explicit():
    parsed=data.parse(('n\n'+'\n'.join(map(str,range(300)))).encode())
    result=data.query(parsed,'SELECT * FROM data ORDER BY c1')
    assert len(result['rows'])==200 and result['truncated']


def test_expensive_query_interrupted():
    parsed=data.parse(('n\n'+'\n'.join(map(str,range(300)))).encode())
    with pytest.raises(ValueError,match='interrupted'):
        data.query(parsed,'SELECT sum(a.c1*b.c1*c.c1) FROM data a,data b,data c')


@pytest.mark.parametrize('raw',[b'a,a\n1,2',b'a,b\n1',b'a\n',b'\xff',b'a\n"unterminated'])
def test_invalid_csv_not_silently_repaired(raw):
    with pytest.raises(ValueError):data.parse(raw)


def test_quoted_multiline_and_formula_remain_text():
    parsed=data.parse(b'name,note\nAlice,"line one\nline two"\nBob,=1+1\n')
    assert parsed['rows'][0][1]=='line one\nline two' and parsed['rows'][1][1]=='=1+1'


def test_persistent_source_dedup_and_query_audit(tmp_path):
    path=tmp_path/'data.db';data.initialize(path)
    first=data.import_csv(path,'渠道订单',RAW)
    assert data.import_csv(path,'重复',RAW)=={'id':first['id'],'duplicate':True}
    result=data.execute(path,first['id'],'SELECT sum(c3) FROM data')
    assert result['rows']==[[60.0]]
    failed=data.execute(path,first['id'],'DELETE FROM data')
    assert failed['state']=='failed'
    with data.connect(path) as db:
        assert db.execute('SELECT raw FROM datasets').fetchone()['raw']==RAW
        assert db.execute('SELECT count(*) FROM runs').fetchone()[0]==2
        assert json.loads(db.execute('SELECT result FROM runs WHERE id=?',(result['id'],)).fetchone()['result'])['rows']==[[60.0]]
    assert data.dataset(path,first['id'])['row_count']==3
