"""Export a stored result, never rerun SQL or ask a model for a summary."""
import csv
import io
import json
import zipfile


def bundle(record):
    result=record['result']
    if result['state']!='succeeded':raise ValueError('失败查询没有可导出的结果表，请下载JSON记录查看错误')
    escaped=0
    def cell(value):
        nonlocal escaped
        if value is None:return '\\N'
        # Keep numeric negatives numeric; neutralize text formula prefixes in spreadsheet imports.
        if isinstance(value,str) and (value.startswith(('\t','\r','\n')) or value.lstrip().startswith(('=','+','-','@'))):
            escaped+=1
            return "'"+value
        return value
    csv_file=io.StringIO(newline='');writer=csv.writer(csv_file)
    writer.writerow([cell(c) for c in result['columns']])
    writer.writerows([cell(c) for c in row] for row in result['rows'])
    truncated=result['truncated'];name='result-truncated.csv' if truncated else 'result.csv'
    description=f'''# DataBrief 查询结果包

执行记录：{record['id']}
数据集：{record['dataset_id']}
执行时间：{record['created_at']}
原始数据 SHA-256：{result['source_sha256']}
导出行数：{len(result['rows'])}
结果截断：{'是，只包含已保存的前200行，不是完整结果。请调整SQL重新分析。' if truncated else '否'}

文件说明
- snapshot.json：原始执行快照，包含SQL、审核说明、来源哈希和带类型的结果。为核对依据。
- {name}：UTF-8 BOM CSV表格，严格保持快照中的列顺序（含同名列）与行顺序。
- query.sql：当次实际执行的SQL；不会再次执行。

CSV 导入注意
- NULL写作\\N，空字符串为空单元格。如果原文本身就是\\N，请以JSON区分；CSV不保留完整类型信息。
- 对公式前缀文本加单引号，本包共处理{escaped}个表头或单元格；数字负值保持数值。此处理改变CSV文本，原值仍在JSON。
- 表格软件仍可能自动转换日期、前导零编码或大整数；导入时将对应列设为文本，并核对JSON。
- 金额小数为浮点近似。此包不是自动生成的业务结论，SQL成功不代表分析口径正确。
- 不包含原始CSV、其他数据集或其他查询历史，只包含此条快照。将包发送给他人前请核对其中的结果与审核说明。
'''
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('snapshot.json',json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False))
        archive.writestr(name,csv_file.getvalue().encode('utf-8-sig'))
        archive.writestr('query.sql',record['sql'])
        archive.writestr('README.txt',description)
    return output.getvalue()
