"""Explicit synthetic-data smoke against an already configured public demo URL."""
import json
import sys
import time
from pathlib import Path
import httpx


def main(base):
    report = {'url': base, 'model': 'local Qwen2.5 1.5B', 'synthetic_only': True}
    with httpx.Client(base_url=base, timeout=110) as a, httpx.Client(base_url=base, timeout=30) as b:
        for client in (a, b):
            client.get('/').raise_for_status()
        mid = a.get('/api/meetings').json()[0]['id']
        other = b.get('/api/meetings').json()[0]['id']
        start = time.monotonic()
        r = a.post(f'/api/meetings/{mid}/extract', json={})
        report['extraction'] = {'status': r.status_code, 'elapsed_ms': round((time.monotonic()-start)*1000), 'result': r.json()}
        r.raise_for_status()
        result = r.json()
        repeated = a.post(f'/api/meetings/{mid}/extract', json={}).json()
        assert repeated['reused']
        report['reused'] = True
        # Explicitly reviewed synthetic commitment. Never approve every model candidate.
        action = a.post(f'/api/meetings/{mid}/candidates', json={
            'title': '完成接口文档', 'quote': '小林：我明天完成接口文档。', 'owner': '小林', 'due_phrase': '明天'}).json()
        review = a.post('/api/actions/'+action['id']+'/review', json={
            'version': action['version'], 'decision': 'confirm', 'title': action['title'],
            'owner': '小林', 'due_date': '2026-09-24', 'note': '人工逐字核对合成会议中的明确承诺'})
        review.raise_for_status()
        assert b.get('/api/meetings/'+mid).status_code == 404
        assert b.post('/api/actions/'+action['id']+'/state', json={
            'version': 2, 'state': 'in_progress', 'note': 'isolation probe'}).status_code == 404
        assert mid != other and b.get('/api/board').json() == []
        report['isolation'] = {'different_meeting_ids': True, 'cross_read': 404, 'cross_write': 404, 'other_board_empty': True}
        report['exports'] = {}
        for kind in ('json', 'csv', 'ics'):
            response = a.get('/api/export/'+kind)
            response.raise_for_status()
            second = b.get('/api/export/'+kind)
            assert action['id'] not in second.text
            if kind == 'json': assert len(response.json()['actions']) == 1 and second.json()['actions'] == []
            if kind == 'ics': assert 'BEGIN:VEVENT' in response.text and 'BEGIN:VEVENT' not in second.text
            report['exports'][kind] = {'status': response.status_code, 'bytes': len(response.content), 'other_visitor_empty': True}
        report['quota'] = a.get('/demo/status').json()
        report['run_count'] = len(a.get('/api/meetings/'+mid).json()['runs'])
        assert report['run_count'] == 1
    Path('artifacts/public-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1])
