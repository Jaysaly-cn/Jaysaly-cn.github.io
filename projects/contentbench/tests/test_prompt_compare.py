import asyncio
from unittest.mock import AsyncMock, MagicMock
import httpx
from app import model
from app.checks import CHANNELS
from evals.prompt_compare import cases, messages


def test_frozen_baseline_matches_current_model_requests(monkeypatch):
    monkeypatch.setenv('CB_MODEL_BASE_URL', 'http://127.0.0.1:8770/v1')
    monkeypatch.setenv('CB_MODEL', 'portfolio-qwen')
    response = httpx.Response(200, request=httpx.Request('POST', 'http://localhost'), json={
        'choices': [{'message': {'content': '{"title":"test","body":"test","fact_ids":[]}'}}]})
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(model.httpx, 'AsyncClient', lambda **kwargs: context)
    for case in cases():
        asyncio.run(model.generate(case['brief'], case['channel'], CHANNELS[case['channel']]))
        sent = client.post.call_args.kwargs['json']
        assert sent['messages'] == messages(case['brief'], case['channel'], 'baseline-v1')
        assert sent['temperature'] == .2 and sent['max_tokens'] == 650
