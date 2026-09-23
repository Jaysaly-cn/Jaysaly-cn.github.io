import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from uuid import uuid4
from rapidfuzz.fuzz import ratio

def ingest(path, raw):
    if len(raw)>1_000_000:raise ValueError('CSV exceeds 1MB')
    text=raw.decode('utf-8-sig',errors='strict')
    reader=csv.DictReader(io.StringIO(text,newline=''),strict=True)
    if reader.fieldnames!=['source_id','channel','text']:raise ValueError('Expected source_id,channel,text header')
    rows=list(reader)
    if not 1<=len(rows)<=500:raise ValueError('Expected 1..500 rows')
    seen=set()
    for row in rows:
        if set(row)!=set(reader.fieldnames) or any(not isinstance(v,str) or not v.strip() for v in row.values()):
            raise ValueError('Missing or extra values')
        if len(row['source_id'])>200 or len(row['channel'])>100 or len(row['text'])>4000:raise ValueError('Field too long')
        if row['source_id'] in seen:raise ValueError('Duplicate source_id within file')
        seen.add(row['source_id'])
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(raw).hexdigest()
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.executescript('''CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY,sha256 TEXT UNIQUE,raw BLOB);
        CREATE TABLE IF NOT EXISTS feedback(source_id TEXT PRIMARY KEY,channel TEXT,text TEXT);
        CREATE TABLE IF NOT EXISTS import_rows(import_id TEXT REFERENCES imports(id),line INTEGER,source_id TEXT REFERENCES feedback(source_id));''')
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            previous=conn.execute('SELECT id FROM imports WHERE sha256=?',(digest,)).fetchone()
            if previous:return {'import_id':previous[0],'added':0,'reused':len(rows),'same_file':True}
            if conn.execute('SELECT count(*) FROM imports').fetchone()[0]>=100:raise ValueError('Import capacity 100 exceeded')
            batch=uuid4().hex;added=0
            conn.execute('INSERT INTO imports VALUES(?,?,?)',(batch,digest,raw))
            for line,row in enumerate(rows,2):
                existing=conn.execute('SELECT channel,text FROM feedback WHERE source_id=?',(row['source_id'],)).fetchone()
                if existing and existing!=(row['channel'],row['text']):raise ValueError('source_id content conflict: '+row['source_id'])
                if not existing:
                    conn.execute('INSERT INTO feedback VALUES(?,?,?)',(row['source_id'],row['channel'],row['text']));added+=1
                conn.execute('INSERT INTO import_rows VALUES(?,?,?)',(batch,line,row['source_id']))
            if conn.execute('SELECT count(*) FROM feedback').fetchone()[0]>500:raise ValueError('Workspace capacity 500 exceeded')
        return {'import_id':batch,'added':added,'reused':len(rows)-added,'same_file':False}

def similar(path, source_id):
    with closing(sqlite3.connect(path)) as conn:
        row=conn.execute('SELECT text FROM feedback WHERE source_id=?',(source_id,)).fetchone()
        if row is None:raise ValueError('Unknown source_id')
        candidates=[{'source_id':other,'text':text,'character_similarity':round(ratio(row[0],text),2)}
                    for other,text in conn.execute('SELECT source_id,text FROM feedback WHERE source_id<>?',(source_id,))]
    return sorted(candidates,key=lambda x:(-x['character_similarity'],x['source_id']))[:10]

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('csv',type=Path);parser.add_argument('--db',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(ingest(args.db,args.csv.read_bytes()),ensure_ascii=False))
