"""Bounded deterministic DES of a DAG, shared crews, finite buffers and corridors.

This is a process/queue model, not a geometric trajectory planner. All jobs visit
every DAG node; forks represent required parallel operations on the same job.
"""
import math
import simpy

def cycle(data,op):
    return 3600/data['rates'][op['code']]+2*op['distance_m']/data['speed_m_s']

def simulate(req,groups,assignment,rate=None,jobs=120):
    rate=rate or req['peak_hour'];env=simpy.Environment()
    batteries={g['id']:[0]*g['count'] for g in groups}
    chargers={g['id']:simpy.Resource(env,capacity=g.get('chargers',1)) for g in groups}
    idle={g['id']:simpy.Store(env,capacity=g['count']) for g in groups}
    for g in groups:
        for i in range(g['count']):idle[g['id']].put(i)
    stations={o['id']:simpy.Resource(env,capacity=o['stations']) for o in req['operations']}
    successors={o['id']:[n['id'] for n in req['operations'] if o['id'] in n['predecessors']] for o in req['operations']}
    buffers={o['id']:simpy.Container(env,capacity=max(1,o['buffer']),init=max(1,o['buffer'])) for o in req['operations']}
    # A zero-buffer handoff uses the downstream station admission semaphore.
    admissions={o['id']:simpy.Resource(env,capacity=o['stations']) for o in req['operations']}
    groupmap={g['id']:g for g in groups};routes={};geometry=[]
    for r in req['routes']:
        widths=[groupmap[assignment[o['id']]]['data']['width_m'] for o in req['operations'] if o.get('route')==r['id'] and groupmap[assignment[o['id']]]['kind']=='robot']
        lanes=max(1,int(r['width_m']/(max(widths,default=.6)+2*req['clearance_m'])))
        routes[r['id']]=simpy.Resource(env,capacity=lanes)
        geometry.append(dict(**r,lanes=lanes,warning='Разъезд ограничен: один робот на участке' if lanes==1 else 'Проезд допускает параллельное движение'))
    waits={o['id']:[] for o in req['operations']};ends=[];events=[];charged=0;blocked=0
    opmap={o['id']:o for o in req['operations']}
    def job(index):
        born=env.now;done={o['id']:env.event() for o in req['operations']};tokens={};handoffs={};claimed=set()
        def step(o):
            nonlocal charged,blocked
            yield simpy.AllOf(env,[done[x] for x in o['predecessors']])
            start_wait=env.now;gid=assignment[o['id']];g=groupmap[gid]
            # Consume the buffer slot only after this operation can take its executor.
            station=stations[o['id']].request();yield station
            worker=yield idle[gid].get()
            if o['predecessors']:
                if o['id'] in tokens:yield buffers[o['id']].put(1)
                if o['id'] in handoffs:admissions[o['id']].release(handoffs[o['id']])
            waits[o['id']].append(env.now-start_wait)
            seconds=3600/g['rate'] if g['kind']=='human' else cycle(g['data'],o)
            if g['kind']=='robot' and batteries[gid][worker]+seconds>g['data']['runtime_h']*3600:
                charged+=1
                with chargers[gid].request() as charge:
                    yield charge;charge_start=env.now;yield env.timeout(g['data']['charge_h']*3600)
                    events.append(dict(job=index,operation=o['id'],group=gid,worker=worker,phase='charge',start=round(charge_start,2),end=round(env.now,2)))
                batteries[gid][worker]=0
            started=env.now
            if o.get('route'):
                with routes[o['route']].request() as passage:
                    yield passage;started=env.now;yield env.timeout(seconds)
            else:yield env.timeout(seconds)
            if g['kind']=='robot':batteries[gid][worker]+=seconds
            events.append(dict(job=index,operation=o['id'],group=gid,worker=worker,phase='work',start=round(started,2),end=round(env.now,2)))
            # Release a shared executor before transfer to itself, preventing self-deadlock.
            shared=any(assignment[n]==gid for n in successors[o['id']])
            if shared:yield idle[gid].put(worker)
            before=env.now
            for nxt in successors[o['id']]:
                if nxt in claimed:continue
                claimed.add(nxt)
                if opmap[nxt]['buffer']:
                    yield buffers[nxt].get(1);tokens[nxt]=True
                else:
                    admission=admissions[nxt].request();yield admission;handoffs[nxt]=admission
            blocked+=env.now-before
            stations[o['id']].release(station)
            if not shared:yield idle[gid].put(worker)
            done[o['id']].succeed()
        for o in req['operations']:env.process(step(o))
        yield simpy.AllOf(env,list(done.values()));ends.append((index,born,env.now))
    def arrivals():
        for i in range(jobs):env.process(job(i));yield env.timeout(3600/rate)
    env.process(arrivals());env.run(until=(jobs+20)*3600/rate+86400)
    ordered=sorted(ends)
    if len(ordered)<jobs:return dict(feasible=False,reason='Блокировка цепочки или незавершённые задания',completed=len(ends),routes=geometry,events=events)
    # Compare later latencies to the warmed-up first half to detect growing queues.
    latencies=[end-born for _,born,end in ordered]
    a=sum(latencies[jobs//3:jobs//2])/len(latencies[jobs//3:jobs//2]);b=sum(latencies[-jobs//6:])/len(latencies[-jobs//6:])
    growth=max(0,b-a);stable=growth<=max(3600/rate, a*.1)
    completion_times=sorted(end for _,_,end in ordered)
    measured=(jobs//2-1)*3600/max(.001,completion_times[-1]-completion_times[jobs//2])
    stable=stable and measured>=rate*.98
    return dict(feasible=stable,completed=len(ends),throughput=round(measured,2),queue_growth_s=round(growth,2),
        max_latency_s=round(max(latencies),2),charging_events=charged,blocked_s=round(blocked,2),
        queues=[dict(operation=o['id'],name=o['name'],wait_s=round(sum(waits[o['id']])/len(waits[o['id']]),2)) for o in req['operations']],routes=geometry,events=events,
        reason='Поток устойчив в проверенном сценарии' if stable else 'Очередь растёт при заданном пиковом потоке',
        assumptions=['Детерминированные времена операций; все ветви процесса обязательны.',
         'Общий ресурс не получает дополнительное рабочее время при назначении на несколько операций.',
         'Проезды моделируются ограниченной ёмкостью, точные траектории и столкновения не рассчитываются.',
         'При передаче между операциями общего исполнителя груз ожидает в месте операции.'])
