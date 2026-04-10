from django.urls import path

from . import master_views

urlpatterns = [
    path("patients/", master_views.patients, name="patients"),
    path("patients/<int:patient_id>/", master_views.patient_detail, name="patient-detail"),
    path("devices/", master_views.devices, name="devices"),
    path("devices/<int:device_id>/", master_views.device_detail, name="device-detail"),
    path("calibration-profiles/", master_views.calibration_profiles, name="calibration-profiles"),
    path(
        "calibration-profiles/<int:calibration_profile_id>/",
        master_views.calibration_profile_detail,
        name="calibration-profile-detail",
    ),
]
