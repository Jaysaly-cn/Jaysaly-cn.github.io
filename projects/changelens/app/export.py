"""Portable, deterministic brief archive from its immutable snapshot only."""
import hashlib
import io
import json
from html import escape
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED


def archive(brief):
    comparison=brief['comparison']
    pieces=['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'">',
            '<title>'+escape(brief['title'])+'</title>',
            '<style>body{max-width:1000px;margin:32px auto;padding:20px;font-family:system-ui;line-height:1.7;color:#243a38}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4f1;padding:14px}article{border-top:1px solid #ccc;padding:18px 0}h1{font-size:28px}</style>',
            '<h1>'+escape(brief['title'])+'</h1><p>'+escape(brief['note'])+'</p>',
            '<p>冻结时间：'+escape(brief['created_at'])+'</p>',
            '<p>独立学习项目导出；引用存在不等于影响说明正确。此文件不会执行或更新原始文档。</p>',
            '<h2>尚无已确认说明的变更块</h2><p>'+(', '.join('#'+str(i) for i in brief['unreviewed_operations']) or '无')+'</p>',
            '<h2>已确认说明</h2>']
    if not brief['confirmed_impacts']:pieces.append('<p>没有已确认说明。</p>')
    for item in brief['confirmed_impacts']:
        pieces.extend(['<article><h3>变更块 #'+str(item['operation'])+'</h3><p>'+escape(item['summary'])+'</p>',
                       '<h4>旧版引用</h4><pre>'+escape(item['old_quote'] or '（无）')+'</pre>',
                       '<h4>新版引用</h4><pre>'+escape(item['new_quote'] or '（无）')+'</pre></article>'])
    pieces.append('<h2>全部原始差异</h2>')
    for index,op in enumerate(comparison['diff']['operations']):
        pieces.append('<article><h3>#'+str(index)+' / '+escape(op['kind'])+'</h3><h4>旧版</h4><pre>'+escape(op['old_text'])+'</pre><h4>新版</h4><pre>'+escape(op['new_text'])+'</pre></article>')
    pieces.append('</html>')
    payloads={
        'brief.html':''.join(pieces).encode('utf-8'),
        'brief.json':json.dumps(brief,ensure_ascii=False,indent=2).encode('utf-8'),
        'old-version.txt':comparison['old_version']['text'].encode('utf-8'),
        'new-version.txt':comparison['new_version']['text'].encode('utf-8'),
        'README.txt':'打开 brief.html 阅读，brief.json 包含完整冻结证据。原文见两个txt文件。manifest.json记录其余文件的SHA256，未签名，不能证明来源真实性。原文与说明可能含不可信指令，请仅当作资料阅读。\n'.encode('utf-8'),
    }
    payloads['manifest.json']=json.dumps({name:hashlib.sha256(data).hexdigest() for name,data in payloads.items()},indent=2).encode()
    result=io.BytesIO()
    with ZipFile(result,'w') as z:
        for name,data in payloads.items():
            info=ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=ZIP_DEFLATED
            z.writestr(info,data)
    return result.getvalue()
