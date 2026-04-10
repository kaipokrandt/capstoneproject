from django.urls import path

from . import reports_views

urlpatterns = [
    path("generate/", reports_views.generate_report, name="report-generate"),
    path("", reports_views.reports, name="reports"),
    path("<int:report_id>/", reports_views.report_detail, name="report-detail"),
    path("<int:report_id>/download/", reports_views.report_download, name="report-download"),
]
