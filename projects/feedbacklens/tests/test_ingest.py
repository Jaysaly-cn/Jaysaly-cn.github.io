import sqlite3
import pytest
from app.ingest import ingest,similar

def raw(rows):return ('source_id,channel,text\n'+rows).encode('utf-8')

def test_reimport_and_different_ids_preserved(tmp_path):
    path=tmp_path/'test.db';data=raw('a,app,希望离线导出\nb,email,希望离线导出\n')
    assert ingest(path,data)['added']==2
    assert ingest(path,data)['same_file']
    assert similar(path,'a')[0]['character_similarity']==100

def test_conflict_rolls_back_batch(tmp_path):
    path=tmp_path/'test.db';ingest(path,raw('a,app,原文\n'))
    with pytest.raises(ValueError,match='conflict'):ingest(path,raw('b,web,新增\na,app,被改写\n'))
    conn=sqlite3.connect(path)
    try:
        assert conn.execute('SELECT count(*) FROM feedback').fetchone()[0]==1
        assert conn.execute('SELECT count(*) FROM imports').fetchone()[0]==1
    finally:conn.close()

@pytest.mark.parametrize('rows',['a,app,\n','a,app,文本,多余\n','a,app,文本\na,app,文本\n'])
def test_invalid_rows(tmp_path,rows):
    with pytest.raises(ValueError):ingest(tmp_path/'test.db',raw(rows))

def test_negation_is_only_a_candidate(tmp_path):
    path=tmp_path/'test.db';ingest(path,raw('a,app,希望增加离线导出功能。\nb,app,不希望增加离线导出功能。\n'))
    candidates=similar(path,'a')
    assert candidates[0]['character_similarity']>90
    assert 'duplicate' not in candidates[0]
