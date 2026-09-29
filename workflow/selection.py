from copy import deepcopy
from itertools import product
from math import ceil
from .domain import compatibility, num
from .simulation import cycle, simulate
from .finance import calculate, D

def evaluate(req,fin,assignments,revisions,with_limit=True,with_sensitivity=True):
    """Assignments identify shared physical fleets, never independent copies."""
    ops={o['id']:o for o in req['operations']};groups={};mapping={};errors=[];missing=[];preliminary=[]
    if len(assignments)!=len(ops) or {a['operation'] for a in assignments}!=set(ops):raise ValueError('Каждой операции нужен ровно один исполнитель')
    for a in assignments:
        op=ops[a['operation']];gid=str(a.get('group',op['id']))[:80]
        if not gid:raise ValueError('Укажите группу исполнителей')
        count=num(a['count'],'Число исполнителей',1,100,True)
        if a.get('kind')=='human':
            if not req['allow_human']:raise ValueError('Ручной этап требует согласия клиента')
            rate=num(a.get('rate'),'Производительность человека',.1,1000)
            salary=num(a.get('salary_month'),'ФОТ человека с начислениями',0,1e7)
            item=dict(id=gid,kind='human',count=count,rate=rate,salary_month=salary)
        else:
            revision=revisions.get(int(a['revision']))
            if not revision:raise ValueError('Недоступная версия оборудования')
            data=revision['data'];m,e=compatibility(data,op,req)
            if not m and cycle(data,op)>data['runtime_h']*3600:e.append('Одно задание превышает автономность робота')
            errors.extend(f'{op["name"]}: {x}' for x in e);missing.extend(f'{op["name"]}: {x}' for x in m)
            preliminary.extend(data.get('estimated_fields',[]))
            if revision.get('demo'):preliminary.append('Демонстрационные характеристики')
            item=dict(id=gid,kind='robot',count=count,total_count=count+ceil(count*.1),revision=int(a['revision']),
                data=data,supplier=revision['supplier'],demo=revision.get('demo',False))
        if gid in groups and item!=groups[gid]:raise ValueError('Общая группа должна иметь одинаковую модель, численность и параметры')
        groups[gid]=item;mapping[op['id']]=gid
    result=dict(model_version='workflow-2.1',status='blocked',errors=errors,missing=missing,preliminary=sorted(set(preliminary)),groups=list(groups.values()),scenarios=[])
    if errors or missing:return result
    for g in groups.values():
        if g['kind']=='robot' and g['data'].get('power_kw') is None:result['missing'].append('Для экономики требуется средняя мощность '+g['data']['model'])
    capacities=[]
    for gid,g in groups.items():
        work=sum(3600/g['rate'] if g['kind']=='human' else cycle(g['data'],o)*(1+g['data']['charge_h']/g['data']['runtime_h']) for o in ops.values() if mapping[o['id']]==gid)
        capacities.append(g['count']*3600/work)
        if g['kind']=='robot':g['chargers']=ceil(g['total_count']/fin['robots_per_charger'])
    steady_bound=min(capacities)
    sim=simulate(req,list(groups.values()),mapping);result['simulation']=sim
    sim['resource_bound']=round(steady_bound,2)
    if steady_bound+1e-6<req['peak_hour']:
        sim['feasible']=False;sim['reason']='Группы исполнителей не обеспечивают поток с учётом полного цикла зарядки'
    if not sim['feasible']:result['status']='incompatible';result['errors'].append(sim['reason']);return result
    if result['missing']:return result
    if float(fin.get('price_factor',1))!=1:preliminary.append('Ручная корректировка цены покупки')
    result['preliminary']=sorted(set(preliminary))
    result['status']='preliminary' if preliminary else 'confirmed'
    result['scenarios']=calculate(fin,list(groups.values()),req['daily_moves']*fin['days_year'])
    if len(result['scenarios'])==1:result['missing'].append('Нет подтверждённых цен покупки или условий аренды')
    else:
        best=min(result['scenarios'][1:],key=lambda s:D(s['tco']))
        saving=D(result['scenarios'][0]['tco'])-D(best['tco'])
        result['conclusion']=f"В этой конфигурации минимальные затраты у варианта «{best['name']}»: {best['tco']} руб. за {fin.get('horizon',5)} лет. Разница с текущим процессом: {saving:.2f} руб. "
        result['conclusion']+=('Модель показывает сокращение затрат. ' if saving>0 else 'Сокращение затрат относительно текущего процесса не подтверждено. ')
        result['conclusion']+='Результат требует верификации при обследовании объекта и согласования ТТХ и коммерческих условий.'
    if with_limit:
        lo=req['peak_hour'];hi=min(1000,max(lo*2,lo+10));checks=[dict(rate=lo,feasible=True)]
        high=simulate(req,list(groups.values()),mapping,hi)
        high['feasible']=high['feasible'] and hi<=steady_bound
        checks.append(dict(rate=hi,feasible=high['feasible']))
        if high['feasible']:lo=hi
        else:
            for _ in range(5):
                mid=(lo+hi)/2;ok=simulate(req,list(groups.values()),mapping,mid)['feasible'] and mid<=steady_bound;checks.append(dict(rate=round(mid,2),feasible=ok))
                if ok:lo=mid
                else:hi=mid
        result['load_limit']=dict(tested_stable=round(lo,2),upper_tested=round(hi,2),checks=checks,
            note='Наибольший устойчивый поток среди проверенных нагрузок; не гарантия работы реального склада.')
    if with_sensitivity:
        result['sensitivity']=[]
        for parameter,label in [('purchase','Стоимость оборудования'),('payroll_month','Стоимость труда'),('volume','Объём операций')]:
            for delta in [-20,20]:
                factor=1+delta/100;vr=deepcopy(req);vf=deepcopy(fin);vs=deepcopy(revisions)
                if parameter=='purchase':
                    for entry in vs.values():
                        if entry['data'].get('purchase') is not None:entry['data']['purchase']*=factor
                elif parameter=='payroll_month':vf['payroll_month']*=factor
                else:vr['peak_hour']*=factor;vr['daily_moves']*=factor
                va=deepcopy(assignments)
                if parameter=='payroll_month':
                    for a in va:
                        if a.get('kind')=='human':a['salary_month']=float(a['salary_month'])*factor
                varied=evaluate(vr,vf,va,vs,False,False)
                result['sensitivity'].append(dict(parameter=label,delta=delta,status=varied['status'],reason='; '.join(varied['errors']+varied['missing']),scenarios=varied['scenarios']))
    return result

def suggest(req,fin,revisions):
    choices=[];rejections=[]
    for op in req['operations']:
        candidates=[]
        for ident,r in revisions.items():
            m,e=compatibility(r['data'],op,req)
            if not m and not e:candidates.append(ident)
            else:rejections.append(dict(model=r['data']['model'],operation=op['name'],missing=m,errors=e))
        if not candidates:return [],rejections
        candidates.sort(key=lambda i:(bool(revisions[i].get('demo') or revisions[i]['data'].get('estimated_fields')),revisions[i]['data'].get('purchase') is None,revisions[i]['data'].get('purchase') or 0))
        choices.append(candidates[:3])
    results=[];seen=set()
    for combo in list(product(*choices))[:24]:
        for shared in [False,True]:
            durations={};asgn=[]
            for op,ident in zip(req['operations'],combo):
                gid=str(ident) if shared else op['id'];r=revisions[ident]['data']
                duration=cycle(r,op)*(1+r['charge_h']/r['runtime_h'])
                durations[gid]=durations.get(gid,0)+duration
                asgn.append(dict(operation=op['id'],group=gid,revision=ident,kind='robot'))
            for a in asgn:a['count']=max(1,ceil(req['peak_hour']*durations[a['group']]/3600/fin.get('utilization',.8)))
            if any(a['count']>100 for a in asgn):continue
            key=str(sorted((a['revision'],a['count'],tuple(sorted(b['operation'] for b in asgn if b['group']==a['group']))) for a in asgn))
            if key in seen:continue
            seen.add(key)
            result=evaluate(req,fin,asgn,revisions,False,False)
            if result['status'] in ['confirmed','preliminary'] and len(result['scenarios'])>1:results.append((asgn,result))
    results.sort(key=lambda x:(x[1]['status']!='confirmed',min(D(s['tco']) for s in x[1]['scenarios'] if s['mode']!='baseline')))
    selected=results[:8]
    for assignments,result in selected:
        checked=evaluate(req,fin,assignments,revisions,True)
        result.update(checked)
    return selected,rejections
