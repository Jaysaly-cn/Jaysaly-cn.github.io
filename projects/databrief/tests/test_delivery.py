import csv
import io
import json
import zipfile
from app import delivery


def test_csv_preserves_order_handles_special_text_and_marks_truncation():
    values=['=1+1',' +SUM(A1:A2)','-2','@SUM(A1)','\t=1','quote,"newline\n',None,'','\\N',-2,1.25]
    record={'id':'synthetic','dataset_id':'synthetic-data','created_at':'2026-09-23',
            'sql':'SELECT synthetic', 'result':{'state':'succeeded','columns':['=header','same','same'],
            'rows':[[v,'text',3] for v in values],'truncated':True,'source_sha256':'synthetic-hash'}}
    with zipfile.ZipFile(io.BytesIO(delivery.bundle(record))) as archive:
        assert 'result-truncated.csv' in archive.namelist() and 'result.csv' not in archive.namelist()
        rows=list(csv.reader(io.StringIO(archive.read('result-truncated.csv').decode('utf-8-sig'))))
        assert rows[0]==["'=header",'same','same']
        assert [r[0] for r in rows[1:]]==["'=1+1","' +SUM(A1:A2)","'-2","'@SUM(A1)","'\t=1",'quote,"newline\n','\\N','','\\N','-2','1.25']
        assert json.loads(archive.read('snapshot.json'))==record
        readme=archive.read('README.txt').decode()
        assert '不是完整结果' in readme and '共处理6个' in readme
