"""Normalized catalogue; legacy revisions remain immutable calculation snapshots."""
from django.conf import settings
from django.db import models

REVIEW_STATES = [('unreviewed', 'Ожидает проверки'), ('accepted', 'Подтверждено'), ('rejected', 'Отклонено')]


class Robot(models.Model):
    key = models.CharField(max_length=250, unique=True)
    manufacturer = models.CharField(max_length=300, blank=True)
    name = models.CharField(max_length=300)
    general = models.JSONField(default=dict)
    equipment = models.OneToOneField('workflow.Equipment', null=True, blank=True, on_delete=models.PROTECT)
    legacy_product = models.OneToOneField('core.Product', null=True, blank=True, on_delete=models.PROTECT)
    class Meta:
        db_table = 'robot'
        ordering = ['name']


class WarehouseSpec(models.Model):
    robot = models.OneToOneField(Robot, primary_key=True, on_delete=models.PROTECT)
    values = models.JSONField(default=dict)
    class Meta:
        db_table = 'warehouse_spec'


class CleaningSpec(models.Model):
    robot = models.OneToOneField(Robot, primary_key=True, on_delete=models.PROTECT)
    values = models.JSONField(default=dict)
    class Meta:
        db_table = 'cleaning_spec'


class Scenario(models.Model):
    code = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=300)
    category = models.CharField(max_length=50, blank=True)
    class Meta:
        db_table = 'scenario'


class RobotScenario(models.Model):
    robot = models.ForeignKey(Robot, on_delete=models.PROTECT)
    scenario = models.ForeignKey(Scenario, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default='unreviewed')
    evidence = models.JSONField(default=dict)
    class Meta:
        db_table = 'robot_scenario'
        constraints = [models.UniqueConstraint(fields=['robot', 'scenario'], name='robot_scenario_unique')]


class Source(models.Model):
    key = models.CharField(max_length=250, unique=True)
    location = models.TextField()
    site = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=30)
    status = models.CharField(max_length=30, default='pending', choices=[('pending','Ожидает обработки'),('processing','Обрабатывается'),('review','На проверке'),('error','Ошибка')])
    error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = 'source'


class SourceSnapshot(models.Model):
    key = models.CharField(max_length=100, unique=True)
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name='snapshots')
    sha256 = models.CharField(max_length=64, db_index=True)
    stored_path = models.TextField()
    content = models.BinaryField()
    acquired_at = models.DateTimeField(null=True)
    processed_at = models.DateTimeField(null=True)
    parser_version = models.CharField(max_length=160)
    class Meta:
        db_table = 'source_snapshot'
        constraints = [models.UniqueConstraint(fields=['source', 'sha256', 'parser_version'], name='source_version_unique')]


class FieldObservation(models.Model):
    key = models.CharField(max_length=100, unique=True)
    robot = models.ForeignKey(Robot, on_delete=models.PROTECT, related_name='field_observations')
    snapshot = models.ForeignKey(SourceSnapshot, on_delete=models.PROTECT)
    field = models.CharField(max_length=100)
    raw_text = models.TextField()
    normalized = models.JSONField(null=True)
    evidence = models.JSONField(default=dict)
    extraction_state = models.CharField(max_length=30)
    review_state = models.CharField(max_length=20, default='unreviewed', choices=REVIEW_STATES)
    class Meta:
        db_table = 'field_observation'
        indexes = [models.Index(fields=['robot', 'field', 'review_state'])]


class FieldSelection(models.Model):
    robot = models.ForeignKey(Robot, on_delete=models.PROTECT)
    field = models.CharField(max_length=100)
    observation = models.ForeignKey(FieldObservation, on_delete=models.PROTECT)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20)
    reason = models.TextField(blank=True)
    selected_at = models.DateTimeField(auto_now_add=True)
    current = models.BooleanField(default=False)
    class Meta:
        db_table = 'field_selection'
        constraints = [models.UniqueConstraint(fields=['robot', 'field'], condition=models.Q(current=True), name='one_current_field_selection')]


class RobotOffer(models.Model):
    key = models.CharField(max_length=100, unique=True)
    robot = models.ForeignKey(Robot, on_delete=models.PROTECT)
    snapshot = models.ForeignKey(SourceSnapshot, on_delete=models.PROTECT)
    supplier = models.CharField(max_length=300, blank=True)
    terms = models.JSONField(default=dict)
    review_state = models.CharField(max_length=20, default='unreviewed')
    class Meta:
        db_table = 'robot_offer'


class ReviewIssue(models.Model):
    key = models.CharField(max_length=100, unique=True)
    robot = models.ForeignKey(Robot, null=True, on_delete=models.PROTECT)
    snapshot = models.ForeignKey(SourceSnapshot, null=True, on_delete=models.PROTECT)
    field = models.CharField(max_length=100, blank=True)
    reason = models.TextField()
    evidence = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default='open', db_index=True)
    resolution = models.TextField(blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    resolved_at = models.DateTimeField(null=True)
    class Meta:
        db_table = 'review_issue'
