"""Разбор одного предложения; денежные суммы — точные десятичные строки."""
from decimal import Decimal
import re

# Число может быть коротким; валюту требуем отдельно от числа.
NUMBER=re.compile(r'(?<![\w])([+\-−]?\d+(?:[ \u00a0\u202f]\d{3})*(?:[,.]\d{1,2})?)(?![\w\d.,])')
CURRENCY=re.compile(r'₽|\bруб(?:\.|лей|ля)?\b|\b(?:RUB|USD|EUR)\b|€',re.I)
PERIOD=re.compile(r'(?:/|в\s+|per\s+)(?:\s*)(месяц|мес\.?|день|сутки|год|недел[яю]|month|day|year|week)\b',re.I)

def parse(text,source_id,model_key,supplier=None,full_text=None):
    """Возвращает предложение или причину проверки; контекст не меняет вид сделки."""
    low=text.casefold().replace('ё','е')
    full=full_text or text
    if not re.search(r'\b(?:цена|price)\b|₽|\bруб|\b(?:rub|usd|eur)\b|€',low,re.I):
        return None,'Не найдено обозначение цены'
    currency_matches=list(CURRENCY.finditer(text))
    codes=[]
    for m in currency_matches:
        word=m.group().lower().rstrip('.')
        codes.append('RUB' if word=='₽' or word.startswith('руб') or word=='rub' else 'EUR' if word in ('€','eur') else 'USD')
    if len(set(codes))>1:return None,'Разные валюты одного предложения'
    cur=codes[0] if codes else None
    quantity=re.search(r'при\s+покупке\s+от\s+(\d+)\s*шт',low)
    vat=re.search(r'(без ндс|с ндс|ндс\s*\d+\s*%)',low)
    rental=bool(re.search(r'\bаренд[аыуеы]|\bпрокат\b|\brent(?:al)?\b|\blease\b',low))
    service=bool(re.search(r'\bуслуг[ауы]|\bподписк|\bservice\b|\bsubscription\b',low))
    kind='rental' if rental else 'service' if service else 'purchase'
    period=PERIOD.search(low)
    amounts=[]
    for m in NUMBER.finditer(text.translate(str.maketrans({'−':'-'}))):
        tail=text[m.end():].lstrip().lower()
        if re.match(r'шт\b|%',tail):continue
        # Число в периоде, налоге или условии количества не становится ценой.
        if re.match(r'\d+\s*%',m.group()) or re.search(r'ндс\s*$',text[:m.start()],re.I):continue
        number=Decimal(m.group(1).replace(' ','').replace('\u00a0','').replace('\u202f','').replace(',','.'))
        if number<0:return None,'Отрицательная цена недопустима'
        amounts.append(number)
    offer={'source_id':source_id,'model_key':model_key,'supplier':supplier,'configuration':None,
           'transaction_type':kind,'tariff_period':period.group(1).lower().rstrip('.') if period else None,
           'minimum_quantity':int(quantity.group(1)) if quantity else None,
           'included_items':None,'vat':vat.group(1) if vat else None,'raw_conditions':full,
           'raw_offer':text,'currency':cur,'price_min':None,'price_max':None,
           'price_kind':'unknown','requires_review':False}
    if ('по запросу' in low or 'on request' in low or 'contact for price' in low) and not amounts:return offer,None
    if not amounts or not cur:return None,'Сумма или валюта не распознаны'
    if len(amounts)>2:return None,'Несколько цен без однозначного условия'
    if kind in ('rental','service') and not period:offer['requires_review']=True
    if len(amounts)==2:
        if amounts[0]>amounts[1]:return None,'Нижняя цена больше верхней'
        offer['price_min'],offer['price_max']=map(str,amounts)
        offer['price_kind']='range'
        if 'зависит от комплектации' in low:offer['requires_review']=True
    elif re.search(r'\b(?:не более|до|up to|at most)\s*[+\-−]?\d',low):
        offer['price_max']=str(amounts[0]);offer['price_kind']='upper_bound'
    elif re.search(r'\b(?:от|не менее|from|at least)\b',low):
        offer['price_min']=str(amounts[0]);offer['price_kind']='lower_bound'
    else:
        offer['price_min']=offer['price_max']=str(amounts[0]);offer['price_kind']='exact'
    if 'при покупке' in low and not quantity:offer['requires_review']=True
    # Контекст других предложений оставляем целиком, но не переносим их условия.
    if full_text and full_text!=text and re.search(r'\b(?:ндс|комплектац|тариф)\b',full_text,re.I) and not re.search(r'\b(?:ндс|комплектац|тариф)\b',text,re.I):
        offer['requires_review']=True
    return offer,None
