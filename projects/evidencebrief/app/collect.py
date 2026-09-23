"""Bounded public HTTPS collection with DNS pinning on every redirect."""
import hashlib
import http.client
import ipaddress
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

MAX_BYTES = 1_000_000


class CollectionError(ValueError):
    pass


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.title = False
        self.title_parts, self.parts = [], []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'template'):
            self.hidden += 1
        if tag == 'title':
            self.title = True
        if tag in ('p', 'div', 'li', 'br', 'h1', 'h2', 'h3', 'tr', 'section'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'template') and self.hidden:
            self.hidden -= 1
        if tag == 'title':
            self.title = False
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'tr', 'section'):
            self.parts.append('\n')

    def handle_data(self, value):
        if self.hidden:
            return
        if self.title:
            self.title_parts.append(value)
        else:
            self.parts.append(value)


def extract(raw: str, content_type: str) -> tuple[str, str]:
    if 'html' in content_type:
        parser = TextExtractor()
        parser.feed(raw)
        title, content = ''.join(parser.title_parts), ''.join(parser.parts)
    else:
        title, content = '', raw
        heading = re.search(r'^#\s+(.+)$', raw, re.MULTILINE)
        if heading:
            title = heading.group(1)
    lines = [re.sub(r'[\t \r]+', ' ', line).strip() for line in content.split('\n')]
    return title.strip()[:200], '\n'.join(line for line in lines if line)


def validate_url(url: str):
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise CollectionError('仅支持不带凭据的公开 HTTPS 地址与默认端口')
        hostname = parsed.hostname.encode('idna').decode('ascii')
        if '%' in hostname or any(ord(c) < 33 for c in url) or '\\' in url:
            raise CollectionError('地址包含不支持的字符')
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)})
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise CollectionError('不允许采集本机、内网或保留地址')
        normalized = urlunsplit(('https', hostname,
                                 quote(parsed.path or '/', safe="/%:@!$&'()*+,;=-._~"),
                                 quote(parsed.query, safe="%=&?/:@!$'()*+,;~-._"), ''))
        return hostname, addresses, normalized
    except (UnicodeError, OSError, ValueError) as exc:
        if isinstance(exc, CollectionError):
            raise
        raise CollectionError('无法解析公开来源地址') from exc


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, address, timeout):
        super().__init__(hostname, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # The TLS hostname is original; the TCP destination cannot re-resolve to a private IP.
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def collect(url: str) -> dict:
    started = time.monotonic()
    original = url
    for hop in range(4):
        hostname, addresses, url = validate_url(url)
        remaining = 25 - (time.monotonic() - started)
        if remaining <= 0:
            raise CollectionError('来源采集超时，请改用粘贴原文')
        parsed = urlsplit(url)
        connection = PinnedHTTPS(hostname, addresses[0], min(10, remaining))
        try:
            path = parsed.path + ('?' + parsed.query if parsed.query else '')
            connection.request('GET', path, headers={'User-Agent': 'EvidenceBrief/0.1 (user-initiated research)',
                                                    'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location or hop == 3:
                    raise CollectionError('来源重定向过多或缺少目标')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise CollectionError(f'来源返回 HTTP {response.status}，可改用粘贴原文')
            content_type = response.getheader('Content-Type', '').lower()
            if content_type.split(';')[0].strip() not in ('text/html', 'text/plain', 'application/xhtml+xml'):
                raise CollectionError('仅支持 HTML 或纯文本来源，暂不支持 PDF')
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise CollectionError('来源未提供未压缩正文，请改用粘贴原文')
            body = bytearray()
            while True:
                remaining = 25 - (time.monotonic() - started)
                if remaining <= 0:
                    raise CollectionError('来源采集超时')
                if connection.sock:
                    connection.sock.settimeout(min(10, remaining))
                chunk = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise CollectionError('来源超过 1MB，请选择具体页面或粘贴节选')
                if not chunk:
                    break
            charset = re.search(r'charset=["\s]*([\w-]+)', content_type)
            encoding = charset.group(1) if charset else 'utf-8'
            try:
                raw = body.decode(encoding, errors='replace')
            except LookupError:
                raise CollectionError('来源字符编码不受支持')
            title, content = extract(raw, content_type)
            if not content or len(content) > 100000:
                raise CollectionError('可提取正文为空或超过 10 万字符，请粘贴节选')
            return {'title': title or hostname, 'content': content, 'url': url,
                    'requested_url': original, 'raw_sha256': hashlib.sha256(body).hexdigest()}
        except (OSError, http.client.HTTPException) as exc:
            raise CollectionError('来源连接失败，请稍后重试或粘贴原文') from exc
        finally:
            connection.close()
    raise CollectionError('无法采集来源')
