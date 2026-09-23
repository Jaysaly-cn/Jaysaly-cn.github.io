"""Replay captured real model outputs without requiring a running model in CI."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import model

RESULTS=json.loads((Path(__file__).resolve().parents[1]/'artifacts/model-probes-20260923.json').read_text(encoding='utf-8'))['results']

@pytest.mark.parametrize('result',RESULTS,ids=lambda r:r['case']['id'])
def test_recorded_generation_boundary(tmp_path,monkeypatch,result):
    monkeypatch.setattr(model,'configured',lambda:True)
    async def propose(source):return result['raw']
    monkeypatch.setattr(model,'propose',propose)
    with TestClient(create_app(tmp_path/'replay.db')) as client:
        case=result['case']
        material=client.post('/api/materials',json={'title':case['title'],'body':case['body']}).json()
        response=client.post('/api/materials/'+material['id']+'/generate')
        expected=201 if case['id']=='negation' else 422
        assert response.status_code==expected
        cards=client.get('/api/cards').json()
        if expected==422:
            assert cards==[]
            assert client.get('/api/export').json()['events']==[]
        else:
            assert len(cards)==1 and cards[0]['state']=='draft'
        assert client.get('/api/due').json()==[]
        history=client.get('/api/generations').json()
        assert len(history)==1 and history[0]['raw']==result['raw']
        assert history[0]['status']==('saved' if expected==201 else 'failed')
        assert json.loads(history[0]['card_ids'])==[card['id'] for card in cards]
        if expected==422:assert json.loads(history[0]['issues'])[0]['kind']=='quote'
