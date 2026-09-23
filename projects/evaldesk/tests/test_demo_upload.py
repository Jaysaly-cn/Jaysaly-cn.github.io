"""Regression: a request owns its workspace from body receipt through completion."""
import asyncio
from contextlib import closing
import sqlite3
import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from demo import create_demo_app, COOKIE


@pytest.mark.parametrize('oversize',[False,True],ids=['accepted','too-large'])
def test_expiry_during_upload_does_not_remove_workspace(tmp_path,oversize):
    clock=[0]
    app=create_demo_app(tmp_path/'sandbox',clock=lambda:clock[0])
    @app.post('/api/upload-probe')
    async def probe(request: Request):
        payload=await request.body()
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('SELECT count(*) FROM sqlite_master').fetchone()[0]>0
        return {'bytes':len(payload)}
    app.router.routes.insert(0, app.router.routes.pop())  # before a root static-files mount
    with TestClient(app,base_url='https://testserver') as c:
        assert c.get('/').status_code==200
        cookie=c.cookies.get(COOKIE)
        session=next(iter(app.state.demo_sessions.values()))
        path=session['path']
        async def run():
            started=asyncio.Event();release=asyncio.Event()
            async def chunks():
                yield b'a'
                started.set()
                await release.wait()
                yield b'b'*(40000 if oversize else 2)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://testserver',
                                         headers={'Cookie':COOKIE+'='+cookie}) as client:
                pending=asyncio.create_task(client.post('/api/upload-probe',content=chunks()))
                try:
                    await asyncio.wait_for(started.wait(),3)
                    clock[0]=1801
                    assert (await client.get('/api/upload-probe')).status_code==401
                    assert path.exists(), 'active upload lost its database before completing'
                finally:
                    release.set()
                    response=await asyncio.wait_for(pending,3)
                assert response.status_code==(413 if oversize else 200)
                assert session['active']==0
                assert (await client.get('/api/upload-probe')).status_code==401
                assert not path.exists()
        asyncio.run(run())


def test_write_quota_exit_releases_workspace_reference(tmp_path):
    clock=[0]
    app=create_demo_app(tmp_path/'sandbox',clock=lambda:clock[0])
    with TestClient(app,base_url='https://testserver') as c:
        assert c.get('/').status_code==200
        session=next(iter(app.state.demo_sessions.values()))
        path=session['path'];session['writes']=60
        assert c.post('/api/upload-probe',content=b'x').status_code==429
        assert session['active']==0
        clock[0]=1801
        assert c.get('/api/upload-probe').status_code==401
        assert not path.exists()
