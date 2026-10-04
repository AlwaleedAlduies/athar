"""Bounded public-page ingestion. No browser cookies, scripts, proxies or private-network requests."""
import gzip
import io
import ipaddress
import re
import socket
import ssl
import time
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit, urljoin, quote
from django.core.exceptions import ValidationError

MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 120000


def public_target(url):
    if len(url) > 2048 or re.search(r'[\x00-\x20\\]', url):
        raise ValidationError('الرابط غير صالح.')
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ['http', 'https'] or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        host = parsed.hostname.encode('idna').decode('ascii')
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if port != (443 if parsed.scheme == 'https' else 80) or '%' in host:
            raise ValueError()
        addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError()
    except (ValueError, UnicodeError, OSError):
        raise ValidationError('استخدم رابط صفحة عامة على الإنترنت؛ العناوين المحلية والداخلية غير مسموحة.') from None
    return parsed, host, port, addresses[0]


class PinnedHTTP(HTTPConnection):
    def __init__(self, host, port, address):
        super().__init__(host, port, timeout=10)
        self.address = address

    def connect(self):
        self.sock = socket.create_connection((self.address, self.port), self.timeout)


class PinnedHTTPS(HTTPSConnection):
    def __init__(self, host, port, address):
        super().__init__(host, port, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class PageText:
    """Extract the reading body, retaining footnotes but excluding site furniture."""
    ignored = {'head','script','style','nav','footer','aside','form','noscript','svg','iframe','button','input','select','textarea','template'}
    blocks = {'p','div','section','article','main','li','br','h1','h2','h3','h4','h5','h6','tr','blockquote'}
    noise = re.compile(r'(?:^|[\s_-])(?:nav|navbar|menu|sidebar|breadcrumb|breadcrumbs|pagination|share|sharing|social|cookie|consent|modal|advert|advertisement|ads|related|recommended|comments|toolbar|search|site-header|site-footer|post-meta|entry-meta|article-meta|d-none)(?:$|[\s_-])',re.I)

    def __init__(self, url=''):
        self.url, self.parts = url, []

    def feed(self, text):
        self.parts.append(text)

    def text(self):
        from lxml import html, etree
        try:
            root = html.fromstring(''.join(self.parts), parser=html.HTMLParser(no_network=True))
        except (ValueError, etree.ParserError):
            return ''
        for node in list(root.iter()):
            if not isinstance(node.tag,str):
                if node.getparent() is not None: node.drop_tree()
                continue
            attrs = ' '.join([node.get('class',''),node.get('id','')])
            hidden = 'hidden' in node.attrib or node.get('aria-hidden') == 'true' or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden',node.get('style',''),re.I)
            role = node.get('role','')
            furniture = node.tag in self.ignored or role in {'navigation','banner','contentinfo','dialog','search'} or self.noise.search(attrs)
            if (hidden or furniture) and node is not root and node.getparent() is not None:
                node.drop_tree()
        def has_class(name):
            return root.xpath('//*[contains(concat(" ", normalize-space(@class), " "), $token)]',token=' '+name+' ')
        selected = []
        if urlsplit(self.url).hostname in {'dorar.net','www.dorar.net'} and '/history/event/' in urlsplit(self.url).path:
            selected = has_class('event-container')
            if not selected:
                raise ValidationError('تغيرت بنية صفحة الدرر؛ لم نستطع تحديد نص الحدث. استخدم ملفًا نصيًا بدل استيراد قوائم الموقع.')
        if not selected:
            for query in ['//*[@itemprop="articleBody"]','//article','//*[@role="main"]','//main']:
                selected = root.xpath(query)
                if selected: break
        if not selected:
            for name in ['entry-content','post-content','article-content','article-body','story-body','main-content']:
                selected = has_class(name)
                if selected: break
        if not selected:
            # Prefer the densest prose container when the site has no semantic article marker.
            candidates = root.xpath('//div[p or blockquote] | //section[p or blockquote]')
            def score(node):
                prose = sum(len(''.join(p.itertext())) for p in node.xpath('./p | ./blockquote'))
                links = sum(len(''.join(a.itertext())) for a in node.xpath('.//a'))
                return prose - links
            best = max(candidates,key=score,default=None)
            selected = [best] if best is not None and score(best)>120 else [root]
        # Nested article/main markers must not duplicate text.
        chosen = set(selected)
        selected = [n for n in selected if not any(p in chosen for p in n.iterancestors())]
        parts=[]
        def visit(node):
            if node.tag in self.blocks: parts.append('\n')
            if node.text: parts.append(node.text)
            for child in node:
                visit(child)
                if child.tail: parts.append(child.tail)
            if node.tag in self.blocks: parts.append('\n')
        for node in selected: visit(node)
        return '\n'.join(line for part in ''.join(parts).splitlines() if (line := re.sub(r'\s+', ' ', part).strip()))


def fetch_page(url):
    deadline = time.monotonic() + 30
    for hop in range(4):
        parsed, host, port, address = public_target(url)
        connection = (PinnedHTTPS if parsed.scheme == 'https' else PinnedHTTP)(host, port, address)
        try:
            path = quote(parsed.path or '/', safe='/%:@!$&\'()*+,;=-._~')
            if parsed.query:
                path += '?' + quote(parsed.query, safe='/%?:@!$&\'()*+,;=-._~')
            connection.request('GET', path, headers={'User-Agent': 'ATHAR-SourceReader/1.0', 'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in [301, 302, 303, 307, 308]:
                target = response.getheader('Location')
                if not target or hop == 3:
                    raise ValidationError('تعذر متابعة تحويلات هذا الرابط.')
                url = urljoin(url, target)
                continue  # Every redirect is resolved, validated and pinned again.
            if response.status != 200:
                raise ValidationError('لم يُتح الموقع قراءة هذه الصفحة. استخدم ملفًا نصيًا أو مصدرًا آخر.')
            content_type = response.getheader('Content-Type', '')
            if content_type.split(';')[0].lower() not in ['text/html', 'application/xhtml+xml', 'text/plain']:
                raise ValidationError('الرابط يجب أن يشير إلى صفحة نصية. للـPDF استخدم رفع الملفات.')
            body = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValidationError('انتهت مهلة جلب الصفحة.')
                if connection.sock:
                    connection.sock.settimeout(min(10, remaining))
                piece = response.read(min(16384, MAX_BYTES + 1 - len(body)))
                if not piece:
                    break
                body.extend(piece)
                if len(body) > MAX_BYTES:
                    raise ValidationError('الصفحة أكبر من حد القراءة (٢ ميغابايت).')
            encoding = response.getheader('Content-Encoding', '').lower()
            if encoding == 'gzip':
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                    body = compressed.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValidationError('محتوى الصفحة بعد فك الضغط أكبر من الحد.')
            elif encoding not in ['', 'identity']:
                raise ValidationError('ضغط الصفحة غير مدعوم؛ استخدم ملفًا نصيًا.')
            charset = re.search(r'charset=([\w-]+)', content_type, re.I)
            text = bytes(body).decode(charset[1] if charset else 'utf-8', errors='replace')
            if not content_type.startswith('text/plain'):
                parser = PageText(url=url); parser.feed(text); text = parser.text()
            if len(text) < 60:
                raise ValidationError('لم يُستخرج نص كافٍ؛ قد تتطلب الصفحة JavaScript أو تسجيل دخول.')
            if len(text) > MAX_TEXT:
                raise ValidationError('النص أطول من حد الاستيراد؛ استخدم ملفًا يضم القسم المطلوب.')
            return url, text
        except ValidationError:
            raise
        except (OSError, ValueError, LookupError):
            raise ValidationError('تعذر جلب الصفحة بأمان؛ تحقق من الرابط أو ارفع ملف المصدر.') from None
        finally:
            connection.close()
