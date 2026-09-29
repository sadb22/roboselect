import csv
import hashlib
import io
import json
import base64
from django.db import transaction
from .models import Equipment,EquipmentRevision,ImportBatch,ImportRow,Notice
from .domain import equipment_data,TECH,OPERATIONS

TEMPLATE=['manufacturer','model','sku','configuration','source','operations','purchase','rental_month','rental_scope',*TECH,'rates','confirm_identity']

def submit(user,supplier,data,evidence=None,confirm=False,robot=None):
    data=equipment_data(data)
    identity='|'.join(str(data.get(k,'')).casefold().strip() for k in ['manufacturer','model','sku','configuration'])
    if len(identity)>1000 or len(identity.encode('utf-8'))>2000:raise ValueError('Сократите наименование и комплектацию: идентификатор слишком длинный')
    with transaction.atomic():
        eq=Equipment.objects.select_for_update().filter(supplier=supplier,identity=identity).first()
        if eq and not confirm:raise ValueError('Возможный дубликат. Подтвердите обновление модели и комплектации.')
        if not eq:eq=Equipment.objects.create(supplier=supplier,identity=identity)
        revision=EquipmentRevision.objects.create(equipment=eq,author=user,data=data,evidence=evidence or {})
        if robot is not None:
            from .provenance_models import Robot
            if Robot.objects.filter(equipment=eq).exclude(pk=robot.pk).exists():
                raise ValueError('Эта карточка уже связана с другой записью робота; автоматическое объединение запрещено')
            if robot.equipment_id and robot.equipment_id!=eq.pk:
                raise ValueError('Модель уже связана с другой карточкой')
            robot.equipment=eq;robot.name=data['model'];robot.manufacturer=data['manufacturer'];robot.save()
        elif not (evidence or {}).get('card'):
            from .provenance_models import Robot
            Robot.objects.get_or_create(equipment=eq,defaults={'key':'equipment-'+str(eq.pk),'name':data['model'],'manufacturer':data['manufacturer']})
        return revision

def publish(revision,user,state,feedback):
    if not user.is_staff:raise PermissionError('Требуются права администратора')
    if state not in ['published','returned']:raise ValueError('Неизвестное решение')
    if state=='returned' and not feedback.strip():raise ValueError('Укажите замечания автору')
    with transaction.atomic():
        rev=EquipmentRevision.objects.select_for_update().get(pk=revision.pk)
        if rev.state!='pending':raise ValueError('Версия уже рассмотрена')
        if state=='published':
            if rev.evidence.get('card', {}).get('model_key'):
                from .provenance import selected_fields
                from .provenance_models import Robot
                robot=Robot.objects.filter(equipment=rev.equipment).first()
                if robot:
                    for field in ('payload_kg','width_m','length_m','min_aisle_m','runtime_h'):
                        rev.data[field]=None
                    rev.data.update(selected_fields(robot))
                    from .provenance import contract
                    from .provenance_models import FieldSelection
                    fields=contract()
                    rev.data['verified_fields']=[{'label':fields.get(s.field,{}).get('label',s.field),
                        'value':s.observation.normalized, 'source':s.observation.snapshot.source.location,
                        'acquired_at':s.observation.snapshot.acquired_at.isoformat() if s.observation.snapshot.acquired_at else None}
                        for s in FieldSelection.objects.filter(robot=robot,current=True).select_related('observation__snapshot__source')]
            equipment_data(rev.data)
        rev.state=state;rev.reviewer=user;rev.feedback=feedback;rev.save()
        if state=='published':
            eq=Equipment.objects.select_for_update().get(pk=rev.equipment_id);eq.published=rev;eq.save()
            # Old immutable calculation snapshots remain intact.
            from .models import Configuration
            owners=set()
            for config in Configuration.objects.select_related('version__study'):
                if any(str(r.get('equipment'))==str(eq.pk) for r in config.snapshot.values()):owners.add(config.version.study.owner_id)
            for owner in owners:Notice.objects.create(user_id=owner,text='Каталог обновлён: '+rev.data['model']+'. Для нового расчёта нажмите «Актуализировать».',url='/studies/')
        Notice.objects.create(user=rev.author,text=f'Карточка {rev.data["model"]}: {state}. {feedback}'[:500],url='/workspace/')

def import_csv(user,supplier,content,filename):
    if len(content)>2_000_000:raise ValueError('Максимум 2 МБ')
    try:text=content.decode('utf-8-sig')
    except UnicodeDecodeError:raise ValueError('Сохраните CSV в кодировке UTF-8')
    reader=csv.DictReader(io.StringIO(text),delimiter=';')
    if not reader.fieldnames or not set(TEMPLATE)<=set(reader.fieldnames):raise ValueError('Нужен единый CSV-шаблон UTF-8 с разделителем ;')
    rows=list(reader)
    if len(rows)>500:raise ValueError('Не более 500 строк')
    digest=hashlib.sha256(str(supplier.pk).encode()+b':' +content).hexdigest()
    existing=ImportBatch.objects.filter(owner=user,digest=digest).first()
    if existing:return existing
    batch=ImportBatch.objects.create(owner=user,filename=filename[:200],digest=digest)
    for i,raw in enumerate(rows,2):
        error=''
        try:
            d=dict(raw);d['operations']=[x.strip() for x in d['operations'].split(',') if x.strip()]
            d['rates']=json.loads(d['rates'] or '{}')
            submit(user,supplier,d,dict(import_row=i,source_row=raw),confirm=d['confirm_identity'].lower()=='true')
        except (ValueError,TypeError,KeyError) as e:error=str(e)
        ImportRow.objects.create(batch=batch,number=i,raw=raw,error=error)
    return batch

@transaction.atomic
def import_parser(user,folder):
    """Import trusted offline parser output; do not infer loaded speed from max speed."""
    from .models import Supplier
    if not user.is_staff:raise PermissionError('Требуются права администратора')
    from pathlib import Path
    folder=Path(folder)
    def read(name):return [json.loads(s) for s in (folder/(name+'.jsonl')).read_text(encoding='utf-8').splitlines() if s.strip()]
    cards=read('cards');obs=read('observations');offers=read('offers');links=read('scenario_links');snapshots=read('snapshots');issues=read('issues')
    from .provenance import ingest
    robots=ingest(folder)
    digest=hashlib.sha256(json.dumps([cards,obs,offers,links,issues,[(s['snapshot_id'],s['sha256'],s['parser_version']) for s in snapshots]],sort_keys=True).encode()).hexdigest()
    previous=ImportBatch.objects.filter(digest=digest).first()
    if previous:return previous
    batch=ImportBatch.objects.create(owner=user,filename='parser-3.3.0',digest=digest)
    # No implicit merge of a previous import or of legacy catalogue identities.
    fields={'payload':'payload_kg','width':'width_m','length':'length_m','min_aisle_width':'min_aisle_m','runtime':'runtime_h'}
    for i,c in enumerate(cards,1):
        supplier,_=Supplier.objects.get_or_create(name='Требует назначения поставщика: '+(c.get('manufacturer') or 'Не установлен'))
        d=dict(manufacturer=c['manufacturer'],model=c['model'],configuration='Уточнить комплектацию',source='Офлайн-парсер; дата актуальности не подтверждена',operations=[l['scenario_code'] for l in links if l['model_key']==c['model_key'] and l['scenario_code'] in OPERATIONS],rates={})
        for old,new in fields.items():
            item=c['fields'].get(old,{})
            if 'value' in item and item.get('qualifier') is None:d[new]=item['value']/1000 if new.endswith('_m') else item['value']
        selected_obs=[o for o in obs if o['observation_id'] in c['observation_ids']]
        selected_snapshots=[s for s in snapshots if s['snapshot_id'] in {o['snapshot_id'] for o in selected_obs}]
        source_files=[]
        for s in selected_snapshots:
            source=(folder/s['stored_path'].replace('\\','/')).resolve()
            if not source.is_relative_to(folder.resolve()) or not source.is_file():raise ValueError('Отсутствует безопасный снимок источника')
            raw=source.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=s['sha256']:raise ValueError('Контрольная сумма снимка не совпадает')
            source_files.append(dict(path=s['stored_path'],sha256=s['sha256'],bytes_base64=base64.b64encode(raw).decode()))
        evidence=dict(card=c,observations=selected_obs,offers=[o for o in offers if o['model_key']==c['model_key']],issues=[o for o in issues if o.get('model_key')==c['model_key']],snapshots=selected_snapshots,source_files=source_files)
        # Unknown rates/operating conditions/prices are intentionally left empty.
        try:
            robot=robots[c['model_key']]
            # Stable parser model keys refer to the same draft, not a new supplier/model.
            if robot.equipment_id:
                rev=EquipmentRevision.objects.create(equipment=robot.equipment,author=user,data=d,evidence=evidence)
            else:
                rev=submit(user,supplier,d,evidence)
                robot.equipment=rev.equipment;robot.save(update_fields=['equipment'])
            error=''
        except ValueError as e:error=str(e)
        ImportRow.objects.create(batch=batch,number=i,raw=evidence,error=error)
    # Preserve all raw CSV rows, including duplicate IDs, without publishing them.
    for i,row in enumerate(read('catalog_rows'),len(cards)+1):ImportRow.objects.create(batch=batch,number=i,raw=row,error='Исходный каталог: требуется сопоставление модели, комплектации и ТТХ')
    return batch

def import_jsonl_zip(user,content):
    import zipfile,tempfile,subprocess,sys
    from pathlib import Path,PurePosixPath
    from django.conf import settings
    if len(content)>5_000_000:raise ValueError('Архив: не более 5 МБ')
    try:archive=zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:raise ValueError('Нужен ZIP с результатом парсера')
    members=archive.infolist()
    if len(members)>1000 or sum(m.file_size for m in members)>20_000_000:raise ValueError('Превышен размер распакованных данных: 20 МБ / 1000 файлов')
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        for member in members:
            if member.flag_bits & 1:raise ValueError('Архивы с паролем не поддерживаются')
            path=PurePosixPath(member.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in member.filename:raise ValueError('Недопустимый путь в архиве')
            if member.is_dir():continue
            # Never execute uploaded code. Only JSONL metadata and snapshots are copied.
            if path.suffix not in ['.jsonl','.txt','.html','.csv','.json','.bin']:continue
            target=root.joinpath(*path.parts);target.parent.mkdir(parents=True,exist_ok=True)
            try:target.write_bytes(archive.read(member))
            except (zipfile.BadZipFile,RuntimeError,NotImplementedError):raise ValueError('Повреждённый или неподдерживаемый архив')
        candidates=list(root.rglob('cards.jsonl'))
        if len(candidates)!=1:raise ValueError('В архиве должен быть один cards.jsonl')
        folder=candidates[0].parent
        required=['observations','offers','issues','snapshots','scenario_links','catalog_rows']
        if any(not (folder/(n+'.jsonl')).exists() for n in required):raise ValueError('Не хватает обязательных JSONL файлов')
        try:result=subprocess.run([sys.executable,str(settings.BASE_DIR/'vendor/robot_parser/validate_export.py'),str(folder)],capture_output=True,timeout=20,text=True)
        except subprocess.TimeoutExpired:raise ValueError('Проверка архива превысила 20 секунд. Уменьшите объём выгрузки.')
        if result.returncode:raise ValueError('Контракт JSONL не прошёл проверку. Проверьте версии, обязательные поля и ссылки на источники.')
        with transaction.atomic():return import_parser(user,folder)
