"""Offline MIME ingestion. Returned HTML fallback is text, never rendered HTML."""
from email import policy
from email.parser import BytesParser
from hashlib import sha256
from html.parser import HTMLParser

MAX_BYTES = 2_000_000
MAX_BODY = 100_000


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.hidden = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.hidden.append(tag)
        if not self.hidden and tag in ('p', 'div', 'br', 'li', 'tr', 'h1', 'h2'):
            self.output.append('\n')

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if not self.hidden and tag in ('p', 'div', 'li', 'tr'):
            self.output.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.output.append(data)


def parse(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('邮件必须非空且不超过 2 MB')
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError('邮件结构无法解析') from exc
    for field in ('Subject', 'From', 'Date', 'Message-ID'):
        if len(msg.get_all(field, [])) > 1:
            raise ValueError('重复邮件头：' + field)
    if not msg.keys():
        raise ValueError('缺少邮件头，请导入 .eml 文件')
    if any(len(str(value)) > 4000 for value in msg.values()):
        raise ValueError('邮件头过长')
    try:
        body_part = msg.get_body(preferencelist=('plain', 'html'))
    except RecursionError as exc:
        raise ValueError('邮件嵌套过深') from exc
    if body_part is None:
        raise ValueError('没有可读正文；不解析附件或转发邮件附件')
    try:
        body = body_part.get_content(errors='strict')
    except (LookupError, UnicodeError, ValueError) as exc:
        raise ValueError('正文字符编码无法可靠解码') from exc
    warnings = list(dict.fromkeys(type(d).__name__ for d in msg.defects + body_part.defects))
    if body_part.get_content_type() == 'text/html':
        parser = TextOnly()
        parser.feed(body)
        body = ''.join(parser.output)
        warnings.append('HTML 已转换为纯文本；链接目标、布局和隐藏样式不构成可信证据')
    body = body.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not body or len(body) > MAX_BODY:
        raise ValueError('正文必须非空且不超过 100000 字符；不会静默截断')
    if any(part.get_content_disposition() == 'attachment' for part in msg.walk()):
        warnings.append('附件仅随原始邮件留存，不提取附件中的任务')
    return {'sha256': sha256(raw).hexdigest(), 'subject': str(msg.get('Subject', '(无主题)')),
            'sender': str(msg.get('From', '')), 'recipients': ', '.join(str(v) for v in msg.get_all('To', [])),
            'message_id': str(msg.get('Message-ID', '')).strip(), 'date_header': str(msg.get('Date', '')),
            'in_reply_to': str(msg.get('In-Reply-To', '')), 'body': body,
            'body_sha256': sha256(body.encode('utf-8')).hexdigest(),
            'warnings': warnings, 'body_type': body_part.get_content_type()}
