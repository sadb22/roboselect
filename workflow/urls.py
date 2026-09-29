from django.urls import path
from . import views as v
from . import review_views as r
urlpatterns=[path('enter/<str:role>/',v.enter_role,name='enter_role'),path('workspace/robots/<int:id>/card/',r.create_card,name='review_create_card'),path('workspace/issues/<int:id>/resolve/',r.resolve_issue,name='review_issue_resolve'),path('workspace/robots/',r.catalogue,name='review_catalog'),path('workspace/robots/<int:id>/',r.robot,name='review_robot'),path('workspace/observations/<int:id>/',r.review,name='review_observation'),path('workspace/snapshots/<int:id>/',r.snapshot,name='review_snapshot'),path('workspace/sources/',r.sources,name='review_sources'),path('',v.home,name='home'),path('user/',v.user_home,name='user_home'),path('account/',v.account,name='account'),
 path('studies/',v.studies,name='studies'),path('studies/new/',v.study_edit,name='study_new'),path('studies/template/',v.study_template,name='study_template'),path('studies/upload/',v.study_upload,name='study_upload'),
 path('studies/<uuid:id>/copy/',v.study_copy,name='study_copy'),path('studies/<uuid:id>/delete/',v.study_delete,name='study_delete'),
 path('studies/<uuid:id>/',v.study_detail,name='study'),path('studies/<uuid:id>/edit/',v.study_edit,name='study_edit'),
 path('studies/<uuid:id>/generate/',v.generate,name='generate'),path('versions/<int:id>/configure/',v.config_edit,name='config_edit'),
 path('versions/<int:id>/need/',v.need,name='need'),path('configurations/<int:id>/',v.config_detail,name='configuration'),
 path('configurations/<int:id>/recheck/',v.recheck,name='recheck'),path('configurations/<int:id>/export/',v.export,name='workflow_export'),
 path('configurations/<int:id>/request/',v.send_request,name='send_request'),
 path('workspace/',v.workspace,name='workspace'),path('equipment/new/',v.equipment_edit,name='equipment_new'),
 path('equipment/<int:id>/edit/',v.equipment_edit,name='equipment_edit'),path('equipment/<int:id>/',v.revision_detail,name='revision'),
 path('equipment/<int:id>/moderate/',v.moderate,name='moderate'),path('workspace/template/',v.template,name='catalog_template'),
 path('workspace/upload/',v.upload,name='catalog_upload_v2'),path('workspace/parser/',v.upload_parser,name='parser_upload'),path('batches/<int:id>/',v.batch_detail,name='batch'),
 path('requests/',v.requests_list,name='requests'),path('requests/<uuid:id>/',v.request_detail,name='request'),path('requests/<uuid:id>/demo-answers/',v.demo_answers,name='demo_answers'),
 path('requests/<uuid:id>/order/',v.order_action,name='order_action'),path('parts/<int:id>/',v.part_detail,name='part'),
 path('parts/<int:id>/answer/',v.answer,name='answer'),path('parts/<int:id>/message/',v.message,name='message'),path('parts/<int:id>/alternative/',v.alternative,name='alternative')]
