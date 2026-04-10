from django.urls import path

from . import auth_views

urlpatterns = [
    path("csrf/", auth_views.csrf, name="auth-csrf"),
    path("register/", auth_views.register, name="auth-register"),
    path("login/", auth_views.login_view, name="auth-login"),
    path("logout/", auth_views.logout_view, name="auth-logout"),
    path("me/", auth_views.me, name="auth-me"),
]
