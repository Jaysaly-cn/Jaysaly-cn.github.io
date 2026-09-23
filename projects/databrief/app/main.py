import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
from typing import Annotated,Literal
from uuid import uuid4
from fastapi import FastAPI,HTTPException,Request,Query
from fastapi.responses import JSONResponse,FileResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,StringConstraints,Field
from . import data,model,security,builder,delivery


class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class Question(Strict):
    question:Annotated[str,StringConstraints(strip_whitespace=True,min_length=2,max_length=1000)]
class Proposal(Strict):
    sql:Annotated[str,StringConstraints(strip_whitespace=True,max_length=8000)]
    explanation:Annotated[str,StringConstraints(max_length=2000)]
    limitations:Annotated[str,StringConstraints(max_length=2000)]
class Execution(Strict):
    sql:Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=8000)]
    proposal_id:str|None=Field(default=None,max_length=32)
    note:Annotated[str,StringConstraints(strip_whitespace=True,min_length=5,max_length=1000)]
    reviewed:bool=False

class Filter(Strict):
    column:Annotated[str,StringConstraints(max_length=4)]
    operator:Literal['eq','ne','gte','lte','missing','present']
    value:Annotated[str,StringConstraints(max_length=500)]=''
class VisualQuery(Strict):
    aggregate:Literal['rows','count','distinct','sum','avg','min','max']='rows'
    metric:Annotated[str,StringConstraints(max_length=4)]=''
    group:Annotated[str,StringConstraints(max_length=4)]=''
    nulls:Literal['exclude','zero']='exclude'
    order:Literal['asc','desc']='desc'
    filter:Filter|None=None


def create_app(path=None):
    path=path or os.getenv('DATABRIEF_DB',str(Path(__file__).resolve().parents[1]/'data/databrief.sqlite3'))
    @asynccontextmanager
    async def lifespan(app):
        data.initialize(path)
        yield
    app=FastAPI(title='DataBrief',lifespan=lifespan);security.install(app);lock=asyncio.Lock()
    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse({'detail':'数据记录不存在'},status_code=404)
    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({'detail':str(exc)},status_code=422)
    @app.get('/api/status')
    def status():return {'model_configured':model.configured(),'mode':'local-single-workspace','model_input':'schema and question only; no row values'}
    @app.post('/api/datasets',status_code=201)
    async def upload(request:Request,name:str=Query(min_length=1,max_length=120)):
        return data.import_csv(path,name,await request.body())
    @app.get('/api/datasets')
    def listing():
        with data.connect(path) as db:return [dict(r) for r in db.execute('SELECT id,name,sha256,created_at FROM datasets ORDER BY created_at DESC')]
    @app.get('/api/datasets/{did}')
    def profile(did:str):
        source=data.dataset(path,did);source['preview']=source.pop('rows')[:20]
        return source
    @app.post('/api/datasets/{did}/query-preview')
    def visual_query(did:str,request:VisualQuery):
        return builder.preview(data.dataset(path,did),request.model_dump())
    @app.post('/api/datasets/{did}/proposals',status_code=201)
    async def propose(did:str,request:Question):
        source=data.dataset(path,did)
        if not model.configured():raise HTTPException(503,'免费模型未配置，可以手工编写SQL')
        if lock.locked():raise HTTPException(409,'模型正在处理，请稍后再试')
        async with lock:
            with data.connect(path) as db:
                if db.execute('SELECT count(*) FROM proposals WHERE dataset_id=?',(did,)).fetchone()[0]>=30:raise HTTPException(409,'每数据集最多30次模型提议')
            raw='';error='';proposal={}
            try:
                raw=await model.propose(source,request.question)
                proposal=Proposal.model_validate_json(raw).model_dump()
            except Exception as exc:error=type(exc).__name__
            identity=uuid4().hex
            with data.connect(path) as db:
                db.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?)',(identity,did,request.question,os.getenv('DBR_MODEL',''),raw,json.dumps(proposal,ensure_ascii=False),'failed' if error else 'proposed',error,datetime.now(timezone.utc).isoformat()))
            if error:raise HTTPException(502,'模型提议未通过协议检查，原始失败已保留')
            return {'id':identity,'question':request.question,**proposal,'notice':'尚未执行；必须核对列名、过滤条件、空值与聚合口径'}
    @app.get('/api/datasets/{did}/proposals')
    def proposals(did:str):
        data.dataset(path,did)
        with data.connect(path) as db:
            return [{**dict(r),'proposal':json.loads(r['proposal'])} for r in db.execute('SELECT * FROM proposals WHERE dataset_id=? ORDER BY created_at DESC',(did,))]
    @app.post('/api/datasets/{did}/runs',status_code=201)
    def execute(did:str,request:Execution):
        data.dataset(path,did)
        if not request.reviewed:raise HTTPException(422,'请确认已核对查询口径')
        context={'note':request.note,'proposal_id':request.proposal_id,'origin':'manual','question':'','proposed_sql':None}
        if request.proposal_id:
            with data.connect(path) as db:
                row=db.execute("SELECT * FROM proposals WHERE id=? AND dataset_id=? AND state='proposed'",(request.proposal_id,did)).fetchone()
                if not row:raise HTTPException(404,'提议不属于当前数据集或未通过协议检查')
                context.update(origin='model-reviewed',question=row['question'],proposed_sql=json.loads(row['proposal'])['sql'])
        return data.execute(path,did,request.sql,context)
    @app.get('/api/datasets/{did}/runs')
    def runs(did:str):
        data.dataset(path,did)
        with data.connect(path) as db:
            return [{**dict(r),'result':json.loads(r['result'])} for r in db.execute('SELECT * FROM runs WHERE dataset_id=? ORDER BY created_at DESC',(did,))]
    def saved_run(rid):
        with data.connect(path) as db:
            row=db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            if not row:raise HTTPException(404,'查询记录不存在')
            return {**dict(row),'result':json.loads(row['result'])}
    @app.get('/api/runs/{rid}')
    def download(rid:str):
        return JSONResponse(saved_run(rid),headers={'Content-Disposition':f'attachment; filename="databrief-{rid}.json"'})
    @app.get('/api/runs/{rid}/bundle')
    def export_bundle(rid:str):
        record=saved_run(rid)
        return Response(delivery.bundle(record),media_type='application/zip',
                        headers={'Content-Disposition':f'attachment; filename="databrief-{record["id"]}.zip"'})
    root=Path(__file__).resolve().parents[1]
    @app.get('/')
    def index():return FileResponse(root/'web/index.html')
    @app.get('/sample.csv')
    def sample():return FileResponse(root/'samples/channels.csv',media_type='text/csv')
    app.mount('/static',StaticFiles(directory=root/'web'),name='static')
    return app


app=create_app()
