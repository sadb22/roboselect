import uuid
from django.conf import settings
from django.db import models

class Supplier(models.Model):
    name = models.CharField(max_length=200)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='suppliers')
    demo = models.BooleanField(default=False)
    def __str__(self): return self.name

class ImportBatch(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    filename = models.CharField(max_length=200)
    digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

class ImportRow(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='rows')
    number = models.PositiveIntegerField()
    raw = models.JSONField(default=dict)
    error = models.TextField(blank=True)

class Equipment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT)
    identity = models.CharField(max_length=1000)
    published = models.ForeignKey('EquipmentRevision', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    class Meta:
        constraints=[models.UniqueConstraint(fields=['supplier','identity'],name='equipment_identity')]

class EquipmentRevision(models.Model):
    equipment = models.ForeignKey(Equipment,on_delete=models.CASCADE,related_name='revisions')
    author = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    data = models.JSONField(default=dict)
    evidence = models.JSONField(default=dict)
    state = models.CharField(max_length=20,default='pending')
    feedback = models.TextField(blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.PROTECT,related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

class Study(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)

class StudyVersion(models.Model):
    study = models.ForeignKey(Study,on_delete=models.CASCADE,related_name='versions')
    number = models.PositiveIntegerField()
    requirements = models.JSONField()
    finance = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-number']
        constraints=[models.UniqueConstraint(fields=['study','number'],name='study_version_number')]

class Configuration(models.Model):
    version = models.ForeignKey(StudyVersion,on_delete=models.CASCADE,related_name='configurations')
    assignments = models.JSONField()
    snapshot = models.JSONField()
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

class Procurement(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    configuration = models.ForeignKey(Configuration,on_delete=models.PROTECT)
    mode = models.CharField(max_length=20)
    parent = models.ForeignKey('self',null=True,blank=True,on_delete=models.PROTECT)
    state = models.CharField(max_length=20,default='waiting')
    created_at = models.DateTimeField(auto_now_add=True)

class SupplierRequest(models.Model):
    procurement = models.ForeignKey(Procurement,on_delete=models.CASCADE,related_name='parts')
    supplier = models.ForeignKey(Supplier,on_delete=models.PROTECT)
    items = models.JSONField()
    state = models.CharField(max_length=20,default='waiting')
    response = models.TextField(blank=True)
    alternative = models.ForeignKey(EquipmentRevision,null=True,blank=True,on_delete=models.PROTECT)
    answered_at = models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['procurement','supplier'],name='request_supplier')]

class Message(models.Model):
    part = models.ForeignKey(SupplierRequest,on_delete=models.CASCADE,related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class Notice(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    text = models.CharField(max_length=500)
    url = models.CharField(max_length=300,default='/')
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class DemoOrder(models.Model):
    procurement = models.OneToOneField(Procurement,on_delete=models.PROTECT,related_name='order')
    stage = models.CharField(max_length=20,default='contracts')
    events = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

class CatalogNeed(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    version = models.ForeignKey(StudyVersion,on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
