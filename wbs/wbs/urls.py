from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("wbs.auth_urls")),
    path("api/sessions/", include("wbs.sessions_urls")),
    path("api/", include("wbs.master_urls")),
]
