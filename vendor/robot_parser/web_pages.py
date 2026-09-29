"""Область одной модели: адаптеры известных сайтов и осторожный общий HTML-разбор."""
from html.parser import HTMLParser
from urllib.parse import urlparse
import json
import re

KNOWN={
    'ronavi-robotics.ru':'ronavi',
    'robob2b.ru':'robob2b',
    'xn--l1aeahg.xn--p1ai':'moros',
}

class VisibleText(HTMLParser):
    BLOCK={'h1','h2','h3','h4','p','li','tr','section','article','br'}
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    HIDDEN={'script','style','noscript','svg'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[];self.hidden=0;self.headings=[];self.heading=None;self.htext=[]
    def handle_starttag(self,tag,attrs):
        if tag in self.HIDDEN:self.hidden+=1
        if self.hidden:return
        if tag in self.BLOCK:self.parts.append('\n')
        if tag=='div':self.parts.append(' ')
        if tag in ('td','th'):self.parts.append(' | ')
        if tag in ('h1','h2','h3'):self.heading=tag;self.htext=[]
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in self.HIDDEN:self.hidden=max(0,self.hidden-1);return
        if self.hidden:return
        if tag==self.heading:
            self.headings.append((tag,' '.join(''.join(self.htext).split())))
            self.heading=None
        if tag in self.BLOCK:self.parts.append('\n')
        if tag=='div':self.parts.append(' ')
    def handle_data(self,data):
        if self.hidden:return
        self.parts.append(data)
        if self.heading:self.htext.append(data)
    def lines(self):
        return [' '.join(x.split()).strip(' |') for x in ''.join(self.parts).splitlines() if x.strip(' |\t')]

def domain_adapter(url):
    host=(urlparse(url).hostname or '').lower().removeprefix('www.')
    return KNOWN.get(host)

def identity(model):
    # Число/артикул обязателен: простого слова AMR недостаточно для совпадения.
    parts=re.findall(r'[a-zа-я0-9]+(?:-[a-zа-я0-9]+)*',model.casefold().replace('ё','е'))
    numbered=[p for p in parts if any(c.isdigit() for c in p)]
    model_codes=[p for p in numbered if any(c.isalpha() for c in p)]
    return model_codes[0] if model_codes else numbered[0] if numbered else ''.join(parts)

class Node:
    def __init__(self,tag='',attrs=None,parent=None):
        self.tag=tag;self.attrs=dict(attrs or []);self.parent=parent;self.children=[]
    def text(self):
        return ' '.join(' '.join(x.text() if isinstance(x,Node) else x for x in self.children).split())
    def descendants(self):
        for child in self.children:
            if isinstance(child,Node):
                yield child
                yield from child.descendants()

class ProductDOM(HTMLParser):
    VOID=VisibleText.VOID
    SKIP={'script','style','noscript','svg','nav','footer','aside','form'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root=Node('root');self.stack=[self.root];self.scripts=[];self.script=None
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('type','').casefold()=='application/ld+json':self.script=[]
        node=Node(tag,attrs,self.stack[-1]);self.stack[-1].children.append(node)
        if tag not in self.VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag=='script' and self.script is not None:
            self.scripts.append(''.join(self.script));self.script=None
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:
                del self.stack[i:];break
    def handle_data(self,data):
        if self.stack[-1].tag=='script' and self.script is not None:self.script.append(data)
        self.stack[-1].children.append(data)

def _excluded(node):
    attrs=' '.join(str(node.attrs.get(k,'')) for k in ('class','id','role')).casefold()
    if node.tag in ProductDOM.SKIP or bool(re.search(r'\b(?:related|recommended|similar|upsell|cross-sell|carousel|compare|sidebar|product-list|catalog-list|похож|рекомендуем)',attrs)):
        return True
    if node.tag in ('section','div'):
        headings=[c for c in node.children if isinstance(c,Node) and c.tag in ('h2','h3')]
        if any(re.search(r'^(?:related products|similar products|you may also like|recommended|похожие товары|рекомендуем)',h.text(),re.I) for h in headings):
            return True
    return False

def _product_objects(scripts):
    def walk(value):
        if isinstance(value,list):
            for item in value:yield from walk(item)
        elif isinstance(value,dict):
            types=value.get('@type',[])
            if isinstance(types,str):types=[types]
            if any(t.casefold().endswith('product') for t in types if isinstance(t,str)):yield value
            for key in ('@graph','mainEntity'):
                if key in value:yield from walk(value[key])
    for raw in scripts:
        try:yield from walk(json.loads(raw))
        except (ValueError,TypeError):continue

def generic_product_lines(html,source):
    """Неизвестный сайт: один H1, одна область товара; без догадок по соседним блокам."""
    dom=ProductDOM();dom.feed(html)
    token=identity(source['model_name'])
    headings=[n for n in dom.root.descendants() if n.tag=='h1' and not any(_excluded(p) for p in ancestors(n))]
    if len(headings)!=1 or not token or not mentions_model(headings[0].text(),token):
        return None,'Не найден единственный H1 выбранной модели'
    h1=headings[0]
    scope=next((p for p in ancestors(h1) if p.tag in ('article','main') and not _excluded(p)),None)
    products=[p for p in _product_objects(dom.scripts) if mentions_model(str(p.get('name','')),token)]
    if scope is None:
        if len(products)!=1:
            # Нет доказуемых границ товара: тело может включать чужие модели и цены.
            return None,'Не определена область модели (нужен main/article или Product JSON-LD)'
        scope=Node('empty')
    else:
        scope_h1=[n for n in scope.descendants() if n.tag=='h1' and not any(_excluded(p) for p in ancestors(n) if p is not scope)]
        if len(scope_h1)!=1:return None,'В области страницы несколько моделей'
    lines=[];page_prices=[];structured_prices=[]
    def add(label,value):
        label=' '.join(str(label).split()).strip(' :|')
        value=' '.join(str(value).split()).strip(' :|')
        if label and value and len(label)<130 and len(value)<400:
            lines.append(label+' | '+value)
    def traverse(node):
        if _excluded(node):return
        if node.tag=='tr':
            cells=[c for c in node.descendants() if c.tag in ('th','td')]
            if len(cells)==2:add(cells[0].text(),cells[1].text())
            return
        if node.tag=='dl':
            parts=[c for c in node.descendants() if c.tag in ('dt','dd')]
            for a,b in zip(parts,parts[1:]):
                if a.tag=='dt' and b.tag=='dd':add(a.text(),b.text())
            return
        if node.tag in ('p','li') and not any(c.tag in ('tr','table','dl') for c in node.descendants()):
            line=node.text()
            if re.match(r'^(?:цена|price|rental price)\s*:',line,re.I):
                label,value=line.split(':',1);page_prices.append((label,value))
            elif ' | ' in line:
                label,value=line.split(' | ',1);add(label,value)
        for child in node.children:
            if isinstance(child,Node):traverse(child)
    traverse(scope)
    if len(products)==1:
        product=products[0]
        for prop in product.get('additionalProperty',[]):
            if isinstance(prop,dict) and prop.get('name') and prop.get('value') is not None:
                add(prop['name'],prop['value'])
        offers=product.get('offers',[])
        if isinstance(offers,dict):offers=[offers]
        for offer in offers:
            if isinstance(offer,dict) and offer.get('price') is not None and offer.get('priceCurrency'):
                structured_prices.append(('Price',str(offer['price'])+' '+str(offer['priceCurrency'])))
    # Несколько разных цен в общей области main нельзя привязать к одной модели.
    # JSON-LD выбранного Product имеет отдельную привязку по имени модели.
    unique_prices=list(dict.fromkeys((a.strip(),b.strip()) for a,b in (structured_prices or page_prices)))
    if len(unique_prices)==1:add(*unique_prices[0])
    if not lines:return None,'В области модели нет распознанных пар параметр–значение'
    marker='generic:ambiguous-price' if len(unique_prices)>1 else ('generic:product-jsonld' if scope.tag=='empty' else 'generic:main/article+h1')
    return '\n'.join(dict.fromkeys(lines)),marker

def ancestors(node):
    parent=node.parent
    while parent is not None:
        yield parent;parent=parent.parent

def mentions_model(line,token):
    return bool(re.search(r'(?<![a-zа-я0-9])'+re.escape(token)+r'(?![a-zа-я0-9])',line.casefold().replace('ё','е')))

def product_lines(html,source):
    adapter=domain_adapter(source.get('source_url',''))
    if adapter!=source.get('adapter'):
        return None,'Домен не имеет проверенного обработчика'
    p=VisibleText();p.feed(html)
    lines=p.lines()
    h1=[name for tag,name in p.headings if tag=='h1']
    token=identity(source['model_name'])
    if len(h1)!=1 or not token or not mentions_model(h1[0],token):
        return None,'Заголовок H1 не подтверждает выбранную модель'
    if adapter=='ronavi':
        headings=[i for i,x in enumerate(lines) if re.search(r'^технические характеристики(?:\s|$)',x,re.I)]
        if len(headings)!=1:return None,'Раздел ТТХ модели не определён однозначно'
        start=headings[0]
        if not (mentions_model(lines[start],token) or lines[start].casefold()=='технические характеристики'):
            return None,'Раздел ТТХ не связан с выбранной моделью'
        end=next((i for i in range(start+1,len(lines)) if re.search(r'нужны подробные спецификации|готовы к автоматизации',lines[i],re.I)),None)
        if end is None:return None,'Конец раздела ТТХ модели не определён'
        specs=lines[start+1:end]
        out=list(specs)
        # Отдельный коммерческий блок должен назвать ту же модель.
        for i,line in enumerate(lines[end:],end):
            if re.search(r'цена за единицу',line,re.I) and mentions_model(line,token):
                q=re.search(r'при покупке от\s*(\d+)\s*шт.*?:\s*(от\s*[\d\s\u00a0\u202f,.]+\s*₽)',line,re.I)
                if q:out.append('Цена | '+q.group(2)+' при покупке от '+q.group(1)+' шт.')
                else:out.append('Цена | '+line)
                if i+2<len(lines) and re.search(r'стоимость\s*\(',lines[i+2],re.I):
                    out.append('Цена | '+lines[i+2])
                elif i+1<len(lines) and re.search(r'стоимость\s*\(',lines[i+1],re.I):
                    out.append('Цена | '+lines[i+1])
                break
        return '\n'.join(out),'heading:'+lines[start]
    if adapter=='robob2b':
        start=next((i for i,x in enumerate(lines) if re.search(r'характеристики',x,re.I) and mentions_model(x,token)),None)
        if start is None:return None,'Раздел характеристик модели не определён'
        end=next((i for i in range(start+1,len(lines)) if re.search(r'^обсуждения|похожие товары|рекомендуем',lines[i],re.I)),None)
        if end is None:return None,'Конец раздела характеристик модели не определён'
        out=lines[start+1:end]
        hindex=next((i for i,x in enumerate(lines) if mentions_model(x,token) and x==h1[0]),None)
        if hindex is not None and hindex<start and any(re.fullmatch(r'цена\s+по запросу',x,re.I) for x in lines[hindex:start]):
            out.insert(0,'Цена | по запросу')
        return '\n'.join(out),'heading:'+lines[start]
    if adapter=='moros':
        start=next((i for i,x in enumerate(lines) if re.search(r'технические характеристики',x,re.I)),None)
        if start is None:return None,'Раздел ТТХ модели не определён'
        end=next((i for i in range(start+1,len(lines)) if re.search(r'^ключевые функциональные возможности|^область применения|^обсуждения|похожие|другие модели|оставить заявку',lines[i],re.I)),None)
        if end is None:return None,'Конец раздела ТТХ модели не определён'
        return '\n'.join(lines[start+1:end]),'heading:'+lines[start]
    return None,'Обработчик страницы отсутствует'
