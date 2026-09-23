"""Opt-in real local inference. Never part of offline CI; saves synthetic inputs/outputs."""
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from app.model import generate
from app.main import Copy
from app.checks import check, CHANNELS

BRIEF = {'name': '拾光任务本（合成产品）', 'audience': '职场新人', 'objective': '邀请体验任务整理功能',
         'tone': '清晰、克制、友好', 'facts': [
             {'id': 'F1', 'text': '支持手动添加任务和设置截止日期', 'source': '合成产品说明'},
             {'id': 'F2', 'text': '支持按周查看任务清单', 'source': '合成产品说明'}],
         'forbidden': ['行业第一', '保证', '最强'], 'required_phrase': '示例产品，仅供学习'}


async def main():
    if os.environ.get('CB_MODEL_BASE_URL') != 'http://127.0.0.1:8770/v1':
        raise SystemExit('This evaluation only calls the local loopback server on port 8770')
    results = []
    for channel in ('小红书', '邮件', '短信'):
        start = time.monotonic()
        item = {'channel': channel}
        try:
            raw, name = await generate(BRIEF, channel, CHANNELS[channel])
            copy = Copy.model_validate(raw)
            valid_ids = not (set(copy.fact_ids) - {'F1', 'F2'}) and len(copy.fact_ids) == len(set(copy.fact_ids))
            item.update(output=raw, model=name, schema_valid=True, fact_ids_valid=valid_ids,
                        checks=check(BRIEF, channel, copy.title, copy.body, copy.fact_ids))
        except Exception as e:
            item.update(schema_valid=False, error=type(e).__name__ + ': ' + str(e)[:400])
        item['latency_seconds'] = round(time.monotonic() - start, 3)
        results.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    report = {'evaluated_at': datetime.now(timezone.utc).isoformat(),
              'type': 'real local inference on synthetic brief', 'model_file': 'Qwen2.5-0.5B-Instruct Q4_K_M',
              'runtime': 'llama.cpp b11118 CPU, 4 threads, context 8192', 'brief': BRIEF,
              'results': results, 'note': 'Three development smoke cases, not benchmark accuracy. Rule checks do not establish semantic truth.'}
    Path('artifacts').mkdir(exist_ok=True)
    Path('artifacts/live-model.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
