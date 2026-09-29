"""Validated catalogue contract and warehouse process, all physical units explicit."""
import math
from .finance import FIELDS, defaults

OPERATIONS={'warehouse_rack_stacking':'Снятие / размещение на стеллаже',
 'warehouse_pallet_transport':'Перевозка паллет', 'truck_loading':'Погрузка в автомобиль',
 'warehouse_general_transport':'Перевозка груза', 'warehouse_low_lift':'Подхват паллеты',
 'warehouse_g2p':'Подвоз к оператору'}
TECH={
 'payload_kg':('Грузоподъёмность, кг',1,50000), 'width_m':('Ширина, м',.1,10),
 'length_m':('Длина, м',.1,20), 'min_aisle_m':('Минимальный проход, м',.1,20),
 'speed_m_s':('Рабочая скорость с грузом, м/с',.01,10), 'runtime_h':('Автономность, ч',.01,100),
 'charge_h':('Зарядка, ч',.01,24), 'power_kw':('Средняя мощность, кВт',.001,100),
 'lift_m':('Высота подъёма, м',0,40), 'temp_min':('Минимальная температура, °C',-60,70),
 'temp_max':('Максимальная температура, °C',-60,70),
}
def num(value,name,low=0,high=1e12,integer=False):
    if isinstance(value,bool):raise ValueError(f'{name}: требуется число')
    try:n=float(value)
    except (TypeError,ValueError):raise ValueError(f'{name}: требуется число')
    if not math.isfinite(n) or not low<=n<=high or (integer and n!=int(n)):
        raise ValueError(f'{name}: допустимо {low}…{high}'+(' целое' if integer else ''))
    return int(n) if integer else n

def equipment_data(data):
    d=dict(data)
    for k in ['manufacturer','model','source','configuration']:
        d[k]=str(d.get(k) or '').strip()
        if not d[k] or len(d[k])>500:raise ValueError(f'{k}: обязательное поле, до 500 символов')
    d['sku']=str(d.get('sku',''))[:120]
    d['operations']=list(d.get('operations',[]))
    if not d['operations'] or any(x not in OPERATIONS for x in d['operations']):raise ValueError('Укажите поддерживаемые операции')
    for k,(label,low,high) in TECH.items():
        if d.get(k) in [None,'']:d[k]=None
        else:d[k]=num(d[k],label,low,high)
    if d['temp_min'] is not None and d['temp_max'] is not None and d['temp_min']>d['temp_max']:raise ValueError('Диапазон температуры перевёрнут')
    rates=d.get('rates',{})
    if not isinstance(rates,dict):raise ValueError('Производительность задаётся по операциям')
    d['rates']={k:num(v,'Производительность',.01,10000) for k,v in rates.items() if k in d['operations'] and v not in [None,'']}
    for k in ['purchase','rental_month']:
        d[k]=None if d.get(k) in [None,''] else num(d[k],k,0,1e10)
    if d['rental_month'] is not None and d.get('rental_scope')!='robots_chargers_software_service':
        raise ValueError('Для аренды укажите включение роботов, зарядок, ПО и обслуживания')
    d['rental_scope']=d.get('rental_scope','')
    d['estimated_fields']=list(d.get('estimated_fields',[]))
    if d['estimated_fields'] and not d.get('estimate_basis'):raise ValueError('Нужно основание допущений и ссылки на аналоги')
    d['estimate_basis']=str(d.get('estimate_basis',''))[:2000]
    return d

def default_requirements():
    return dict(area=20000,active_area=10000,aisle_m=3.5,payload_kg=800,temperature=18,
        peak_hour=60,daily_moves=400,clearance_m=.2,allow_human=False,
        routes=[dict(id='main',name='Основной проезд',width_m=3.5,x1=10,y1=50,x2=90,y2=50)],
        operations=[
          dict(id='retrieve',name='Снять паллету со стеллажа',code='warehouse_rack_stacking',predecessors=[],distance_m=0,lift_m=4,route='',buffer=4,stations=3),
          dict(id='move',name='Перевезти в зону выдачи',code='warehouse_pallet_transport',predecessors=['retrieve'],distance_m=60,lift_m=0,route='main',buffer=4,stations=3),
          dict(id='load',name='Погрузить в автомобиль',code='truck_loading',predecessors=['move'],distance_m=0,lift_m=1.2,route='',buffer=2,stations=2)])

def requirements(data,finance):
    d=dict(data);f=defaults()|finance
    for k,(label,_,lo,hi) in FIELDS.items():
        f[k]=None if k=='budget' and f[k] in ['',None] else num(f[k],label,lo,hi,k in ['horizon','days_year','robots_per_charger'])
    for k,lo,hi in [('area',10,1e6),('active_area',10,1e6),('aisle_m',.3,20),('payload_kg',1,50000),('temperature',-60,70),('peak_hour',1,1000),('daily_moves',1,24000),('clearance_m',.05,1)]:d[k]=num(d.get(k),k,lo,hi)
    if d['active_area']>d['area']:raise ValueError('Рабочая зона больше склада')
    if d['daily_moves']/f['hours_day']>d['peak_hour']:raise ValueError('Средняя нагрузка превышает пиковую')
    ops=d.get('operations',[]);routes=d.get('routes',[])
    if not 1<=len(ops)<=6 or len(routes)>6:raise ValueError('Прототип поддерживает от 1 до 6 операций и до 6 проездов')
    ids=[str(o.get('id','')) for o in ops]
    if len(set(ids))!=len(ids) or any(not x or len(x)>40 for x in ids):raise ValueError('Идентификаторы операций должны быть уникальными')
    route_ids=[x['id'] for x in routes]
    if len(set(route_ids))!=len(route_ids):raise ValueError('Проезды должны иметь уникальные ID')
    for route in routes:
        route['width_m']=num(route['width_m'],'Ширина проезда',.3,20)
        for k in ['x1','y1','x2','y2']:route[k]=num(route.get(k,50),k,0,100)
    for o in ops:
        if o.get('code') not in OPERATIONS:raise ValueError('Неизвестная операция')
        if not o.get('name'):raise ValueError('У операции нет названия')
        o['predecessors']=list(dict.fromkeys(o.get('predecessors',[])))
        if any(p not in ids or p==o['id'] for p in o['predecessors']):raise ValueError('Некорректная связь операций')
        for k,lo,hi in [('distance_m',0,1000),('lift_m',0,30),('buffer',0,100),('stations',1,30)]:o[k]=num(o.get(k),k,lo,hi,k in ['buffer','stations'])
        if o.get('route') and o['route'] not in route_ids:raise ValueError('Неизвестный проезд')
    done=set()
    for _ in ops:
        for o in ops:
            if set(o['predecessors'])<=done:done.add(o['id'])
    if len(done)!=len(ops):raise ValueError('В процессе обнаружен цикл')
    d['allow_human']=bool(d.get('allow_human',False))
    return d,f

def compatibility(data,op,req):
    missing=[];violations=[]
    if op['code'] not in data.get('operations',[]):violations.append('Модель не поддерживает операцию')
    needed=['payload_kg','width_m','length_m','min_aisle_m','speed_m_s','runtime_h','charge_h','temp_min','temp_max']
    if op['lift_m']>0:needed+=['lift_m']
    for k in needed:
        if data.get(k) is None:missing.append(TECH[k][0])
    if not data.get('rates',{}).get(op['code']):missing.append('Производительность для операции')
    if data.get('payload_kg') is not None and data['payload_kg']<req['payload_kg']:violations.append('Недостаточная грузоподъёмность')
    aisle=min(req['aisle_m'],next((r['width_m'] for r in req['routes'] if r['id']==op.get('route')),req['aisle_m']))
    if data.get('min_aisle_m') is not None and data['min_aisle_m']>aisle:violations.append('Недостаточная ширина прохода')
    if data.get('width_m') is not None and data['width_m']+2*req['clearance_m']>aisle:violations.append('Габариты не позволяют проехать с заданным зазором')
    if data.get('lift_m') is not None and data['lift_m']<op['lift_m']:violations.append('Недостаточная высота подъёма')
    if data.get('temp_min') is not None and req['temperature']<data['temp_min']:violations.append('Температура ниже допустимой')
    if data.get('temp_max') is not None and req['temperature']>data['temp_max']:violations.append('Температура выше допустимой')
    return missing,violations
