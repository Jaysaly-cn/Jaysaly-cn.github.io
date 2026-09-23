import json
import socket
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import collect, model


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k in ('EVIDENCEBRIEF_ACCESS_TOKEN', 'EB_MODEL', 'EB_MODEL_BASE_URL', 'EB_MODEL_API_KEY'):
        monkeypatch.delenv(k, raising=False)
    with TestClient(create_app(str(tmp_path / 'research.db'))) as c:
        yield c


def project(c, **kwargs):
    response = c.post('/api/projects', json={'title': '知识库选型', 'question': '比较小团队知识库方案',
                                             'entities': ['Alpha', 'Beta'], 'dimensions': ['价格', '导入格式'], **kwargs})
    assert response.status_code == 201, response.text
    return response.json()['id']


def source(c, pid, **kwargs):
    response = c.post(f'/api/projects/{pid}/sources', json={'entity': 'Alpha', 'title': '合成定价页',
        'content': 'Alpha 团队版每月 19 元。支持导入 Markdown 文档。所有内容均为合成示例。', **kwargs})
    assert response.status_code == 201, response.text
    return response.json()


def claim(c, pid, sid, **kwargs):
    return c.post(f'/api/projects/{pid}/claims', json={'source_id': sid, 'dimension': '价格',
        'statement': '团队版每月 19 元', 'quote': 'Alpha 团队版每月 19 元。', **kwargs})


def approve(c, pid, item):
    return c.patch(f'/api/projects/{pid}/claims/{item["id"]}', json={'version': item['version'],
                      'state': 'approved', 'note': '已核对原文与适用套餐'} )


def test_full_workflow_and_immutable_report(client):
    pid = project(client)
    s = source(client, pid)
    assert source(client, pid)['id'] == s['id']
    draft = claim(client, pid, s['id']).json()
    assert draft['state'] == 'draft'
    assert len(client.get('/api/projects/' + pid).json()['gaps']) == 4
    assert approve(client, pid, draft).status_code == 200
    assert approve(client, pid, draft).status_code == 409
    live = client.get('/api/projects/' + pid).json()
    assert len(live['gaps']) == 3
    exported = client.post(f'/api/projects/{pid}/reports').json()
    assert '团队版每月 19 元' in exported['markdown'] and '[1]' in exported['markdown']
    assert s['sha256'] in exported['markdown']
    assert client.patch(f'/api/projects/{pid}/sources/{s["id"]}', json={'archived': True}).status_code == 200
    assert len(client.get('/api/projects/' + pid).json()['gaps']) == 4
    past = client.get(f'/api/projects/{pid}/reports/{exported["id"]}').json()
    assert past['markdown'] == exported['markdown']
    assert past['snapshot']['sources'][0]['archived'] == 0
    latest = client.post(f'/api/projects/{pid}/reports').json()
    assert len(latest['snapshot']['gaps']) == 4
    assert '团队版每月 19 元' not in latest['markdown']
    assert client.get(f'/api/projects/{pid}/reports/{exported["id"]}?format=markdown').headers['content-disposition'].endswith('.md"')


def test_cross_project_links_quotes_and_dimensions(client):
    p1, p2 = project(client), project(client)
    s = source(client, p1)
    assert claim(client, p2, s['id']).status_code == 404
    assert claim(client, p1, s['id'], quote='Alpha 提供完全免费的团队服务').status_code == 422
    assert claim(client, p1, s['id'], dimension='不存在的维度').status_code == 422
    assert client.post(f'/api/projects/{p1}/sources', json={'entity': 'Unknown', 'title': '资料', 'content': '不是这个项目研究对象的资料'}).status_code == 422
    report = client.post(f'/api/projects/{p1}/reports').json()
    assert client.get(f'/api/projects/{p2}/reports/{report["id"]}').status_code == 404


def test_differences_and_retirement(client):
    pid = project(client)
    s = source(client, pid)
    first = claim(client, pid, s['id']).json()
    approve(client, pid, first)
    second = claim(client, pid, s['id'], statement='基础团队方案月付 19 元').json()
    approve(client, pid, second)
    data = client.get('/api/projects/' + pid).json()
    assert len(data['differences']) == 1
    assert data['matrix'][0]['cells'][0]['status'] == 'review_difference'
    assert client.patch(f'/api/projects/{pid}/claims/{second["id"]}', json={'version': 2, 'state': 'rejected', 'note': '表述重复，保留另一条'}).status_code == 200
    assert client.get('/api/projects/' + pid).json()['differences'] == []


def test_model_atomic_grounding(client, monkeypatch):
    pid = project(client)
    s = source(client, pid)
    endpoint = f'/api/projects/{pid}/sources/{s["id"]}/suggest'
    assert client.post(endpoint).status_code == 409
    monkeypatch.setenv('EB_MODEL', 'test:free')
    monkeypatch.setenv('EB_MODEL_BASE_URL', 'https://openrouter.ai/api/v1')
    async def invalid(*args):
        return [{'dimension': '价格', 'statement': '团队版 19 元', 'quote': 'Alpha 团队版每月 19 元。'},
                {'dimension': '价格', 'statement': '虚构价格', 'quote': '原文不存在的片段'}]
    monkeypatch.setattr(model, 'suggest', invalid)
    assert client.post(endpoint).status_code == 502
    assert client.get('/api/projects/' + pid).json()['claims'] == []
    async def valid(*args):
        return [{'dimension': '价格', 'statement': '团队版 19 元', 'quote': 'Alpha 团队版每月 19 元。'}]
    monkeypatch.setattr(model, 'suggest', valid)
    generated = client.post(endpoint).json()['claims'][0]
    assert generated['state'] == 'draft' and generated['origin'] == 'model'
    assert len(client.get('/api/projects/' + pid).json()['gaps']) == 4


def test_security_and_validation(client, monkeypatch):
    assert client.get('/api/projects', headers={'Host': 'evil.example'}).status_code == 403
    assert client.post('/api/projects', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/projects', content='x' * 400001).status_code == 413
    assert client.post('/api/projects', json={'title': '重复', 'question': '比较方案', 'entities': ['A', 'a'], 'dimensions': ['价格']}).status_code == 422
    monkeypatch.setenv('EVIDENCEBRIEF_ACCESS_TOKEN', 'test-only')
    assert client.get('/api/projects').status_code == 401
    assert client.get('/api/projects', headers={'Authorization': 'Bearer test-only'}).status_code == 200


def test_restart_and_markdown_escaping(tmp_path):
    path = str(tmp_path / 'persistent.db')
    with TestClient(create_app(path)) as c:
        pid = project(c, title='<script>bad</script> [link](javascript:test)')
    with TestClient(create_app(path)) as c:
        content = c.post(f'/api/projects/{pid}/reports').json()['markdown']
        assert '<script>' not in content and '[link]' not in content
        assert len(c.get('/api/projects').json()) == 1


@pytest.mark.parametrize('url', ['http://example.com', 'https://u:p@example.com', 'https://example.com:8443',
                                'https://127.0.0.1', 'https://[::1]', 'https://169.254.169.254', 'https://10.1.2.3'])
def test_unsafe_urls_rejected(url):
    def resolve(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (host if host in ('127.0.0.1', '::1', '169.254.169.254', '10.1.2.3') else '93.184.216.34', 443))]
    with patch.object(collect.socket, 'getaddrinfo', side_effect=resolve):
        with pytest.raises(collect.CollectionError):
            collect.validate_url(url)


def test_html_extraction():
    title, content = collect.extract('<title>Product &amp; Docs</title><script>steal()</script><p>Alpha <b>19</b> 元</p><p>导入 Markdown。</p>', 'text/html')
    assert title == 'Product & Docs'
    assert content == 'Alpha 19 元\n导入 Markdown。'
    assert 'steal' not in content
    assert collect.extract('# A title\nSome text', 'text/plain')[0] == 'A title'


def test_redirect_revalidates_destination(monkeypatch):
    monkeypatch.setattr(collect.socket, 'getaddrinfo', lambda host, *a, **k: [(2, 1, 6, '', ('127.0.0.1' if host=='localhost' else '93.184.216.34', 443))])
    connected = []
    class Fake:
        def __init__(self, host, address, timeout):
            connected.append((host, address))
        def request(self, *a, **kw): pass
        def getresponse(self):
            class Redirect:
                status = 302
                def getheader(self, name, default=None): return 'https://localhost/private'
            return Redirect()
        def close(self): pass
    monkeypatch.setattr(collect, 'PinnedHTTPS', Fake)
    with pytest.raises(collect.CollectionError):
        collect.collect('https://example.com')
    assert connected == [('example.com', '93.184.216.34')]


def test_fetch_persists_verifiable_snapshot(client, monkeypatch):
    pid = project(client)
    monkeypatch.setattr(collect, 'collect', lambda url: {'title':'公开页面','content':'公开页面合成事实：团队版每月19元。','url':url,'raw_sha256':'a'*64})
    r = client.post(f'/api/projects/{pid}/fetch', json={'entity':'Alpha','url':'https://example.com'}).json()
    assert r['method'] == 'https' and len(r['sha256']) == 64 and r['raw_sha256'] == 'a'*64


def test_mixed_public_private_dns_is_rejected(monkeypatch):
    monkeypatch.setattr(collect.socket, 'getaddrinfo', lambda *a, **k: [
        (2,1,6,'',('93.184.216.34',443)), (2,1,6,'',('192.168.1.2',443))])
    with pytest.raises(collect.CollectionError):
        collect.validate_url('https://mixed.example')


def test_tcp_destination_is_pinned_and_tls_uses_hostname(monkeypatch):
    calls = []
    class Raw:
        def close(self): pass
    raw, tls = Raw(), Raw()
    monkeypatch.setattr(collect.socket, 'create_connection', lambda address, timeout: calls.append(address) or raw)
    connection = collect.PinnedHTTPS('example.com', '93.184.216.34', 10)
    class Context:
        def wrap_socket(self, sock, server_hostname):
            assert sock is raw and server_hostname == 'example.com'
            return tls
    connection._context = Context()
    connection.connect()
    assert calls == [('93.184.216.34', 443)] and connection.sock is tls


def test_paid_model_cannot_be_called(monkeypatch):
    import asyncio
    monkeypatch.setenv('EB_MODEL_BASE_URL', 'https://openrouter.ai/api/v1')
    monkeypatch.setenv('EB_MODEL', 'paid-model')
    monkeypatch.setenv('EB_MODEL_API_KEY', 'mock')
    with pytest.raises(ValueError):
        asyncio.run(model.suggest({'entity':'A','content':'test'}, ['价格']))


def test_model_provider_contract(monkeypatch):
    import asyncio
    import httpx
    monkeypatch.setenv('EB_MODEL_BASE_URL', 'https://openrouter.ai/api/v1')
    monkeypatch.setenv('EB_MODEL', 'test:free')
    monkeypatch.setenv('EB_MODEL_API_KEY', 'mock')
    original = httpx.AsyncClient
    def handler(request):
        body = json.loads(request.content)
        assert body['model'] == 'test:free'
        assert len(json.loads(body['messages'][1]['content'])['text']) == 20000
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"claims": []}'}}]})
    monkeypatch.setattr(model.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    assert asyncio.run(model.suggest({'entity':'A','content':'x'*30000}, ['价格'])) == []


def test_local_model_excerpt_is_bounded(monkeypatch):
    import asyncio
    import httpx
    monkeypatch.setenv('EB_MODEL_BASE_URL', 'http://127.0.0.1:8771/v1')
    monkeypatch.setenv('EB_MODEL', 'local')
    original = httpx.AsyncClient
    def handler(request):
        text = json.loads(json.loads(request.content)['messages'][1]['content'])['text']
        assert len(text) == 4000
        assert '正文尾部' not in text
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"claims": []}'}}]})
    monkeypatch.setattr(model.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    assert asyncio.run(model.suggest({'entity':'A','content':'正'*5000+'正文尾部'}, ['价格'])) == []
