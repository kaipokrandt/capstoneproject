from django.contrib import admin
from django.urls import include, path

from . import system_views, ui_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", ui_views.app),
    path("app/", ui_views.app),
    path("app/login/", ui_views.login),
    path("app/dashboard/", ui_views.dashboard),
    path("app/patients/", ui_views.patients),
    path("app/devices/", ui_views.devices),
    path("app/sessions/live/", ui_views.sessions_live),
    path("app/sessions/compare/", ui_views.sessions_compare),
    path("app/reports/", ui_views.reports),
    path("api/auth/", include("wbs.auth_urls")),
    path("api/sessions/", include("wbs.sessions_urls")),
    path("api/reports/", include("wbs.reports_urls")),
    path("api/fhir/", include("wbs.fhir_urls")),
    path("api/", include("wbs.master_urls")),
    path("api/overview/", system_views.overview),
    path("api/health/", system_views.health),
]
