"""Repeatable synthetic acceptance against the isolated demo, never a private workspace."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import httpx


def verify(first, second, use_model=False):
    checks = []

    def expect(response, status):
        if response.status_code != status:
            raise AssertionError(f'{response.request.method} {response.request.url.path}: expected {status}, got {response.status_code}')
        return response

    status = expect(first.get('/demo/status'), 200).json()
    assert status.get('service') == 'EvidenceBrief temporary demo' and status.get('temporary') is True
    for client in (first, second):
        expect(client.get('/'), 200)
    pid = expect(first.get('/api/projects'), 200).json()[0]['id']
    other = expect(second.get('/api/projects'), 200).json()[0]['id']
    assert pid != other
    expect(second.get(f'/api/projects/{pid}'), 404)
    expect(first.get(f'/api/projects/{other}'), 404)
    checks.append('separate visitors cannot read each other projects')
    base = f'/api/projects/{pid}'
    source = expect(first.get(base), 200).json()['sources'][0]
    expect(first.post(base+'/fetch', json={'url':'https://example.com','entity':'Alpha'}), 403)
    expect(first.post(base+'/reports', headers={'Origin':'https://cross-site.invalid'}), 403)
    checks.append('external fetch and cross-origin write blocked')

    model_result = {'attempted': use_model}
    if use_model:
        response = first.post(base+f'/sources/{source["id"]}/suggest')
        model_result['status'] = response.status_code
        if response.status_code == 201:
            candidates = response.json()['claims']
            assert all(c['state'] == 'draft' for c in candidates)
            model_result['draft_count'] = len(candidates)
        else:
            model_result['error'] = response.json().get('detail')
        # A model response is recorded separately; it is never automatically approved.

    draft_report = expect(first.post(base+'/reports'), 201).json()
    assert len(draft_report['snapshot']['gaps']) == 4
    checks.append('unapproved model candidates do not fill evidence gaps')
    item = expect(first.post(base+'/claims', json={
        'source_id': source['id'], 'dimension':'价格',
        'statement':'合成验收：Alpha 团队版月付价格为 19 元',
        'quote':'Alpha 团队版每月 19 元'}), 201).json()
    expect(first.patch(base+'/claims/'+item['id'], json={
        'version':item['version'], 'state':'approved',
        'note':'脚本核对固定合成资料；不是对模型输出自动审核'}), 200)
    frozen = expect(first.post(base+'/reports'), 201).json()
    assert len(frozen['snapshot']['gaps']) == 3 and source['sha256'] in frozen['markdown']
    expect(second.get(base+'/reports/'+frozen['id']), 404)
    download = expect(first.get(base+'/reports/'+frozen['id']+'?format=markdown'), 200)
    assert download.text == frozen['markdown'] and '.md' in download.headers['content-disposition']
    checks.append('approved synthetic evidence exported with source hash; report isolated')
    expect(first.patch(base+'/sources/'+source['id'], json={'archived':True}), 200)
    assert len(expect(first.get(base), 200).json()['gaps']) == 4
    assert expect(first.get(base+'/reports/'+frozen['id']), 200).json()['markdown'] == frozen['markdown']
    checks.append('source archival changes current matrix, preserves frozen report')
    return {'checked_at':datetime.now(timezone.utc).isoformat(), 'workflow_passed':True,
            'checks':checks, 'model':model_result,
            'limits':'Synthetic acceptance only; no accuracy or uptime claim. Sessions expire normally.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--model', action='store_true', help='Consumes one real demo model call')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, timeout=120) as first, httpx.Client(base_url=args.url, timeout=120) as second:
        result = verify(first, second, args.model)
    result['url'] = args.url
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if args.model and result['model'].get('status') != 201:
        raise SystemExit('Workflow passed, but real model generation failed; inspect the saved result.')


if __name__ == '__main__':
    main()
