from django.contrib import admin
from django.urls import path, include
from core import views as v
urlpatterns=[
 path('',include('workflow.urls')),path('legacy/',v.index),path('admin/',admin.site.urls),path('health/',v.health),
 path('api/bootstrap/',v.bootstrap),path('api/catalog/',v.catalog),path('api/calculate/',v.calculate_view),
 path('api/auth/<str:action>/',v.auth_view),path('api/projects/',v.projects),
 path('api/projects/<uuid:id>/',v.project_detail),path('api/projects/<uuid:id>/copy/',v.project_copy),
 path('api/simulations/',v.simulation_start),path('api/simulations/<uuid:id>/',v.simulation_status),
 path('api/export/<str:format>/',v.export_report),path('api/template/',v.input_template),
 path('api/import/',v.import_inputs),path('api/catalog/import/',v.catalog_upload),path('api/schema/',v.openapi),
 path('api/worker-health/',v.worker_health)]
