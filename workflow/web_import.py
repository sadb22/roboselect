"""Bounded public HTTPS ingestion. Connections are pinned to validated public IPs."""
import hashlib
import http.client
import ipaddress
import json
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, urljoin
from django.conf import settings
from .provenance_models import Source
from .catalog import import_parser


def fetch(url):
    deadline = time.monotonic() + 25
    for _ in range(4):
        p = urlparse(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
            raise ValueError('Нужен публичный HTTPS URL без пароля и нестандартного порта')
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Локальные и служебные сетевые адреса запрещены')
        connection = http.client.HTTPSConnection(p.hostname, timeout=12)
        # Preserve TLS hostname validation while avoiding a second DNS resolution.
        raw_socket = socket.create_connection((addresses[0][4][0], 443), timeout=12)
        try:
            connection.sock = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=p.hostname)
            connection.request('GET', (p.path or '/') + ('?' + p.query if p.query else ''), headers={'User-Agent': 'RoboSelect/1.0'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader('Location', '')); continue
            if response.status != 200 or 'text/html' not in response.getheader('Content-Type', ''):
                raise ValueError(f'Источник вернул HTTP {response.status}; нужна HTML-карточка модели')
            chunks = []; total = 0
            while total <= 5_000_000:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('Получение HTML превысило 25 секунд')
                if connection.sock:
                    connection.sock.settimeout(min(12, remaining))
                chunk = response.read1(min(65536, 5_000_001 - total))
                if not chunk:
                    break
                chunks.append(chunk); total += len(chunk)
            content = b''.join(chunks)
            if len(content) > 5_000_000:
                raise ValueError('HTML превышает 5 МБ')
            return content
        finally:
            connection.close(); raw_socket.close()
    raise ValueError('Слишком много перенаправлений')


def add_web_source(user, url):
    if not user.is_staff:
        raise PermissionError('Требуются права администратора')
    if len(url) > 2000:
        raise ValueError('Слишком длинный URL')
    p = urlparse(url)
    if p.scheme != 'https' or not p.hostname:
        raise ValueError('Укажите полный HTTPS URL карточки модели')
    source, _ = Source.objects.get_or_create(key='web-' + hashlib.sha256(url.encode()).hexdigest()[:16],
        defaults={'location': url, 'site': p.hostname, 'kind': 'html'})
    source.status = 'processing'; source.error = ''; source.save()
    try:
        content = fetch(url)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Only bundled executable code; uploaded source bytes are data.
            for f in (settings.BASE_DIR / 'vendor/robot_parser').iterdir():
                if f.suffix in ('.py', '.json'):
                    shutil.copy2(f, root / f.name)
            registry = json.loads((root / 'sources.json').read_text(encoding='utf-8'))
            registry['sources'] = []
            (root / 'sources.json').write_text(json.dumps(registry), encoding='utf-8')
            (root / 'page.html').write_bytes(content)
            code = "from pathlib import Path; from add_source import register; import sys; register(sys.argv[1],Path('.'),html_bytes=Path('page.html').read_bytes(),browser='never')"
            result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, url], cwd=root, capture_output=True, timeout=20)
            if result.returncode:
                raise ValueError('Не выделена одна модель в H1. Нужна отдельная карточка, а не каталог; HTML должен быть UTF-8.')
            result = subprocess.run([sys.executable, '-X', 'utf8', str(root / 'parser.py'), '--output', str(root / 'export')], capture_output=True, timeout=25)
            if result.returncode:
                raise ValueError('Обработчик страницы завершился ошибкой. Сохраните HTML и проверьте его офлайн.')
            from .provenance import read_export
            errors = read_export(root / 'export', 'source_errors')
            if errors or not read_export(root / 'export', 'observations'):
                raise ValueError('В HTML не найдены поддерживаемые характеристики. Возможно, нужны JavaScript или отдельный обработчик; импорт не выполнен.')
            batch = import_parser(user, root / 'export')
        source.refresh_from_db(); source.status = 'review'; source.error = ''; source.save()
        return batch
    except (ValueError, OSError, subprocess.TimeoutExpired, http.client.HTTPException) as e:
        source.status = 'error'
        source.error = str(e) if isinstance(e, ValueError) else 'Не удалось получить или обработать страницу за отведённое время. Проверьте адрес и повторите.'
        source.save()
        raise ValueError(source.error) from e
