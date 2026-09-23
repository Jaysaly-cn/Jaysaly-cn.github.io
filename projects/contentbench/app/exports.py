"""Readable delivery from immutable snapshots; user text stays literal code."""
import re


def literal(text):
    # A longer fence prevents embedded Markdown/HTML from escaping the literal block.
    fence = '`' * max(3, 1 + max((len(s) for s in re.findall(r'`+', text)), default=0))
    return fence + 'text\n' + text + '\n' + fence + '\n'


def markdown(snapshot):
    brief = snapshot['brief']
    parts = ['# ContentBench · 冻结交付包\n',
             '这是已批准版本的快照，不代表已向任何渠道发布。关联事实不是逐句自动溯源；人工审核不能替代实际宣传适用性核验。\n',
             '## 快照标识\n', literal(snapshot['id']), literal(snapshot['created_at']),
             '## 活动要求\n']
    for label, key in [('活动', 'name'), ('受众', 'audience'), ('目标', 'objective'), ('语气', 'tone'), ('必带说明', 'required_phrase')]:
        parts += ['### '+label+'\n', literal(brief[key])]
    parts += ['### 禁用词\n', literal('\n'.join(brief['forbidden'])), '## 已批准稿件\n']
    for index, copy in enumerate(snapshot['copies'], 1):
        parts += [f'### 稿件 {index}\n']
        for label, value in [('渠道', copy['channel']), ('版本与来源',
                f"稿件 {copy['draft_id']} / 版本 {copy['id']} / v{copy['number']}\n{copy['origin']} / {copy['model']}"),
                ('标题', copy['title']), ('正文', copy['body']), ('关联事实', '\n'.join(copy['fact_ids'])),
                ('审核说明', copy['review_note'])]:
            parts += ['#### '+label+'\n', literal(value)]
    parts += ['## 品牌事实与出处\n']
    for fact in brief['facts']:
        parts += ['### '+fact['id']+'\n', literal(fact['text']), '出处：\n', literal(fact['source'])]
    return '\n'.join(parts)
