"""Nominal five-year comparison. Decimal money; no purchase option in rental."""
from decimal import Decimal

FIELDS = {
 'horizon':('Горизонт сравнения, лет',5,5,15),
 'price_factor':('Коэффициент цены покупки из каталога',1,.1,10),
 'utilization':('Целевая загрузка при подборе, доля',.8,.1,1),
 'hours_day':('Работа, ч/сутки',8,1,24), 'days_year':('Рабочих дней в году',247,1,366),
 'staff':('Персонал сейчас, чел.',30,1,2000), 'payroll_month':('Текущий ФОТ с начислениями, руб./мес.',3000000,0,1e10),
 'other_month':('Прочие текущие расходы, руб./мес.',400000,0,1e10),
 'operators':('Операторы после внедрения, чел.',8,0,2000),
 'remaining_other_year':('Сохраняемые прочие расходы, руб./год',0,0,1e10),
 'electricity':('Электроэнергия, руб./кВт·ч',9,0,1000),
 'charger_price':('Зарядная станция, руб.',400000,0,1e9),
 'robots_per_charger':('Роботов на зарядную станцию',4,1,100),
 'infrastructure':('Подготовка инфраструктуры, руб.',3000000,0,1e10),
 'software':('Первоначальное ПО, руб.',2000000,0,1e10),
 'integration':('Интеграция и ПНР, руб.',4000000,0,1e10),
 'training':('Обучение, руб.',600000,0,1e10),
 'contingency':('Резерв бюджета, %',10,0,100),
 'maintenance':('Сервис за год, % стоимости роботов',5,0,100),
 'licenses':('Лицензии, руб./год',1500000,0,1e10),
 'rental_setup':('Разовый запуск аренды, руб.',1500000,0,1e10),
 'discount':('Ставка дисконтирования, %',15.28,0,100),
 'budget':('Стартовый бюджет, руб. (пусто: не задан)',None,0,1e12),
}
def defaults(): return {k:v[1] for k,v in FIELDS.items()}
def D(x): return Decimal(str(x))
def money(x): return str(x.quantize(Decimal('.01')))

def metrics(capex,opex,baseline,rate,horizon=5):
    effect=baseline-opex;total=-capex;discounted=-capex;flows=[];dpb=None
    for year in range(1,horizon+1):
        previous=discounted;pv=effect/(1+rate)**year
        total+=effect;discounted+=pv
        if dpb is None and discounted>=0 and pv>0:dpb=D(year-1)+max(D(0),-previous)/pv
        flows.append(dict(year=year,flow=money(effect),cumulative=money(total),discounted=money(discounted)))
    return dict(capex=money(capex),opex=money(opex),tco=money(capex+horizon*opex),annual_effect=money(effect),
        npv=money(discounted),payback=float(capex/effect) if effect>0 else None,
        discounted_payback=float(dpb) if dpb is not None else None,
        roi=float(horizon*effect/capex*100) if capex else None,net_roi=float((horizon*effect-capex)/capex*100) if capex else None,flows=flows)

def calculate(finance,groups,annual_volume):
    import math
    f={k:D(v) if v is not None else None for k,v in finance.items()}
    baseline=12*(f['payroll_month']+f['other_month']);rate=f['discount']/100;horizon=int(f.get('horizon',5))
    robots=[g for g in groups if g['kind']=='robot'];humans=[g for g in groups if g['kind']=='human']
    human=sum(D(g['count'])*D(g['salary_month'])*12 for g in humans)
    payroll=f['operators']*f['payroll_month']/f['staff']*12+human
    common=payroll+f['remaining_other_year']
    energy=sum(D(g['total_count'])*D(g['data']['power_kw'])*f['hours_day']*f['days_year']*f['electricity'] for g in robots)
    robot_cost=sum(D(g['total_count'])*D(g['data']['purchase'])*f.get('price_factor',D(1)) for g in robots if g['data'].get('purchase') is not None)
    purchase_available=all(g['data'].get('purchase') is not None for g in robots)
    rental_available=bool(robots) and all(g['data'].get('rental_month') is not None for g in robots)
    scenarios=[dict(mode='baseline',name='Текущий процесс',**metrics(D(0),baseline,baseline,rate,horizon))]
    if purchase_available:
        chargers=sum(math.ceil(g['total_count']/int(f['robots_per_charger'])) for g in robots)
        capex=(robot_cost+chargers*f['charger_price']+sum(f[k] for k in ['infrastructure','software','integration','training']))*(1+f['contingency']/100)
        opex=common+energy+robot_cost*f['maintenance']/100+f['licenses']
        scenarios.append(dict(mode='purchase',name='Покупка',**metrics(capex,opex,baseline,rate,horizon)))
        parts={'Роботы':robot_cost,'Зарядные станции':chargers*f['charger_price'],'Инфраструктура':f['infrastructure'],'ПО':f['software'],'Интеграция и ПНР':f['integration'],'Обучение':f['training']}
        parts['Резерв бюджета']=sum(parts.values())*f['contingency']/100
        scenarios[-1]['capex_items']={k:money(v) for k,v in parts.items()}
        scenarios[-1]['opex_items']={k:money(v) for k,v in {'Персонал':payroll,'Сохраняемые прочие расходы':f['remaining_other_year'],'Электроэнергия':energy,'Сервис':robot_cost*f['maintenance']/100,'Лицензии':f['licenses']}.items()}
    if rental_available:
        rent=sum(D(g['total_count'])*D(g['data']['rental_month'])*12 for g in robots)
        # A rentable offer must explicitly include chargers, maintenance and software.
        scenarios.append(dict(mode='rental',name='Аренда',**metrics(f['rental_setup'],common+energy+rent,baseline,rate,horizon)))
        scenarios[-1]['capex_items']={'Разовый запуск':money(f['rental_setup'])}
        scenarios[-1]['opex_items']={k:money(v) for k,v in {'Персонал':payroll,'Сохраняемые прочие расходы':f['remaining_other_year'],'Электроэнергия':energy,'Аренда с зарядками, ПО и сервисом':rent}.items()}
    scenarios[0]['capex_items']={}
    scenarios[0]['opex_items']={'ФОТ':money(f['payroll_month']*12),'Прочие расходы':money(f['other_month']*12)}
    for s in scenarios:
        s['cost_per_operation']=money(D(s['opex'])/D(annual_volume))
        s['over_budget']=finance['budget'] is not None and D(s['capex'])>f['budget']
    return scenarios
