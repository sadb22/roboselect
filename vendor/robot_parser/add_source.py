"""Одна команда для публичного HTTPS URL: получение и сохранение HTML."""
import argparse, hashlib, ipaddress, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from web_pages import VisibleText, domain_adapter, identity, generic_product_lines, product_lines

MAX_BYTES=5_000_000

def public_url(url):
    p=urlparse(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('Нужен публичный HTTPS URL без учётных данных и нестандартного порта')
    host=p.hostname.lower().strip('.')
    if host=='localhost' or host.endswith(('.localhost','.local','.internal')):
        raise ValueError('Локальный адрес запрещён')
    try:
        if not ipaddress.ip_address(host).is_global:raise ValueError('Непубличный адрес запрещён')
    except ValueError as e:
        if 'Непубличный' in str(e):raise
    return p

class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch_http(url):
    public_url(url)
    req=Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; RoboscopeData/1.0)'})
    with build_opener(PublicRedirects()).open(req,timeout=20) as response:
        public_url(response.url)
        if 'text/html' not in response.headers.get('Content-Type','').lower():
            raise ValueError('Ссылка не отдала HTML')
        raw=response.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Страница превышает 5 МБ')
    return raw

def fetch_browser(url):
    """Установить отдельно: pip install playwright; python -m playwright install chromium."""
    public_url(url)
    try:from playwright.sync_api import sync_playwright
    except ImportError as e:raise ValueError('Для страниц с JavaScript установите playwright и Chromium (см. README)') from e
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            page=browser.new_page()
            def route_check(route):
                try:public_url(route.request.url)
                except ValueError:route.abort();return
                route.continue_()
            page.route('**/*',route_check)
            page.goto(url,wait_until='domcontentloaded',timeout=25000)
            page.wait_for_timeout(1500)
            public_url(page.url)
            raw=page.content().encode('utf-8')
        finally:browser.close()
    if len(raw)>MAX_BYTES:raise ValueError('Страница превышает 5 МБ')
    return raw

def h1_names(raw):
    try:html=raw.decode('utf-8-sig')
    except UnicodeDecodeError as e:raise ValueError('HTML не в UTF-8; нужен отдельный обработчик кодировки') from e
    visible=VisibleText();visible.feed(html)
    return [name for tag,name in visible.headings if tag=='h1']

def register(url,root,model_key=None,model_name=None,html_bytes=None,browser='auto'):
    public_url(url)
    registry=root/'sources.json'
    config=json.loads(registry.read_text(encoding='utf-8'))
    related=[x for x in config['sources'] if x.get('source_url')==url]
    existing=next((x for x in related if x.get('kind')=='html'),None)
    if browser not in ('auto','always','never'):raise ValueError('Неизвестный режим браузера')
    if html_bytes is None:
        if browser=='always':html_bytes=fetch_browser(url)
        else:
            try:html_bytes=fetch_http(url)
            except Exception:
                if browser=='never':raise
                html_bytes=fetch_browser(url)
            if browser=='auto':
                names=h1_names(html_bytes)
                probe={'model_name':model_name or names[0] if len(names)==1 else '',
                       'source_url':url,'adapter':domain_adapter(url)}
                extractor=product_lines if domain_adapter(url) else generic_product_lines
                detected,_=extractor(html_bytes.decode('utf-8-sig'),probe) if len(names)==1 else (None,None)
                if detected is None:html_bytes=fetch_browser(url)
    if len(html_bytes)>MAX_BYTES:raise ValueError('Страница превышает 5 МБ')
    h1=h1_names(html_bytes)
    if len(h1)!=1:raise ValueError('Не найден однозначный H1 модели; источник не добавлен')
    name=model_name or h1[0]
    token=identity(name)
    if not token or not re.search(r'\d',token):raise ValueError('Название модели не удалось выделить из H1')
    adapter=domain_adapter(url) or 'generic'
    host=urlparse(url).hostname.lower().removeprefix('www.')
    known_keys={x.get('model_key') for x in related if x.get('model_key')}
    key=model_key or (next(iter(known_keys)) if len(known_keys)==1 else f'{adapter if adapter!="generic" else host}-{token}')
    digest=hashlib.sha256(html_bytes).hexdigest()
    source_id=existing['source_id'] if existing else f'web-{hashlib.sha256(url.encode()).hexdigest()[:16]}'
    path=f'snapshots/web_{digest}.html'
    (root/path).parent.mkdir(parents=True,exist_ok=True)
    (root/path).write_bytes(html_bytes)
    manufacturer={'ronavi':'Ronavi Robotics','moros':'МОРОС'}.get(adapter)
    source={'source_id':source_id,'kind':'html','path':path,'source_url':url,
            'acquired_at':datetime.now(timezone.utc).date().isoformat(),
            'model_key':key,'model_name':name,'manufacturer':manufacturer,
            'adapter':adapter,'category':None,'scenario_codes':[]}
    if existing:
        if model_key is None:source['model_key']=existing['model_key']
        source['category']=existing.get('category')
        source['scenario_codes']=existing.get('scenario_codes',[])
        source['manufacturer']=existing.get('manufacturer') or manufacturer
        config['sources'][config['sources'].index(existing)]=source
    else:config['sources'].append(source)
    registry.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return source

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Скачать HTML карточки по URL и добавить источник')
    p.add_argument('url',nargs='?',help='Один URL карточки')
    p.add_argument('--file',help='Текстовый список URL, по одному в строке')
    p.add_argument('--model-key',help='Для второго источника уже известной модели')
    p.add_argument('--model-name',help='Если H1 содержит лишний текст')
    p.add_argument('--browser',choices=['auto','always','never'],default='auto',help='auto: Chromium при ошибке обычной загрузки или отсутствии H1')
    args=p.parse_args()
    if bool(args.url)==bool(args.file):p.error('Укажите URL или --file со списком ссылок')
    if args.file and (args.model_key or args.model_name):p.error('Для --file нельзя задать общую модель всем ссылкам')
    urls=[args.url] if args.url else [x.strip() for x in Path(args.file).read_text(encoding='utf-8').splitlines() if x.strip() and not x.lstrip().startswith('#')]
    for url in urls:
        try:
            source=register(url,Path(__file__).resolve().parent,args.model_key,args.model_name,browser=args.browser)
            print(json.dumps({'added':source['source_id'],'model_key':source['model_key'],
                              'path':source['path'],'next':'python3 parser.py --output export'},ensure_ascii=False))
        except Exception as e:
            print(json.dumps({'url':url,'error':str(e)},ensure_ascii=False))
