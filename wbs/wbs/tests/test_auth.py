import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.fixture
def csrf_client():
    return Client(enforce_csrf_checks=True)


@pytest.fixture
def csrf_headers(csrf_client):
    response = csrf_client.get("/api/auth/csrf/")
    assert response.status_code == 200
    token = response.json()["csrfToken"]
    return {"HTTP_X_CSRFTOKEN": token}


def post_json(client, url, payload, headers):
    return client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )


@pytest.mark.django_db
def test_csrf_endpoint_sets_cookie(csrf_client):
    response = csrf_client.get("/api/auth/csrf/")
    assert response.status_code == 200
    assert "csrfToken" in response.json()
    assert "csrftoken" in response.cookies


@pytest.mark.django_db
def test_register_creates_user_and_session(csrf_client, csrf_headers):
    user_model = get_user_model()
    response = post_json(
        csrf_client,
        "/api/auth/register/",
        {"username": "alice", "password": "secretpass123", "email": "a@example.com"},
        csrf_headers,
    )
    assert response.status_code == 201
    assert user_model.objects.filter(username="alice").exists()

    me = csrf_client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert me.json()["username"] == "alice"


@pytest.mark.django_db
def test_register_duplicate_username_returns_conflict(csrf_client, csrf_headers):
    user_model = get_user_model()
    user_model.objects.create_user(username="alice", password="x")
    response = post_json(
        csrf_client,
        "/api/auth/register/",
        {"username": "alice", "password": "anotherpass"},
        csrf_headers,
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_login_and_logout_flow(csrf_client, csrf_headers):
    user_model = get_user_model()
    user_model.objects.create_user(username="bob", password="secretpass123")

    bad = post_json(
        csrf_client,
        "/api/auth/login/",
        {"username": "bob", "password": "wrong"},
        csrf_headers,
    )
    assert bad.status_code == 401

    ok = post_json(
        csrf_client,
        "/api/auth/login/",
        {"username": "bob", "password": "secretpass123"},
        csrf_headers,
    )
    assert ok.status_code == 200

    me = csrf_client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.json()["username"] == "bob"

    fresh_csrf = csrf_client.get("/api/auth/csrf/")
    assert fresh_csrf.status_code == 200
    out = csrf_client.post(
        "/api/auth/logout/",
        HTTP_X_CSRFTOKEN=fresh_csrf.json()["csrfToken"],
    )
    assert out.status_code == 200

    me_after = csrf_client.get("/api/auth/me/")
    assert me_after.status_code == 401


@pytest.mark.django_db
def test_me_requires_authentication(csrf_client):
    response = csrf_client.get("/api/auth/me/")
    assert response.status_code == 401
    assert response.json()["authenticated"] is False
