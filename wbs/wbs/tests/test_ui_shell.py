import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.mark.django_db
def test_app_root_redirects_to_dashboard():
    client = Client()
    resp = client.get("/app/")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/app/login/"


@pytest.mark.django_db
def test_site_root_redirects_based_on_auth():
    client = Client()

    unauth = client.get("/")
    assert unauth.status_code == 302
    assert unauth.headers["Location"] == "/app/login/"

    user_model = get_user_model()
    user = user_model.objects.create_user(username="rootredir", password="secretpass123")
    client.force_login(user)
    authed = client.get("/")
    assert authed.status_code == 302
    assert authed.headers["Location"] == "/app/dashboard/"


@pytest.mark.parametrize(
    "route",
    [
        "/app/dashboard/",
        "/app/patients/",
        "/app/devices/",
        "/app/sessions/live/",
        "/app/sessions/compare/",
        "/app/reports/",
    ],
)
@pytest.mark.django_db
def test_ui_pages_serve(route):
    client = Client()
    resp = client.get(route)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/app/login/")


@pytest.mark.django_db
def test_login_page_serves():
    client = Client()
    resp = client.get("/app/login/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "InsolePro" in content


@pytest.mark.django_db
def test_reports_page_contains_preview_modal_shell_when_authenticated():
    client = Client()
    user_model = get_user_model()
    user = user_model.objects.create_user(username="modaluser", password="secretpass123")
    client.force_login(user)

    resp = client.get("/app/reports/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert 'id="report-preview-modal"' in content
    assert 'id="report-tab-summary"' in content
    assert 'id="report-tab-pdf"' in content
