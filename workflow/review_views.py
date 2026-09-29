from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from .views import page
from .provenance_models import *
from .provenance import contract, select_value


def display_value(value):
    if not isinstance(value, dict):
        return 'Не распознано' if value is None else str(value)
    if 'min' in value or 'max' in value:
        text = f"{value.get('min', '…')} – {value.get('max', '…')}"
    else:
        raw = value.get('value')
        text = 'Не указано' if raw is None else ' × '.join(map(str, raw)) if isinstance(raw, list) else str(raw)
    text += (' ' + str(value['unit'])) if value.get('unit') else ''
    qualifier = {'maximum': 'максимум', 'minimum': 'минимум', 'approximate': 'приблизительно',
        'optional': 'опция', 'up_to': 'до', 'from': 'от'}.get(value.get('qualifier'), value.get('qualifier'))
    return text + (f' ({qualifier})' if qualifier else '')


def staff(fn):
    @wraps(fn)
    @login_required(login_url='/account/?role=admin')
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden('Доступно только администратору')
        return fn(request, *args, **kwargs)
    return wrapped


@staff
def catalogue(request):
    robots = Robot.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        robots = robots.filter(Q(name__icontains=q) | Q(manufacturer__icontains=q) | Q(key__icontains=q))
    state = request.GET.get('state', '')
    if state in ('unreviewed', 'accepted', 'rejected'):
        robots = robots.filter(field_observations__review_state=state).distinct()
    order = request.GET.get('sort', 'name')
    if order not in ('name', '-name', 'manufacturer', '-manufacturer'):
        order = 'name'
    return page(request, 'review_catalog', robots=Paginator(robots.order_by(order, 'pk'), 40).get_page(request.GET.get('page')),
        q=q, state=state, sort=order, issues=ReviewIssue.objects.filter(status='open').count())


@staff
def robot(request, id):
    robot = get_object_or_404(Robot, pk=id)
    fields = contract()
    observations = list(robot.field_observations.select_related('snapshot__source').order_by('field', '-id'))
    selected = {s.observation_id for s in FieldSelection.objects.filter(robot=robot, current=True)}
    for o in observations:
        o.label = fields.get(o.field, {}).get('label', o.field)
        o.display_value = display_value(o.normalized)
        o.source_url = o.snapshot.source.location if o.snapshot.source.location.startswith('https://') else ''
        o.is_current = o.pk in selected
    offers = list(RobotOffer.objects.filter(robot=robot))
    for offer in offers:
        terms = offer.terms
        low, high = terms.get('price_min'), terms.get('price_max')
        offer.price_label = 'По запросу' if low is None else str(low) + (' – ' + str(high) if high is not None and high != low else '') + ' ' + (terms.get('currency') or 'валюта не указана')
        offer.transaction_label = {'purchase':'Покупка','rental':'Аренда','service':'Услуга'}.get(terms.get('transaction_type'),'Вид сделки требует уточнения')
    decisions = list(FieldSelection.objects.filter(robot=robot).select_related('reviewer').order_by('-id'))
    for decision in decisions:
        decision.label = 'Выбрано' if decision.decision == 'accepted' else 'Отклонено'
        decision.field_label = fields.get(decision.field, {}).get('label', decision.field)
    return page(request, 'review_robot', robot=robot, observations=observations,
        issues=ReviewIssue.objects.filter(robot=robot), offers=offers,
        legacy_revision=robot.equipment.revisions.order_by('-id').first() if robot.equipment_id else None,
        decisions=decisions)


@staff
@require_POST
def review(request, id):
    observation = get_object_or_404(FieldObservation, pk=id)
    try:
        select_value(request.user, id, request.POST.get('decision'), request.POST.get('reason', ''))
    except ValueError as e:
        return page(request, 'error', error=str(e), retry=f'/workspace/robots/{observation.robot_id}/')
    return redirect('review_robot', id=observation.robot_id)


@staff
def snapshot(request, id):
    s = get_object_or_404(SourceSnapshot, pk=id)
    response = HttpResponse(bytes(s.content), content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="snapshot-{s.sha256}.bin"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@staff
def sources(request):
    error = ''
    if request.method == 'POST':
        from .web_import import add_web_source
        try:
            add_web_source(request.user, request.POST.get('url', '').strip())
            return redirect('review_sources')
        except ValueError as e:
            error = str(e)
    return page(request, 'review_sources', sources=Source.objects.order_by('-updated_at'), error=error)


@staff
@require_POST
def resolve_issue(request, id):
    from django.utils import timezone
    issue = get_object_or_404(ReviewIssue, pk=id)
    reason = request.POST.get('reason', '').strip()
    if not reason:
        return page(request, 'error', error='Опишите, как устранено замечание', retry='/workspace/robots/')
    if issue.status == 'open':
        issue.status = 'resolved'; issue.resolution = reason[:2000]
        issue.reviewer = request.user; issue.resolved_at = timezone.now(); issue.save()
    return redirect('review_robot', id=issue.robot_id) if issue.robot_id else redirect('review_catalog')


@staff
def create_card(request, id):
    from .forms import EquipmentForm
    from .catalog import submit
    from .models import Supplier
    from .provenance import selected_fields
    robot = get_object_or_404(Robot, pk=id)
    if robot.equipment_id:
        return redirect('revision', id=robot.equipment.revisions.order_by('-id').first().pk)
    observation = robot.field_observations.select_related('snapshot__source').first()
    initial = dict(manufacturer=robot.manufacturer, model=robot.name,
        source=observation.snapshot.source.location if observation else '', configuration='', **selected_fields(robot))
    form = EquipmentForm(request.POST if request.method == 'POST' else None, initial=initial)
    error = ''
    if request.method == 'POST' and form.is_valid():
        supplier = get_object_or_404(Supplier, pk=request.POST.get('supplier'))
        try:
            revision = submit(request.user, supplier, form.record(), evidence={'card': {'model_key': robot.key}},
                confirm=form.cleaned_data['confirm_identity'], robot=robot)
            return redirect('revision', id=revision.pk)
        except ValueError as e:
            error = str(e)
    return page(request, 'equipment_edit', form=form, suppliers=Supplier.objects.all(), old=None, error=error)
