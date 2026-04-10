import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


def csrf_token(client: Client) -> str:
    resp = client.get("/api/auth/csrf/")
    assert resp.status_code == 200
    return resp.json()["csrfToken"]


def post_json(client: Client, url: str, payload: dict):
    token = csrf_token(client)
    return client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )


@pytest.mark.django_db
def test_overview_unauthenticated():
    client = Client(enforce_csrf_checks=True)
    resp = client.get("/api/overview/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["health"] == "ok"
    assert data["authenticated"] is False
    assert data["counts"] is None


@pytest.mark.django_db
def test_overview_authenticated_with_counts():
    client = Client(enforce_csrf_checks=True)
    user_model = get_user_model()
    user_model.objects.create_user(username="overview", password="secretpass123")

    token = csrf_token(client)
    login_resp = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "overview", "password": "secretpass123"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert login_resp.status_code == 200

    post_json(client, "/api/patients/", {"external_id": "P-OV-1"})
    post_json(client, "/api/devices/", {"serial_number": "DEV-OV-1"})
    s = post_json(client, "/api/sessions/start/", {"source": "overview"})
    assert s.status_code == 201
    sid = s.json()["session_id"]
    r = post_json(client, "/api/reports/generate/", {"session_id": sid})
    assert r.status_code == 201

    resp = client.get("/api/overview/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is True
    assert data["user"]["username"] == "overview"
    assert data["counts"]["patients"] >= 1
    assert data["counts"]["devices"] >= 1
    assert data["counts"]["sessions"] >= 1
    assert data["counts"]["reports"] >= 1
    assert data["latest"]["session_id"] is not None
    assert data["latest"]["report_id"] is not None
