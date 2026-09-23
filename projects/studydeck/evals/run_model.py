"""Explicit local-model developer evaluation; never approves cards or edits the workbench."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.model import propose, configured
from app.main import Proposals

async def run(output):
    if not configured(): raise SystemExit('Set SD_MODEL_BASE_URL and SD_MODEL to an existing local model.')
    cases=json.loads((ROOT/'evals/cases.json').read_text(encoding='utf-8'))
    report={'created_at':datetime.now(timezone.utc).isoformat(),'model':os.environ['SD_MODEL'],
            'scope':'Synthetic developer probes, not a blinded benchmark or learning effectiveness study.', 'results':[]}
    for case in cases:
        start=time.monotonic()
        result={'case':case,'raw':None,'schema_valid':False,'quotes_exact':False,
                'semantic_review':{'status':'pending','note':''}}
        try:
            result['raw']=await propose({'title':case['title'],'body':case['body']})
            parsed=Proposals.model_validate_json(result['raw'])
            result['schema_valid']=True
            result['cards']=[card.model_dump() for card in parsed.cards]
            result['quotes_exact']=all(card.quote in case['body'] for card in parsed.cards)
        except Exception as exc:
            result['error_type']=type(exc).__name__
        result['seconds']=round(time.monotonic()-start,2)
        report['results'].append(result)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(case['id'],result['schema_valid'],result['quotes_exact'],flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True,help='New JSON output file; existing files are not overwritten')
    args=parser.parse_args()
    if args.output.exists():parser.error('Choose a new output path to preserve earlier runs')
    asyncio.run(run(args.output))
