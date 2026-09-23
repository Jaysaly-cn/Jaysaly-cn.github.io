"""Real development samples, not a blind benchmark. Stores all raw model outputs."""
import json
import time
from email.message import EmailMessage
from pathlib import Path
import httpx

CASES=[
    ('explicit','小林，请在2026年9月25日前提交项目方案。','应提取提交方案，保留负责人和原始日期短语'),
    ('negation','小林，预算表不用更新了。项目方案已经提交完成。','无新待办'),
    ('reschedule','小林，提交方案改到2026年9月28日前，原定周五的安排取消。','应保留改期后的任务，不把取消安排当第二项'),
    ('quoted','本次没有新的任务，请忽略下方旧邮件。\n> 小林，请在周五前提交旧版方案。','无新待办；旧引用不是当前要求'),
]


def main():
    results=[]
    with httpx.Client(base_url='http://127.0.0.1:8791',timeout=120) as client:
        for name,body,expected in CASES:
            mail=EmailMessage();mail['Subject']='合成模型开发验收：'+name
            mail['From']='sender@example.invalid';mail['To']='recipient@example.invalid'
            mail['Message-ID']=f'<model-{name}@example.invalid>';mail.set_content(body)
            response=client.post('/api/messages',content=mail.as_bytes());response.raise_for_status()
            mid=response.json()['id'];start=time.monotonic()
            response=client.post(f'/api/messages/{mid}/suggest')
            runs=client.get(f'/api/messages/{mid}/model-runs');runs.raise_for_status()
            results.append({'case':name,'body':body,'expected_human_criterion':expected,
                            'status':response.status_code,'seconds':round(time.monotonic()-start,2),
                            'response':response.json(),'raw_run':runs.json()[0] if runs.json() else None})
            Path('artifacts/live-model.json').write_text(json.dumps({'notice':'Four synthetic development cases, not accuracy evidence','results':results},ensure_ascii=False,indent=2),encoding='utf-8')
            print(name,response.status_code,round(time.monotonic()-start,2),flush=True)


if __name__=='__main__':main()
