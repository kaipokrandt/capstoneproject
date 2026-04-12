from django.urls import path

from . import master_views

urlpatterns = [
    path("patients/", master_views.patients, name="patients"),
    path("patients/<int:patient_id>/", master_views.patient_detail, name="patient-detail"),
    path("devices/", master_views.devices, name="devices"),
    path("devices/pair/", master_views.pair_device, name="device-pair"),
    path("devices/<int:device_id>/", master_views.device_detail, name="device-detail"),
    path("devices/<int:device_id>/status/", master_views.device_status, name="device-status"),
    path(
        "devices/<int:device_id>/firmware/update/",
        master_views.device_firmware_update,
        name="device-firmware-update",
    ),
    path("devices/<int:device_id>/firmware/", master_views.device_firmware_status, name="device-firmware-status"),
    path("calibration-profiles/", master_views.calibration_profiles, name="calibration-profiles"),
    path("calibration/run/", master_views.calibration_run_start, name="calibration-run-start"),
    path(
        "calibration/run/<int:device_id>/",
        master_views.calibration_run_status,
        name="calibration-run-status",
    ),
    path(
        "calibration-profiles/<int:calibration_profile_id>/",
        master_views.calibration_profile_detail,
        name="calibration-profile-detail",
    ),
    path("annotations/", master_views.annotations, name="annotations"),
    path("annotations/<int:annotation_id>/", master_views.annotation_detail, name="annotation-detail"),
    path("ui-preferences/", master_views.ui_preferences, name="ui-preferences"),
]
