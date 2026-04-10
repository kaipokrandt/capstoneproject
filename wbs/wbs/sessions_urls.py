from django.urls import path

from . import sessions_views

urlpatterns = [
    path("", sessions_views.sessions_list, name="sessions-list"),
    path("start/", sessions_views.start_session, name="session-start"),
    path("compare/", sessions_views.compare_sessions, name="session-compare"),
    path("<int:session_id>/frames/", sessions_views.ingest_frame, name="session-ingest-frame"),
    path("<int:session_id>/end/", sessions_views.end_session, name="session-end"),
    path("<int:session_id>/metrics/", sessions_views.session_metrics, name="session-metrics"),
    path("<int:session_id>/", sessions_views.session_detail, name="session-detail"),
]
