from django.urls import path
from . import views

app_name = 'quality'

urlpatterns = [
    path('',                            views.qc_dashboard,        name='dashboard'),
    path('reagents/',                   views.reagent_list,        name='reagent_list'),
    path('reagents/<int:pk>/',          views.reagent_detail,      name='reagent_detail'),
    path('reagents/<int:reagent_pk>/lot/new/', views.register_lot, name='register_lot'),
    path('reagents/<int:reagent_pk>/qc/',     views.record_qc,     name='record_qc'),
    path('lots/<int:lot_pk>/deplete/',        views.deplete_lot,   name='deplete_lot'),
    path('calibrations/',               views.calibration_list,    name='calibration_list'),
    path('calibrations/new/',           views.record_calibration,  name='record_calibration'),
    path('nc/',                         views.nc_list,             name='nc_list'),
    path('nc/new/',                     views.nc_create,           name='nc_create'),
    path('nc/<int:pk>/',                views.nc_detail,           name='nc_detail'),
    path('lot-validation/',             views.lot_validation_list,   name='lot_validation_list'),
    path('lot-validation/new/',         views.lot_validation_create, name='lot_validation_create'),
    path('lot-validation/<int:pk>/',    views.lot_validation_detail, name='lot_validation_detail'),
    path('sop/',                         views.sop_list,              name='sop_list'),
    path('sop/new/',                     views.sop_create,            name='sop_create'),
    path('sop/<int:pk>/',                views.sop_detail,            name='sop_detail'),
    path('audits/',                      views.internal_audit_list,   name='internal_audit_list'),
    path('audits/new/',                  views.internal_audit_create, name='internal_audit_create'),
    path('audits/<int:pk>/',             views.internal_audit_detail, name='internal_audit_detail'),
    path('competency/',                  views.competency_list,       name='competency_list'),
    path('competency/new/',              views.competency_record,     name='competency_record'),
    path('committee/',                   views.committee_list,        name='committee_list'),
    path('committee/new/',               views.committee_create,      name='committee_create'),
    path('committee/<int:pk>/',          views.committee_detail,      name='committee_detail'),
]
