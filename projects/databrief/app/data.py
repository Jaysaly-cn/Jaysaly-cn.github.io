import csv
import io
import json
import math
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

MAX_BYTES=2_000_000


def number(text):
    # Leading zero identifiers, dates, percentages and scientific notation remain text.
    if not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?',text):return None
    if '.' not in text:
        value=int(text)
        return value if -(2**63)<=value<2**63 else None
    value=float(text)
    return value if math.isfinite(value) else None


def parse(raw):
    if not raw or len(raw)>MAX_BYTES:raise ValueError('CSV必须非空且不超过2MB')
    try:
        reader=csv.reader(io.StringIO(raw.decode('utf-8-sig'),newline=''),strict=True)
        headers=next(reader)
        if not 1<=len(headers)<=40 or any(not h.strip() or len(h)>120 for h in headers):
            raise ValueError('必须有1至40个非空列名，每列名最多120字符')
        headers=[h.strip() for h in headers]
        if len(set(headers))!=len(headers):raise ValueError('列名不可重复')
        rows=[]
        for row in reader:
            if len(row)!=len(headers):raise ValueError('行的列数不一致，拒绝导入')
            if any(len(cell)>10000 or '\x00' in cell for cell in row):raise ValueError('单元格过长或含空字节')
            rows.append([cell.strip() or None for cell in row])
            if len(rows)>10000:raise ValueError('最多10000行，不会静默截断')
    except (UnicodeError,csv.Error,StopIteration) as exc:
        raise ValueError('需要UTF-8编码的有效CSV文件') from exc
    if not rows:raise ValueError('CSV至少需要一行数据')
    columns=[]
    for index,header in enumerate(headers):
        present=[r[index] for r in rows if r[index] is not None]
        numeric=bool(present) and all(number(v) is not None for v in present)
        kind='REAL' if numeric and any('.' in v for v in present) else 'INTEGER' if numeric else 'TEXT'
        if numeric:
            for row in rows:
                if row[index] is not None:row[index]=number(row[index])
        values=[r[index] for r in rows if r[index] is not None]
        column={'key':f'c{index+1}','name':header,'type':kind,'missing':len(rows)-len(values),
                'distinct':len(set(values)),'sample':values[:5]}
        if numeric:column.update(min=min(values),max=max(values))
        columns.append(column)
    return {'sha256':sha256(raw).hexdigest(),'row_count':len(rows),'columns':columns,'rows':rows,
            'notice':'单元格首尾空白已去除，空白转NULL；前导零标识符保留文本。小数使用浮点近似，不用于精确账务。公式只作文本。'}


@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=15);db.row_factory=sqlite3.Row
    try:
        with db:yield db
    finally:db.close()


def initialize(path):
    with connect(path) as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY,name TEXT NOT NULL,
          sha256 TEXT UNIQUE NOT NULL,raw BLOB NOT NULL,parsed TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,dataset_id TEXT NOT NULL,sql TEXT NOT NULL,
          result TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,dataset_id TEXT NOT NULL,question TEXT NOT NULL,
          model TEXT NOT NULL,raw TEXT NOT NULL,proposal TEXT NOT NULL,state TEXT NOT NULL,error TEXT NOT NULL,created_at TEXT NOT NULL);''')


def import_csv(path,name,raw):
    if not name.strip() or len(name)>120:raise ValueError('数据集名称应为1至120字符')
    parsed=parse(raw)
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT id FROM datasets WHERE sha256=?',(parsed['sha256'],)).fetchone()
        if existing:return {'id':existing['id'],'duplicate':True}
        if db.execute('SELECT count(*) FROM datasets').fetchone()[0]>=20:raise ValueError('工作台最多20个数据集')
        identity=uuid4().hex
        db.execute('INSERT INTO datasets VALUES(?,?,?,?,?,?)',(identity,name.strip(),parsed['sha256'],raw,
                   json.dumps(parsed,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        return {'id':identity,'duplicate':False}


def dataset(path,identity):
    with connect(path) as db:
        row=db.execute('SELECT name,parsed FROM datasets WHERE id=?',(identity,)).fetchone()
        if not row:raise KeyError('数据集不存在')
        return {'id':identity,'name':row['name'],**json.loads(row['parsed'])}


def query(parsed,sql):
    if not isinstance(sql,str) or not sql.strip() or len(sql)>8000:raise ValueError('查询应为1至8000字符')
    db=sqlite3.connect(':memory:')
    try:
        columns=parsed['columns']
        db.execute('CREATE TABLE data('+','.join(f'"{c["key"]}" {c["type"]}' for c in columns)+')')
        db.executemany('INSERT INTO data VALUES('+','.join('?' for c in columns)+')',parsed['rows'])
        db.commit()
        db.execute('PRAGMA query_only=ON')
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,200000)
        db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH,8000)
        db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN,100)
        db.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH,100)
        db.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT,10)
        functions={'count','sum','avg','min','max','round','abs','coalesce','ifnull','nullif','lower','upper','length','substr','substring','trim','total'}
        def authorize(action,arg1,arg2,dbname,trigger):
            if action==sqlite3.SQLITE_SELECT:return sqlite3.SQLITE_OK
            if action==sqlite3.SQLITE_READ and arg1=='data':return sqlite3.SQLITE_OK
            if action==sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() in functions:return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        db.set_authorizer(authorize)
        started=time.monotonic();steps=[0]
        def progress():
            steps[0]+=1000
            return int(steps[0]>1_000_000 or time.monotonic()-started>1)
        db.set_progress_handler(progress,1000)
        cursor=db.execute(sql)
        if cursor.description is None:raise ValueError('只允许返回结果的只读查询')
        result=cursor.fetchmany(201)
        for row in result:
            if any(isinstance(v,bytes) for v in row):raise ValueError('结果包含二进制值，无法作为分析表格保存；请查询文本或数值')
            if any(isinstance(v,float) and not math.isfinite(v) for v in row):raise ValueError('结果包含非有限数值，请调整查询')
        return {'columns':[c[0] for c in cursor.description],'rows':[list(r) for r in result[:200]],
                'truncated':len(result)>200,'source_sha256':parsed['sha256'],'sql':sql,
                'notice':'最多展示200行；未排序查询无稳定顺序。SQL可执行不代表业务口径正确。'}
    except sqlite3.Error as exc:
        raise ValueError('查询被拒绝或执行失败：'+str(exc)) from exc
    finally:db.close()


def execute(path,identity,sql,context=None):
    parsed=dataset(path,identity)
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT count(*) FROM runs WHERE dataset_id=?',(identity,)).fetchone()[0]>=100:
            raise ValueError('每数据集最多100条查询记录')
        try:result={'state':'succeeded',**query(parsed,sql)}
        except ValueError as exc:result={'state':'failed','error':str(exc),'source_sha256':parsed['sha256']}
        if context is not None:result['review_context']=context
        run_id=uuid4().hex
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(run_id,identity,sql,json.dumps(result,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        return {'id':run_id,**result}
