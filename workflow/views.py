import csv
import io
import json
from copy import deepcopy
from datetime import timedelta
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse,JsonResponse,HttpResponseForbidden
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import *
from .forms import FinanceForm,EquipmentForm
from .domain import default_requirements,requirements,OPERATIONS,TECH
from .finance import defaults
from .catalog import submit,publish,import_csv,import_jsonl_zip,TEMPLATE
from .selection import evaluate,suggest

def page(request,template_name,**context):
    from django.middleware.csrf import get_token
    get_token(request)
    context['unread']=Notice.objects.filter(user=request.user,read=False).count() if request.user.is_authenticated else 0
    context['is_supplier']=request.user.is_authenticated and request.user.suppliers.exists()
    return render(request,'workflow/'+template_name+'.html',context)

def action(fn):
    @wraps(fn)
    @login_required(login_url='/account/')
    @require_POST
    def run(request,*args,**kwargs):
        try:return fn(request,*args,**kwargs)
        except (ValueError,KeyError,TypeError) as e:
            return page(request,'error',error=str(e),retry=request.path)
    return run

def catalog_snapshot():
    return {
      e.published_id:dict(data=e.published.data,supplier=e.supplier_id,supplier_name=e.supplier.name,
      equipment=str(e.pk),revision=e.published_id,demo=e.supplier.demo)
      for e in Equipment.objects.filter(published__isnull=False).select_related('published','supplier')}

def stale(config):
    return any(not Equipment.objects.filter(pk=x['equipment'],published_id=x['revision']).exists() for x in config.snapshot.values())

def home(request):
    rows=[]
    for ident,r in catalog_snapshot().items():
        missing=[label for k,(label,_,_) in TECH.items() if r['data'].get(k) is None]
        rows.append(dict(id=ident,**r,missing=missing))
    return page(request,'home',catalog=rows,operations=OPERATIONS)

def account(request):return page(request,'account')

@login_required(login_url='/account/')
def studies(request):
    return page(request,'studies',studies=Study.objects.filter(owner=request.user).prefetch_related('versions'),notices=Notice.objects.filter(user=request.user).order_by('-created_at')[:30])

@login_required(login_url='/account/')
def study_edit(request,id=None):
    study=get_object_or_404(Study,id=id,owner=request.user) if id else None
    old=study.versions.first() if study else None
    req=deepcopy(old.requirements if old else default_requirements());error=''
    form=FinanceForm(request.POST if request.method=='POST' else None,initial=old.finance if old else defaults())
    name=study.name if study else 'Склад: от стеллажа до автомобиля'
    if request.method=='POST':
        try:
            req=json.loads(request.POST['requirements']);name=request.POST.get('project_name','').strip()
            if not name or len(name)>160:raise ValueError('Название: от 1 до 160 символов')
            if not form.is_valid():raise ValueError('Проверьте выделенные финансовые поля')
            req,fin=requirements(req,form.cleaned_data)
            with transaction.atomic():
                if not study:study=Study.objects.create(owner=request.user,name=name)
                study=Study.objects.select_for_update().get(pk=study.pk)
                study.name=name;study.save(update_fields=['name'])
                latest=study.versions.first();version=StudyVersion.objects.create(study=study,number=latest.number+1 if latest else 1,requirements=req,finance=fin)
            return redirect('study',id=study.pk)
        except (ValueError,KeyError,TypeError) as e:error=str(e)
    return page(request,'study_edit',study=study,name=name,requirements=req,finance_form=form,operations=OPERATIONS,error=error)

@login_required(login_url='/account/')
def study_detail(request,id):
    study=get_object_or_404(Study,id=id,owner=request.user)
    version=get_object_or_404(study.versions,number=request.GET['version']) if request.GET.get('version') else study.versions.first()
    configs=list(version.configurations.all())
    configs.sort(key=lambda c:(c.result['status']!='confirmed',min([float(s['tco']) for s in c.result['scenarios'] if s['mode']!='baseline'] or [1e30])))
    for c in configs:c.stale=stale(c)
    return page(request,'study',study=study,version=version,configs=configs)

@action
def study_copy(request,id):
    old=get_object_or_404(Study,id=id,owner=request.user);v=old.versions.first()
    with transaction.atomic():
        new=Study.objects.create(owner=request.user,name=('Копия: '+old.name)[:160])
        StudyVersion.objects.create(study=new,number=1,requirements=v.requirements,finance=v.finance)
    return redirect('study',id=new.pk)

@action
def study_delete(request,id):
    study=get_object_or_404(Study,id=id,owner=request.user)
    if request.POST.get('confirm')!='delete':raise ValueError('Подтвердите удаление проекта и его расчётов')
    with transaction.atomic():
        procurements=Procurement.objects.filter(configuration__version__study=study)
        DemoOrder.objects.filter(procurement__in=procurements).delete()
        procurements.update(parent=None);procurements.delete();study.delete()
    return redirect('studies')

@login_required(login_url='/account/')
def study_template(request):
    stream=io.StringIO();writer=csv.writer(stream,delimiter=';');writer.writerow(['section','key','value'])
    for section,data in [('requirements',default_requirements()),('finance',defaults())]:
        for key,value in data.items():writer.writerow([section,key,json.dumps(value,ensure_ascii=False)])
    response=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8')
    response['Content-Disposition']='attachment; filename="warehouse-process.csv"';return response

@action
def study_upload(request):
    file=request.FILES.get('file')
    if not file or file.size>2_000_000:raise ValueError('Выберите CSV до 2 МБ по шаблону проекта')
    try:rows=list(csv.DictReader(io.StringIO(file.read().decode('utf-8-sig')),delimiter=';'))
    except UnicodeDecodeError:raise ValueError('CSV должен быть в кодировке UTF-8')
    if not rows or len(rows)>100:raise ValueError('Допускается от 1 до 100 строк')
    data={'requirements':{},'finance':{}};seen=set()
    for row in rows:
        section=row.get('section');key=row.get('key');value=row.get('value')
        if section not in data or not key or (section,key) in seen:raise ValueError('Некорректная или повторная строка шаблона')
        seen.add((section,key));data[section][key]=json.loads(value)
    req,fin=requirements(data['requirements'],data['finance'])
    with transaction.atomic():
        study=Study.objects.create(owner=request.user,name='Склад из файла')
        StudyVersion.objects.create(study=study,number=1,requirements=req,finance=fin)
    return redirect('study',id=study.pk)

@action
def generate(request,id):
    study=get_object_or_404(Study,id=id,owner=request.user);v=study.versions.first();snap=catalog_snapshot()
    results,rejections=suggest(v.requirements,v.finance,snap)
    for assignments,result in results:
        selected={str(a['revision']):snap[a['revision']] for a in assignments if a.get('revision')}
        if not v.configurations.filter(assignments=assignments,snapshot=selected).exists():
            Configuration.objects.create(version=v,assignments=assignments,snapshot=selected,result=result)
    if not results:return page(request,'no_results',study=study,version=v,rejections=rejections)
    messages.success(request,f'Рассчитано вариантов: {len(results)}. Сравнены раздельные и общие исполнители среди доступных кандидатов.')
    return redirect('study',id=study.pk)

@login_required(login_url='/account/')
def config_edit(request,id):
    version=get_object_or_404(StudyVersion,id=id,study__owner=request.user);error='';snap=catalog_snapshot();submitted={}
    if request.method=='POST':
        try:
            assignments=[]
            for op in version.requirements['operations']:
                key=op['id'];choice=request.POST.get(key+'_model','');group=request.POST.get(key+'_group',key)
                a=dict(operation=key,group=group,count=request.POST.get(key+'_count'))
                if choice=='human':a.update(kind='human',rate=request.POST.get(key+'_rate'),salary_month=request.POST.get(key+'_salary'))
                else:a.update(kind='robot',revision=int(choice))
                assignments.append(a)
            result=evaluate(version.requirements,version.finance,assignments,snap)
            selected={str(a['revision']):snap[a['revision']] for a in assignments if a.get('revision')}
            c=Configuration.objects.create(version=version,assignments=assignments,snapshot=selected,result=result)
            return redirect('configuration',id=c.pk)
        except (ValueError,TypeError,KeyError) as e:error=str(e);submitted=request.POST
    return page(request,'config_edit',version=version,catalog=snap,operations=version.requirements['operations'],error=error,submitted=submitted)

@login_required(login_url='/account/')
def config_detail(request,id):
    c=get_object_or_404(Configuration,id=id,version__study__owner=request.user)
    return page(request,'configuration',config=c,result=c.result,stale=stale(c))

@action
def recheck(request,id):
    old=get_object_or_404(Configuration,id=id,version__study__owner=request.user)
    snap=catalog_snapshot();assignments=deepcopy(old.assignments)
    for a in assignments:
        if a.get('revision'):
            eq=get_object_or_404(Equipment,id=old.snapshot[str(a['revision'])]['equipment'])
            if not eq.published_id:raise ValueError('Модель больше не опубликована')
            a['revision']=eq.published_id
    result=evaluate(old.version.requirements,old.version.finance,assignments,snap)
    selected={str(a['revision']):snap[a['revision']] for a in assignments if a.get('revision')}
    c=Configuration.objects.create(version=old.version,assignments=assignments,snapshot=selected,result=result)
    messages.success(request,f'Создан новый расчёт №{c.pk}. Предыдущий №{old.pk} сохранён. Сравните состав и итоговую стоимость.')
    return redirect('configuration',id=c.pk)

@login_required(login_url='/account/')
def export(request,id):
    c=get_object_or_404(Configuration,id=id,version__study__owner=request.user)
    format=request.GET.get('format','json')
    if format in ['pdf','xlsx']:
        from . import reports
        response=HttpResponse(getattr(reports,format)(c),content_type='application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition']=f'attachment; filename="roboscope-{id}.{format}"'
        return response
    data=dict(schema='roboscope-workflow-2',requirements=c.version.requirements,finance=c.version.finance,assignments=c.assignments,catalog=c.snapshot,result=c.result,version=c.version.number,calculated_at=c.created_at.isoformat(),demo_order_process=True)
    response=JsonResponse(data,json_dumps_params={'ensure_ascii':False,'indent':2});response['Content-Disposition']=f'attachment; filename="roboscope-{id}.json"';return response

@action
def need(request,id):
    v=get_object_or_404(StudyVersion,id=id,study__owner=request.user)
    text=request.POST.get('text','').strip()
    if not text:raise ValueError('Опишите недостающее оборудование')
    CatalogNeed.objects.create(owner=request.user,version=v,text=text[:3000]);messages.success(request,'Запрос сохранён для пополнения каталога. Текущий подбор не ожидает ответа.')
    return redirect('study',id=v.study_id)

@login_required(login_url='/account/')
def workspace(request):
    revisions=EquipmentRevision.objects.select_related('equipment__supplier','author').order_by('-created_at')
    if not request.user.is_staff:revisions=revisions.filter(equipment__supplier__members=request.user)
    return page(request,'workspace',revisions=revisions[:200],suppliers=Supplier.objects.all() if request.user.is_staff else request.user.suppliers.all(),batches=ImportBatch.objects.filter(owner=request.user).order_by('-created_at')[:10],needs=CatalogNeed.objects.all() if request.user.is_staff else [])

@login_required(login_url='/account/')
def equipment_edit(request,id=None):
    old=get_object_or_404(EquipmentRevision,id=id) if id else None
    suppliers=Supplier.objects.all() if request.user.is_staff else request.user.suppliers.all()
    if old and not suppliers.filter(pk=old.equipment.supplier_id).exists():return HttpResponseForbidden()
    form=EquipmentForm(request.POST if request.method=='POST' else None,initial=deepcopy(old.data) if old else {})
    error=''
    if request.method=='POST' and form.is_valid():
        try:
            supplier=get_object_or_404(suppliers,pk=request.POST.get('supplier'))
            if old and supplier.pk!=old.equipment.supplier_id:raise ValueError('Нельзя сменить владельца карточки через редактирование')
            submit(request.user,supplier,form.record(),old.evidence if old else {},form.cleaned_data['confirm_identity'])
            messages.success(request,'Версия отправлена на модерацию. Публикация прежней версии сохранена.');return redirect('workspace')
        except ValueError as e:error=str(e)
    return page(request,'equipment_edit',form=form,suppliers=suppliers,old=old,error=error)

@login_required(login_url='/account/')
def revision_detail(request,id):
    r=get_object_or_404(EquipmentRevision,id=id)
    if not request.user.is_staff and not r.equipment.supplier.members.filter(pk=request.user.pk).exists():return HttpResponseForbidden()
    return page(request,'revision',revision=r,evidence=json.dumps(r.evidence,ensure_ascii=False,indent=2),data=json.dumps(r.data,ensure_ascii=False,indent=2))

@action
def moderate(request,id):
    if not request.user.is_staff:return HttpResponseForbidden()
    publish(get_object_or_404(EquipmentRevision,id=id),request.user,request.POST['decision'],request.POST.get('feedback',''))
    return redirect('workspace')

@login_required(login_url='/account/')
def template(request):
    stream=io.StringIO();writer=csv.writer(stream,delimiter=';');writer.writerow(TEMPLATE)
    response=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8');response['Content-Disposition']='attachment; filename="equipment-template.csv"';return response

@action
def upload(request):
    suppliers=Supplier.objects.all() if request.user.is_staff else request.user.suppliers.all()
    supplier=get_object_or_404(suppliers,pk=request.POST.get('supplier'));file=request.FILES.get('file')
    if not file:raise ValueError('Выберите файл')
    if file.size>2_000_000:raise ValueError('CSV: не более 2 МБ')
    batch=import_csv(request.user,supplier,file.read(),file.name)
    return redirect('batch',id=batch.pk)

@action
def upload_parser(request):
    if not request.user.is_staff:return HttpResponseForbidden()
    file=request.FILES.get('file')
    if not file:raise ValueError('Выберите архив результатов парсера')
    if file.size>5_000_000:raise ValueError('ZIP: не более 5 МБ')
    batch=import_jsonl_zip(request.user,file.read())
    return redirect('batch',id=batch.pk)

@login_required(login_url='/account/')
def batch_detail(request,id):
    batch=get_object_or_404(ImportBatch,id=id)
    if not request.user.is_staff and batch.owner_id!=request.user.pk:return HttpResponseForbidden()
    return page(request,'batch',batch=batch)

@action
def send_request(request,id):
    c=get_object_or_404(Configuration,id=id,version__study__owner=request.user)
    if c.result['status'] not in ['confirmed','preliminary'] or stale(c):raise ValueError('Сначала выполните актуальную проверку конфигурации')
    mode=request.POST.get('mode')
    if mode not in [s['mode'] for s in c.result['scenarios'] if s['mode']!='baseline']:raise ValueError('Условия выбранного сценария отсутствуют')
    groups=[g for g in c.result['groups'] if g['kind']=='robot']
    if not groups:raise ValueError('В конфигурации нет оборудования для заказа')
    with transaction.atomic():
        # Serialise duplicate submissions for the same immutable calculation.
        Configuration.objects.select_for_update().get(pk=c.pk)
        existing=Procurement.objects.filter(owner=request.user,configuration=c,mode=mode).first()
        if existing:return redirect('request',id=existing.pk)
        procurement=Procurement.objects.create(owner=request.user,configuration=c,mode=mode)
        for supplier in set(g['supplier'] for g in groups):
            items=[dict(group=g['id'],revision=g['revision'],name=g['data']['model'],count=g['total_count'],price=g['data'].get('purchase' if mode=='purchase' else 'rental_month')) for g in groups if g['supplier']==supplier]
            part=SupplierRequest.objects.create(procurement=procurement,supplier_id=supplier,items=items)
            for member in part.supplier.members.all():Notice.objects.create(user=member,text='Новая заявка на согласование',url=f'/parts/{part.pk}/')
    return redirect('request',id=procurement.pk)

@login_required(login_url='/account/')
def requests_list(request):
    return page(request,'requests',outgoing=Procurement.objects.filter(owner=request.user).order_by('-created_at'),incoming=SupplierRequest.objects.filter(supplier__members=request.user).select_related('procurement','supplier').order_by('-id'))

def part_allowed(user,part):return part.procurement.owner_id==user.pk or part.supplier.members.filter(pk=user.pk).exists() or user.is_staff

@login_required(login_url='/account/')
def request_detail(request,id):
    p=get_object_or_404(Procurement,id=id,owner=request.user)
    parts=list(p.parts.select_related('supplier'))
    for part in parts:part.overdue=part.state=='waiting' and timezone.now()>p.created_at+timedelta(days=7)
    order=DemoOrder.objects.filter(procurement=p).first()
    for part in parts:
        part.contract_done=order and any(e['action']=='contract' and e['part']==part.pk for e in order.events)
        part.delivery_done=order and any(e['action']=='installed' and e['part']==part.pk for e in order.events)
    return page(request,'request',procurement=p,parts=parts,ready=all(x.state=='confirmed' for x in parts),order=order,demo_pending=bool(parts) and all(x.supplier.demo for x in parts) and any(x.state=='waiting' for x in parts))

@action
def demo_answers(request,id):
    with transaction.atomic():
        p=get_object_or_404(Procurement.objects.select_for_update(),id=id,owner=request.user)
        parts=list(p.parts.select_related('supplier'))
        if not parts or any(not x.supplier.demo for x in parts):return HttpResponseForbidden()
        for part in parts:
            if part.state=='waiting':
                part.state='confirmed';part.response='Учебный ответ: условия синтетического каталога подтверждены. Реальный поставщик не участвовал.'
                part.answered_at=timezone.now();part.save()
    messages.info(request,'Созданы учебные ответы для демонстрационных поставщиков.')
    return redirect('request',id=p.pk)

@login_required(login_url='/account/')
def part_detail(request,id):
    part=get_object_or_404(SupplierRequest,id=id)
    if not part_allowed(request.user,part):return HttpResponseForbidden()
    # Supplier sees only its equipment, operational requirements, not client payroll or competing quotes.
    return page(request,'part',part=part,requirements=part.procurement.configuration.version.requirements,
      can_answer=request.user.is_staff or part.supplier.members.filter(pk=request.user.pk).exists(),
      alternatives=Equipment.objects.filter(supplier=part.supplier,published__isnull=False).select_related('published'))

@action
def answer(request,id):
    with transaction.atomic():
        part=get_object_or_404(SupplierRequest.objects.select_for_update(),id=id)
        if not (request.user.is_staff or part.supplier.members.filter(pk=request.user.pk).exists()):return HttpResponseForbidden()
        if part.state!='waiting' or part.procurement.state!='waiting':raise ValueError('Заявка уже рассмотрена или заменена')
        choice=request.POST.get('decision');text=request.POST.get('text','').strip()
        if choice not in ['confirmed','declined','alternative'] or not text:raise ValueError('Выберите ответ и укажите условия')
        if choice=='alternative':
            part.alternative=get_object_or_404(EquipmentRevision,id=request.POST.get('alternative'),equipment__supplier=part.supplier,state='published')
            if part.alternative.equipment.published_id!=part.alternative_id:raise ValueError('Альтернативная версия устарела')
        part.state=choice;part.response=text[:5000];part.answered_at=timezone.now();part.save()
        Notice.objects.create(user=part.procurement.owner,text='Поставщик ответил на заявку',url=f'/requests/{part.procurement_id}/')
    return redirect('part',id=part.pk)

@action
def message(request,id):
    part=get_object_or_404(SupplierRequest,id=id)
    if not part_allowed(request.user,part):return HttpResponseForbidden()
    text=request.POST.get('text','').strip()
    if not text or len(text)>5000:raise ValueError('Сообщение: от 1 до 5000 символов')
    Message.objects.create(part=part,author=request.user,text=text);return redirect('part',id=part.pk)

@action
def alternative(request,id):
    part=get_object_or_404(SupplierRequest,id=id,procurement__owner=request.user,state='alternative')
    old=part.procurement.configuration;snap=catalog_snapshot();assignments=deepcopy(old.assignments)
    groupids={x['group'] for x in part.items}
    for a in assignments:
        if a['group'] in groupids:a['revision']=part.alternative_id
    result=evaluate(old.version.requirements,old.version.finance,assignments,snap)
    c=Configuration.objects.create(version=old.version,assignments=assignments,snapshot={str(a['revision']):snap[a['revision']] for a in assignments if a.get('revision')},result=result)
    messages.info(request,'Альтернатива проверена для всей цепочки. При выборе нового состава отправьте новую заявку; все поставщики подтвердят её заново.')
    return redirect('configuration',id=c.pk)

@action
def order_action(request,id):
    with transaction.atomic():
        p=get_object_or_404(Procurement.objects.select_for_update(),id=id,owner=request.user)
        if p.parts.exclude(state='confirmed').exists():raise ValueError('Нужно согласование всех поставщиков')
        action=request.POST.get('action');parts=set(p.parts.values_list('id',flat=True))
        order,created=DemoOrder.objects.get_or_create(procurement=p)
        if action=='create':return redirect('request',id=p.pk)
        events=order.events;partid=int(request.POST.get('part',0));now=timezone.now().isoformat()
        if action=='contract' and order.stage=='contracts' and partid in parts:
            if not any(e['action']=='contract' and e['part']==partid for e in events):events.append(dict(action=action,part=partid,date=now))
            if {e['part'] for e in events if e['action']=='contract'}==parts:order.stage='payment'
        elif action=='pay' and order.stage=='payment':order.stage='delivery';events.append(dict(action='pay',part=0,date=now))
        elif action=='installed' and order.stage=='delivery' and partid in parts:
            if not any(e['action']=='installed' and e['part']==partid for e in events):events.append(dict(action=action,part=partid,date=now))
            if {e['part'] for e in events if e['action']=='installed'}==parts:order.stage='acceptance'
        elif action=='accept' and order.stage=='acceptance':order.stage='complete';events.append(dict(action='accept',part=0,date=now))
        else:raise ValueError('Этот переход сейчас недоступен')
        order.events=events;order.save()
    return redirect('request',id=p.pk)
