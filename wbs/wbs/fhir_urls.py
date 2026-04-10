from django.urls import path

from . import fhir_views

urlpatterns = [
    path("export/session/<int:session_id>/", fhir_views.session_export, name="fhir-session-export"),
]
