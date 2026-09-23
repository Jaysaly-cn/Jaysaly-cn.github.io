"""Compile an explicit single-table analysis choice; never execute it."""
from .data import number


def preview(source, spec):
    columns={c['key']:c for c in source['columns']}
    def column(key):
        if key not in columns:raise ValueError('所选列不属于当前数据集')
        return columns[key]
    metric=spec['metric'];aggregate=spec['aggregate'];group=spec['group']
    if aggregate not in ('rows','count','distinct','sum','avg','min','max'):
        raise ValueError('不支持的聚合方式')
    if spec['nulls'] not in ('exclude','zero') or spec['order'] not in ('asc','desc'):
        raise ValueError('不支持的空值或排序方式')
    if group:column(group)
    labels={'rows':'行数','count':'非空数','distinct':'非空去重数','sum':'合计','avg':'均值','min':'最小值','max':'最大值'}
    if aggregate=='rows':
        if metric or spec['nulls']!='exclude':raise ValueError('行数不使用指标列或补零')
        expression='COUNT(*)'
    else:
        selected=column(metric)
        numeric=aggregate in ('sum','avg','min','max')
        if numeric and selected['type'] not in ('INTEGER','REAL'):raise ValueError('此聚合需要数值列')
        if spec['nulls']=='zero' and not numeric:raise ValueError('计数不支持补零，请明确选择行数或非空数')
        field=f'"{metric}"'
        if spec['nulls']=='zero':field=f'COALESCE({field}, 0)'
        expression=f'COUNT(DISTINCT {field})' if aggregate=='distinct' else f'{aggregate.upper()}({field})'
    clauses=[];condition=spec['filter']
    if condition:
        selected=column(condition['column']);field=f'"{selected["key"]}"';op=condition['operator'];value=condition['value']
        if op in ('missing','present'):
            if value:raise ValueError('空值条件不填写比较值')
            clauses.append(field+(' IS NULL' if op=='missing' else ' IS NOT NULL'))
        else:
            operators={'eq':'=','ne':'<>','gte':'>=','lte':'<='}
            if op not in operators or not value.strip():raise ValueError('请选择有效条件并填写比较值；空白请使用空值条件')
            if selected['type'] in ('INTEGER','REAL'):
                parsed=number(value.strip())
                if parsed is None:raise ValueError('数值列的比较值必须为有效普通数字')
                literal=str(parsed)
            else:literal="'"+value.strip().replace("'","''")+"'"
            clauses.append(f'{field} {operators[op]} {literal}')
    sql='SELECT '+(f'"{group}" AS "分组", ' if group else '')+f'{expression} AS "{labels[aggregate]}" FROM data'
    if clauses:sql+=' WHERE '+' AND '.join(clauses)
    if group:sql+=f' GROUP BY "{group}"'
    sql+=f' ORDER BY "{labels[aggregate]}" {spec["order"].upper()}'
    if group:sql+=f', "{group}" ASC'
    return {'sql':sql,'explanation':('按所选列分组；NULL 分组保留。' if group else '汇总筛选后的所有行。')+
            ('指标空值按 0 参与计算。' if spec['nulls']=='zero' else 'COUNT(*)计算行数；其他聚合忽略指标NULL，非空去重数也不计NULL。')+
            '按指标排序，同值按分组升序；非空比较不会包含NULL。文本范围比较按文本顺序，不自动解析日期。',
            'notice':'仅生成，尚未执行。请核对筛选与空值是否符合业务定义；没有匹配行时SUM/AVG/MIN/MAX返回NULL。'}
