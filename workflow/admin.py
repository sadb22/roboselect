from django.contrib import admin
from .models import Supplier,EquipmentRevision,ImportBatch,CatalogNeed,Study,Procurement,DemoOrder

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display=['name','demo'];filter_horizontal=['members']

@admin.register(EquipmentRevision)
class RevisionAdmin(admin.ModelAdmin):
    list_display=['id','equipment','state','author','created_at']
    readonly_fields=['equipment','author','data','evidence','state','feedback','reviewer','created_at']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

@admin.register(CatalogNeed)
class NeedAdmin(admin.ModelAdmin):
    list_display=['owner','created_at','text'];readonly_fields=['owner','version','text','created_at']
    def has_add_permission(self,request):return False
