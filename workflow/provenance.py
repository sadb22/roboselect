import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from .provenance_models import *


def contract():
    return {f['key']: f for f in json.loads((settings.BASE_DIR / 'vendor/robot_parser/fields.json').read_text(encoding='utf-8'))['fields']}


def read_export(folder, name):
    path = Path(folder) / (name + '.jsonl')
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []


def timestamp(value):
    if not value:
        return None
    value = parse_datetime(value)
    return timezone.make_aware(value) if value and timezone.is_naive(value) else value


@transaction.atomic
def ingest(folder):
    """Immutable IDs, verified bytes, no writes to selected values."""
    folder = Path(folder).resolve()
    robots = {}
    for card in sorted(read_export(folder, 'cards'), key=lambda c: c['model_key']):
        robots[card['model_key']], _ = Robot.objects.get_or_create(key=card['model_key'], defaults={
            'name': card['model'], 'manufacturer': card.get('manufacturer') or ''})
        Robot.objects.select_for_update().get(pk=robots[card['model_key']].pk)
    snapshots = {}
    for s in read_export(folder, 'snapshots'):
        path = (folder / s['stored_path'].replace('\\', '/')).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError('Отсутствует безопасный снимок источника')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != s['sha256']:
            raise ValueError('Контрольная сумма снимка не совпадает')
        source, _ = Source.objects.get_or_create(key=s['source_id'], defaults={
            'location': s['url_or_filename'], 'site': urlparse(s['url_or_filename']).hostname or '', 'kind': s['source_type']})
        snapshot, _ = SourceSnapshot.objects.get_or_create(source=source, sha256=s['sha256'], parser_version=s['parser_version'], defaults={
            'key': s['snapshot_id'] + '-' + hashlib.sha256(s['parser_version'].encode()).hexdigest()[:12],
            'content': raw, 'stored_path': s['stored_path'],
            'acquired_at': timestamp(s.get('acquired_at')),
            'processed_at': timestamp(s.get('processed_at'))})
        snapshots[s['snapshot_id']] = snapshot
        source.status = 'review'; source.error = ''; source.save()
    for o in read_export(folder, 'observations'):
        if o['model_key'] not in robots:
            raise ValueError('Наблюдение ссылается на неизвестную модель')
        observation, created = FieldObservation.objects.get_or_create(key=o['observation_id'], defaults={
            'robot': robots[o['model_key']], 'snapshot': snapshots[o['snapshot_id']], 'field': o['field'],
            'raw_text': str(o.get('raw_label', '')) + ': ' + str(o.get('raw_value', '')),
            'normalized': o.get('normalized'), 'extraction_state': o['extraction_state'], 'evidence': o})
        if created:
            selected = FieldSelection.objects.filter(robot=observation.robot, field=observation.field, current=True).select_related('observation').first()
            if selected and selected.observation.normalized != observation.normalized:
                ReviewIssue.objects.get_or_create(key='conflict-' + o['observation_id'], defaults={
                    'robot': observation.robot, 'snapshot': observation.snapshot, 'field': observation.field,
                    'reason': 'Новое наблюдение отличается от выбранного значения', 'evidence': o})
    for o in read_export(folder, 'offers'):
        if o['model_key'] in robots:
            RobotOffer.objects.get_or_create(key=o['offer_id'], defaults={'robot': robots[o['model_key']],
                'snapshot': snapshots[o['snapshot_id']], 'supplier': o.get('supplier') or '', 'terms': o})
    for issue in read_export(folder, 'issues'):
        ReviewIssue.objects.get_or_create(key=issue['issue_id'], defaults={
            'robot': robots.get(issue.get('model_key')), 'snapshot': snapshots.get(issue.get('snapshot_id')),
            'field': issue.get('field', ''), 'reason': issue.get('reason', issue.get('kind', 'Проверка')),
            'evidence': issue, 'status': issue.get('lifecycle', 'open')})
    for label in read_export(folder, 'unknown_labels'):
        snapshot = snapshots.get(label.get('snapshot_id'))
        if snapshot:
            robot = FieldObservation.objects.filter(snapshot=snapshot).select_related('robot').first()
            key = hashlib.sha256(json.dumps(label, sort_keys=True).encode()).hexdigest()
            ReviewIssue.objects.get_or_create(key='label-' + key, defaults={'robot': robot.robot if robot else None,
                'snapshot': snapshot, 'reason': 'Неизвестная метка: ' + label.get('label', ''), 'evidence': label})
    for s in read_export(folder, 'scenarios'):
        Scenario.objects.get_or_create(code=s['code'], defaults={'name': s['name'], 'category': s.get('category', '')})
    for link in read_export(folder, 'scenario_links'):
        scenario, _ = Scenario.objects.get_or_create(code=link['scenario_code'], defaults={'name': link['scenario_code']})
        RobotScenario.objects.get_or_create(robot=robots[link['model_key']], scenario=scenario, defaults={'evidence': link, 'status': 'unreviewed'})
    return robots


@transaction.atomic
def select_value(user, observation_id, decision, reason=''):
    if not user.is_staff:
        raise PermissionError('Только администратор может проверять значения')
    observation = FieldObservation.objects.select_related('snapshot').get(pk=observation_id)
    robot = Robot.objects.select_for_update().get(pk=observation.robot_id)
    if decision not in ('accepted', 'rejected'):
        raise ValueError('Неизвестное решение')
    if decision == 'rejected' and not reason.strip():
        raise ValueError('Укажите причину отклонения')
    if decision == 'accepted' and (observation.extraction_state != 'parsed' or not observation.normalized):
        raise ValueError('Не удалось нормализовать значение; исправьте источник и повторите импорт')
    previous = FieldSelection.objects.filter(robot=robot, field=observation.field, current=True).first()
    if previous and previous.observation_id == observation.pk:
        raise ValueError('Это значение уже выбрано. Сначала выберите замену.')
    if decision == 'accepted':
        FieldSelection.objects.filter(robot=robot, field=observation.field, current=True).update(current=False)
        meta = contract().get(observation.field)
        if not meta:
            raise ValueError('Поле отсутствует в словаре парсера')
        scope = meta.get('scope', '')
        spec_class = CleaningSpec if scope == 'Уборка' else WarehouseSpec if scope == 'Склад' else None
        if spec_class:
            spec, _ = spec_class.objects.get_or_create(robot=robot)
            spec.values[observation.field] = observation.normalized; spec.save()
        else:
            robot.general[observation.field] = observation.normalized; robot.save()
    observation.review_state = decision; observation.save(update_fields=['review_state'])
    return FieldSelection.objects.create(robot=robot, field=observation.field, observation=observation,
        reviewer=user, decision=decision, reason=reason, current=decision == 'accepted')


def selected_fields(robot):
    """Only explicit reviewer selections may enter a new workflow revision."""
    mapping = {'payload': ('payload_kg', 1), 'width': ('width_m', 1000),
        'length': ('length_m', 1000), 'min_aisle_width': ('min_aisle_m', 1000), 'runtime': ('runtime_h', 1)}
    result = {}
    for selection in FieldSelection.objects.filter(robot=robot, current=True).select_related('observation'):
        value = selection.observation.normalized
        if selection.field in mapping and isinstance(value, dict) and value.get('qualifier') is None and isinstance(value.get('value'), (int, float)):
            key, divisor = mapping[selection.field]
            result[key] = value['value'] / divisor
    return result
