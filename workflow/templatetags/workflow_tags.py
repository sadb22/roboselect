from django import template
from decimal import Decimal,InvalidOperation
register=template.Library()
@register.filter
def status(value):
    return {'pending':'На проверке','published':'Опубликовано','returned':'На доработку',
      'blocked':'Недостаточно данных','incompatible':'Не соответствует требованиям',
      'confirmed':'Подтверждено','preliminary':'Предварительный расчёт','waiting':'Ожидаем ответ',
      'declined':'Отказ','alternative':'Предложена альтернатива','contracts':'Договоры',
      'payment':'Оплата','delivery':'Доставка и установка','acceptance':'Приёмка','complete':'Завершено',
      'purchase':'Покупка','rental':'Аренда','contract':'Договор подписан','pay':'Оплата отмечена',
      'installed':'Оборудование доставлено и установлено','accept':'Приёмка подтверждена'}.get(value,value)
@register.filter
def money(value):
    if value is None:return 'Не указано'
    try:return f'{Decimal(str(value)):,.2f}'.replace(',',' ').replace('.',',')
    except (InvalidOperation,ValueError):return value
@register.filter
def get(mapping,key):return mapping.get(key,'') if isinstance(mapping,dict) else ''

@register.filter
def payback_label(s):
    if s['mode']=='baseline':return 'Не применяется'
    return f"{s['payback']:.2f}".replace('.',',') if s.get('payback') is not None else 'Не окупается'

@register.filter
def discounted_payback_label(s):
    if s['mode']=='baseline':return 'Не применяется'
    return f"{s['discounted_payback']:.2f}".replace('.',',') if s.get('discounted_payback') is not None else 'За пределами горизонта'

@register.filter
def roi_label(s):
    return f"{s['roi']:.1f}".replace('.',',') if s.get('roi') is not None else 'Не применяется'
