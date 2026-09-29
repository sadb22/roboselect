from django.contrib import admin
from .models import Product, Normative, Project, ProjectVersion, SimulationRun
admin.site.site_header = 'RoboSelect · управление'
admin.site.site_title = 'RoboSelect'
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'company', 'subtype', 'status', 'price', 'updated_at']
    search_fields = ['name', 'company', 'description']
    list_filter = ['status', 'kind']
    readonly_fields = ['observations', 'updated_at']
@admin.register(Normative)
class NormativeAdmin(admin.ModelAdmin):
    list_display = ['label', 'value', 'source', 'updated_at']
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'revision', 'updated_at']
    readonly_fields = ['payload', 'result', 'revision', 'owner']
admin.site.register(SimulationRun)
