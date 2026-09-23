"""Deterministic evidence report. No model-generated analysis implied."""
import re
from collections import defaultdict


def build(project, sources, claims):
    source_map = {s['id']: s for s in sources}
    cells = defaultdict(list)
    excluded = []
    for claim in claims:
        source = source_map.get(claim['source_id'])
        if claim['state'] != 'approved' or not source or source['archived']:
            excluded.append(claim['id'])
            continue
        cells[(claim['entity'], claim['dimension'])].append(claim)
    matrix, gaps, conflicts = [], [], []
    for dimension in project['dimensions']:
        row = {'dimension': dimension, 'cells': []}
        for entity in project['entities']:
            group = cells[(entity, dimension)]
            normalized = {re.sub(r'\s+', '', c['statement']).lower() for c in group}
            status = 'gap' if not group else 'review_difference' if len(normalized) > 1 else 'evidenced'
            row['cells'].append({'entity': entity, 'status': status, 'claims': group})
            if status == 'gap':
                gaps.append({'entity': entity, 'dimension': dimension})
            if status == 'review_difference':
                conflicts.append({'entity': entity, 'dimension': dimension, 'claim_ids': [c['id'] for c in group]})
        matrix.append(row)
    return {'project': project, 'matrix': matrix, 'gaps': gaps, 'differences': conflicts,
            'excluded_claim_ids': excluded, 'sources': sources,
            'note': '仅展示人工确认且来源未归档的结论；不同表述是复核线索，不自动判定事实矛盾。'}


def escape(value):
    value = str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    value = re.sub(r'([\\`*_\[\]#!])', r'\\\1', value)
    return value.replace('|', '\\|').replace('\n', ' ')


def markdown(snapshot):
    p = snapshot['project']
    lines = [f'# {escape(p["title"])}', '', f'研究问题：{escape(p["question"])}', '',
             f'报告生成时间：{snapshot.get("generated_at", "未记录")}', '',
             '> 此报告由结构化证据整理生成。未确认与已归档来源结论不进入矩阵；缺失不代表产品不具备该能力。', '',
             '| 比较维度 | ' + ' | '.join(escape(e) for e in p['entities']) + ' |',
             '| --- | ' + ' | '.join('---' for _ in p['entities']) + ' |']
    refs = {}
    for row in snapshot['matrix']:
        values = []
        for cell in row['cells']:
            parts = []
            for claim in cell['claims']:
                refs.setdefault(claim['id'], (len(refs) + 1, claim))
                parts.append(f'{escape(claim["statement"])} [{refs[claim["id"]][0]}]')
            values.append(('需复核不同表述：' if cell['status'] == 'review_difference' else '') + ('；'.join(parts) or '待补证据'))
        lines.append('| ' + escape(row['dimension']) + ' | ' + ' | '.join(values) + ' |')
    lines += ['', '## 待补资料', '']
    lines += [f'- {escape(g["entity"])} / {escape(g["dimension"])}' for g in snapshot['gaps']] or ['暂无空白单元格；不代表研究已完整。']
    lines += ['', '## 引用与原文快照', '']
    sources = {s['id']: s for s in snapshot['sources']}
    for number, claim in refs.values():
        s = sources[claim['source_id']]
        lines += [f'### [{number}] {escape(s["title"])}', '',
                  f'- 对象：{escape(s["entity"])}；采集时间：{s["captured_at"]}；发布日期：{s["published_on"] or "未标注"}',
                  f'- 来源：{escape(s["url"]) or "用户粘贴材料（未由系统访问）"}',
                  f'- 内容 SHA-256：{s["sha256"]}', f'- 引用起始字符：{claim["quote_start"]}', '',
                  f'> {escape(claim["quote"])}', '', f'审核说明：{escape(claim["review_note"])}', '']
    return '\n'.join(lines) + '\n'
