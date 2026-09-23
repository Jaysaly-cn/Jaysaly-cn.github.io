"""Local-only review UI. Import trusted engine evidence with store.py."""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
import store
import jobs


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    version: int = Field(ge=0)
    decision: Literal['accepted', 'rejected', 'unclear']
    note: str = Field(min_length=5, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=80)


class Report(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=120)
    note: str = Field(min_length=5, max_length=2000)


class SuiteCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    suite: dict
    note: str = Field(min_length=5, max_length=2000)


class SuiteUpdate(SuiteCreate):
    version: int = Field(ge=1)


class JobCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    suite_id: str = Field(pattern='^[0-9a-f]{32}$')
    version: int = Field(ge=1, le=100)
    request_key: str = Field(pattern='^[0-9a-f-]{32,36}$')


def create_app(path=None):
    path = path or os.getenv('EVALDESK_DB', store.DB)
    def resolve():
        return Path(path() if callable(path) else path)
    @asynccontextmanager
    async def lifespan(app):
        if not callable(path):
            store.initialize(resolve())
            jobs.initialize(resolve())
        yield
    app = FastAPI(title='EvalDesk', version='0.1.0', lifespan=lifespan)

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        host = request.headers.get('host', '')
        if not request.scope.get('isolated_demo_session') and urlsplit('http://' + host).hostname not in ('127.0.0.1', 'localhost', '::1', 'testserver'):
            return JSONResponse({'detail': 'local host required'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if (origin and origin != str(request.base_url).rstrip('/')) or request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': 'same-origin writes required'}, status_code=403)
            limit = 2_000_000 if request.url.path.startswith('/api/suites') else 20_000
            if len(await request.body()) > limit:
                return JSONResponse({'detail': 'request too large'}, status_code=413)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(ValueError)
    @app.exception_handler(KeyError)
    @app.exception_handler(RuntimeError)
    async def invalid(request, exc):
        status = 404 if isinstance(exc, KeyError) else 409 if isinstance(exc, RuntimeError) else 422
        return JSONResponse({'detail': str(exc)}, status_code=status)

    @app.post('/api/jobs', status_code=202)
    def start_job(value: JobCreate):
        return jobs.launch(resolve(), **value.model_dump())

    @app.get('/api/jobs')
    def job_list():
        with store.connect(resolve()) as db:
            db.execute('BEGIN IMMEDIATE')
            jobs.refresh(db, resolve())
            return [jobs.public(row) for row in db.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100')]

    @app.get('/api/jobs/{job_id}/diagnostics')
    def job_diagnostics(job_id: str):
        return jobs.diagnostics(resolve(), job_id)

    @app.post('/api/jobs/{job_id}/recover')
    def recover_job(job_id: str):
        return jobs.recover(resolve(), job_id)

    @app.get('/api/suites')
    def suites():
        with store.connect(resolve()) as db:
            return [store.get_suite(db, row['id']) for row in db.execute('SELECT id FROM suites ORDER BY rowid DESC')]

    @app.get('/api/suite-sample')
    def sample():
        return json.loads((store.ROOT / 'samples/ticket-routing.json').read_text(encoding='utf-8'))

    @app.post('/api/suites', status_code=201)
    def create_suite(value: SuiteCreate):
        with store.connect(resolve()) as db:
            return store.save_suite(db, **value.model_dump())

    @app.put('/api/suites/{suite_id}')
    def update_suite(suite_id: str, value: SuiteUpdate):
        with store.connect(resolve()) as db:
            return store.save_suite(db, suite_id=suite_id, **value.model_dump())

    @app.get('/api/suites/{suite_id}/versions')
    def suite_history(suite_id: str):
        with store.connect(resolve()) as db:
            store.get_suite(db, suite_id)
            return [dict(r) for r in db.execute('SELECT version,sha256,note,created_at FROM suite_versions WHERE suite_id=? ORDER BY version DESC', (suite_id,))]

    @app.get('/api/suites/{suite_id}/versions/{version}')
    def suite_version(suite_id: str, version: int):
        with store.connect(resolve()) as db:
            return store.get_suite(db, suite_id, version)

    @app.get('/api/suites/{suite_id}/versions/{version}/download')
    def suite_download(suite_id: str, version: int):
        with store.connect(resolve()) as db:
            suite = store.get_suite(db, suite_id, version)
            return Response(store.encode(suite['suite']), media_type='application/json', headers={
                'Content-Disposition': f'attachment; filename="evaldesk-suite-v{version}.json"',
                'X-Content-SHA256': suite['sha256']})

    @app.get('/api/runs')
    def runs():
        with store.connect(resolve()) as db:
            result = []
            for row in db.execute('SELECT id,imported_at FROM runs ORDER BY imported_at DESC'):
                run = store.get_run(db, row['id'])
                result.append({'id': row['id'], 'name': run['suite']['name'], 'manifest': run['manifest'], 'summary': run['summary']})
            return result

    @app.get('/api/runs/{run_id}')
    def detail(run_id: str):
        with store.connect(resolve()) as db:
            return store.get_run(db, run_id)

    @app.post('/api/runs/{run_id}/cells/{cell_id}/reviews', status_code=201)
    def review(run_id: str, cell_id: str, value: Review):
        with store.connect(resolve()) as db:
            return store.review(db, run_id, cell_id, **value.model_dump())

    @app.post('/api/runs/{run_id}/reports', status_code=201)
    def report(run_id: str, value: Report):
        with store.connect(resolve()) as db:
            return store.report(db, run_id, **value.model_dump())

    @app.get('/api/runs/{run_id}/reports')
    def reports(run_id: str):
        with store.connect(resolve()) as db:
            store.get_run(db, run_id)
            return [{'id': row['id'], 'title': json.loads(row['snapshot'])['title'], 'created_at': row['created_at']}
                    for row in db.execute('SELECT * FROM reports WHERE run_id=? ORDER BY created_at DESC', (run_id,))]

    @app.get('/api/reports/{report_id}')
    def download(report_id: str):
        with store.connect(resolve()) as db:
            row = db.execute('SELECT snapshot FROM reports WHERE id=?', (report_id,)).fetchone()
            if not row:
                raise KeyError('report not found')
            return Response(row['snapshot'].encode(), media_type='application/json', headers={
                'Content-Disposition': 'attachment; filename="evaldesk-report.json"'})

    app.mount('/', StaticFiles(directory=store.ROOT / 'web', html=True), name='web')
    return app


app = create_app()
