import json
import os
import sqlite3
from contextlib import contextmanager,asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI,HTTPException,Request
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,Field
from .diff import compare,digest,validate_text
from .security import install
from .review import SCHEMA,install_review

ROOT=Path(__file__).resolve().parents[1]
def now():return datetime.now(timezone.utc).isoformat()

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class Document(Strict):
    title:str=Field(min_length=1,max_length=100)

class Version(Strict):
    label:str=Field(min_length=1,max_length=100)
    text:str=Field(min_length=1,max_length=20000)

class Comparison(Strict):
    old_id:str=Field(min_length=1,max_length=100)
    new_id:str=Field(min_length=1,max_length=100)


def create_app(path=None):
    path=Path(path or os.getenv('CHANGELENS_DB',str(ROOT/'data/change.sqlite3')))
    @contextmanager
    def db():
        conn=sqlite3.connect(path,timeout=10);conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:yield conn
        finally:conn.close()
    @asynccontextmanager
    async def lifespan(app):
        path.parent.mkdir(parents=True,exist_ok=True)
        with db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,title TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,document_id TEXT REFERENCES documents(id),number INTEGER,label TEXT,text TEXT,sha256 TEXT,created_at TEXT,UNIQUE(document_id,number),UNIQUE(document_id,sha256));
            CREATE TABLE IF NOT EXISTS comparisons(id TEXT PRIMARY KEY,document_id TEXT REFERENCES documents(id),old_id TEXT REFERENCES versions(id),new_id TEXT REFERENCES versions(id),snapshot TEXT,created_at TEXT,UNIQUE(old_id,new_id));
            ''')
            c.executescript(SCHEMA)
        yield
    app=FastAPI(title='ChangeLens',version='0.1.0',lifespan=lifespan)
    install(app)
    install_review(app,db)

    @app.post('/api/documents',status_code=201)
    def create_document(item:Document):
        if not item.title.strip():raise HTTPException(422,'标题不能为空白')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT count(*) FROM documents').fetchone()[0]>=100:raise HTTPException(409,'文档上限100份')
            identity=uuid4().hex
            c.execute('INSERT INTO documents VALUES(?,?,?)',(identity,item.title,now()))
            return dict(c.execute('SELECT * FROM documents WHERE id=?',(identity,)).fetchone())

    @app.get('/api/documents')
    def documents():
        with db() as c:return [dict(r) for r in c.execute('SELECT * FROM documents ORDER BY created_at DESC,id')]

    @app.post('/api/documents/{identity}/versions',status_code=201)
    def add_version(identity:str,item:Version):
        try:validate_text(item.text)
        except ValueError as exc:raise HTTPException(422,str(exc))
        if not item.label.strip():raise HTTPException(422,'版本名不能为空白')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM documents WHERE id=?',(identity,)).fetchone():raise HTTPException(404,'文档不存在')
            sha=digest(item.text)
            if c.execute('SELECT 1 FROM versions WHERE document_id=? AND sha256=?',(identity,sha)).fetchone():raise HTTPException(409,'该文档已保存相同正文')
            if c.execute('SELECT count(*) FROM versions').fetchone()[0]>=500:raise HTTPException(409,'版本总量上限500份')
            number=c.execute('SELECT coalesce(max(number),0)+1 FROM versions WHERE document_id=?',(identity,)).fetchone()[0]
            vid=uuid4().hex
            c.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(vid,identity,number,item.label,item.text,sha,now()))
            return dict(c.execute('SELECT * FROM versions WHERE id=?',(vid,)).fetchone())

    @app.post('/api/documents/{identity}/versions/file',status_code=201)
    async def import_version(identity:str,request:Request,label:str):
        raw=await request.body()
        if len(raw)>80000:raise HTTPException(413,'文件最多80KB')
        try:text=raw.decode('utf-8')
        except UnicodeDecodeError:raise HTTPException(422,'请使用UTF-8文本文件')
        if not 1<=len(label)<=100 or not 1<=len(text)<=20000:
            raise HTTPException(422,'版本名需1至100字符，正文需1至20000字符')
        return await run_in_threadpool(add_version,identity,Version(label=label,text=text))

    @app.get('/api/documents/{identity}/versions')
    def versions(identity:str):
        with db() as c:
            if not c.execute('SELECT 1 FROM documents WHERE id=?',(identity,)).fetchone():raise HTTPException(404,'文档不存在')
            return [dict(r) for r in c.execute('SELECT id,document_id,number,label,sha256,created_at FROM versions WHERE document_id=? ORDER BY number',(identity,))]

    @app.get('/api/versions/{identity}')
    def version(identity:str):
        with db() as c:
            row=c.execute('SELECT * FROM versions WHERE id=?',(identity,)).fetchone()
            if not row:raise HTTPException(404,'版本不存在')
            return dict(row)

    @app.post('/api/comparisons',status_code=201)
    def comparison(item:Comparison):
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            rows=[c.execute('SELECT * FROM versions WHERE id=?',(vid,)).fetchone() for vid in (item.old_id,item.new_id)]
            if any(r is None for r in rows):raise HTTPException(404,'版本不存在')
            old,new=rows
            if old['document_id']!=new['document_id']:raise HTTPException(422,'只能比较同一文档的版本')
            if old['number']>=new['number']:raise HTTPException(422,'新版本序号必须大于旧版本')
            existing=c.execute('SELECT id,snapshot FROM comparisons WHERE old_id=? AND new_id=?',(item.old_id,item.new_id)).fetchone()
            if existing:return {'id':existing['id'],**json.loads(existing['snapshot'])}
            if c.execute('SELECT count(*) FROM comparisons').fetchone()[0]>=100:raise HTTPException(409,'对比上限100份')
            snapshot={'old_version':dict(old),'new_version':dict(new),'diff':compare(old['text'],new['text']),'created_at':now()}
            identity=uuid4().hex
            c.execute('INSERT INTO comparisons VALUES(?,?,?,?,?,?)',(identity,old['document_id'],item.old_id,item.new_id,json.dumps(snapshot,ensure_ascii=False),snapshot['created_at']))
            return {'id':identity,**snapshot}

    @app.get('/api/comparisons/{identity}')
    def read_comparison(identity:str):
        with db() as c:
            row=c.execute('SELECT snapshot FROM comparisons WHERE id=?',(identity,)).fetchone()
            if not row:raise HTTPException(404,'对比不存在')
            return {'id':identity,**json.loads(row['snapshot'])}
    app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='web')
    return app

app=create_app()
