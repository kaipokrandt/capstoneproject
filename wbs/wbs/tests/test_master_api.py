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


def patch_json(client: Client, url: str, payload: dict):
    token = csrf_token(client)
    return client.patch(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )


def delete_json(client: Client, url: str):
    token = csrf_token(client)
    return client.delete(url, HTTP_X_CSRFTOKEN=token)


@pytest.fixture
def auth_client():
    client = Client(enforce_csrf_checks=True)
    user_model = get_user_model()
    user_model.objects.create_user(username="master", password="secretpass123")

    token = csrf_token(client)
    login_resp = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "master", "password": "secretpass123"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert login_resp.status_code == 200
    return client


@pytest.mark.django_db
def test_master_endpoints_require_auth():
    client = Client(enforce_csrf_checks=True)
    assert client.get("/api/patients/").status_code == 401
    assert client.get("/api/devices/").status_code == 401
    assert client.get("/api/calibration-profiles/").status_code == 401


@pytest.mark.django_db
def test_patient_crud(auth_client):
    created = post_json(
        auth_client,
        "/api/patients/",
        {
            "external_id": "P-100",
            "first_name": "Sam",
            "last_name": "Lee",
            "date_of_birth": "1990-01-02",
            "sex": "f",
            "metadata": {"clinic": "A"},
        },
    )
    assert created.status_code == 201
    patient_id = created.json()["patient_id"]

    listed = auth_client.get("/api/patients/?external_id=P-100")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1

    updated = patch_json(
        auth_client,
        f"/api/patients/{patient_id}/",
        {"first_name": "Samantha", "metadata": {"clinic": "B"}},
    )
    assert updated.status_code == 200
    assert updated.json()["first_name"] == "Samantha"

    detail = auth_client.get(f"/api/patients/{patient_id}/")
    assert detail.status_code == 200
    assert detail.json()["metadata"]["clinic"] == "B"

    deleted = delete_json(auth_client, f"/api/patients/{patient_id}/")
    assert deleted.status_code == 200
    assert auth_client.get(f"/api/patients/{patient_id}/").status_code == 404


@pytest.mark.django_db
def test_patient_validation_and_conflict(auth_client):
    missing = post_json(auth_client, "/api/patients/", {})
    assert missing.status_code == 400

    bad_dob = post_json(
        auth_client,
        "/api/patients/",
        {"external_id": "P-101", "date_of_birth": "01-02-1990"},
    )
    assert bad_dob.status_code == 400

    p1 = post_json(auth_client, "/api/patients/", {"external_id": "P-102"})
    assert p1.status_code == 201
    p2 = post_json(auth_client, "/api/patients/", {"external_id": "P-102"})
    assert p2.status_code == 409


@pytest.mark.django_db
def test_device_crud_and_conflict(auth_client):
    created = post_json(
        auth_client,
        "/api/devices/",
        {
            "serial_number": "DEV-100",
            "model": "insole-v1",
            "firmware_version": "1.2.3",
            "metadata": {"site": "lab"},
        },
    )
    assert created.status_code == 201
    device_id = created.json()["device_id"]

    dup = post_json(auth_client, "/api/devices/", {"serial_number": "DEV-100"})
    assert dup.status_code == 409

    updated = patch_json(
        auth_client,
        f"/api/devices/{device_id}/",
        {"firmware_version": "2.0.0"},
    )
    assert updated.status_code == 200
    assert updated.json()["firmware_version"] == "2.0.0"

    deleted = delete_json(auth_client, f"/api/devices/{device_id}/")
    assert deleted.status_code == 200
    assert auth_client.get(f"/api/devices/{device_id}/").status_code == 404


@pytest.mark.django_db
def test_calibration_profile_crud_filters_and_conflict(auth_client):
    d1 = post_json(auth_client, "/api/devices/", {"serial_number": "DEV-201"}).json()["device_id"]
    d2 = post_json(auth_client, "/api/devices/", {"serial_number": "DEV-202"}).json()["device_id"]

    c1 = post_json(
        auth_client,
        "/api/calibration-profiles/",
        {
            "device_id": d1,
            "profile_name": "default",
            "version": "v1",
            "parameters": {"gain": 1.2},
            "is_active": True,
        },
    )
    assert c1.status_code == 201
    calibration_id = c1.json()["calibration_profile_id"]

    c2 = post_json(
        auth_client,
        "/api/calibration-profiles/",
        {
            "device_id": d2,
            "profile_name": "default",
            "version": "v1",
        },
    )
    assert c2.status_code == 201

    dup = post_json(
        auth_client,
        "/api/calibration-profiles/",
        {"device_id": d1, "profile_name": "default", "version": "v1"},
    )
    assert dup.status_code == 409

    filtered = auth_client.get(f"/api/calibration-profiles/?device_id={d1}")
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1

    updated = patch_json(
        auth_client,
        f"/api/calibration-profiles/{calibration_id}/",
        {"is_active": False, "parameters": {"gain": 1.3}},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False

    inactive = auth_client.get("/api/calibration-profiles/?is_active=false")
    assert inactive.status_code == 200
    assert any(x["calibration_profile_id"] == calibration_id for x in inactive.json()["items"])

    deleted = delete_json(auth_client, f"/api/calibration-profiles/{calibration_id}/")
    assert deleted.status_code == 200
    assert auth_client.get(f"/api/calibration-profiles/{calibration_id}/").status_code == 404


@pytest.mark.django_db
def test_calibration_profile_validation(auth_client):
    missing = post_json(auth_client, "/api/calibration-profiles/", {"profile_name": "p"})
    assert missing.status_code == 400

    bad_device = post_json(
        auth_client,
        "/api/calibration-profiles/",
        {"device_id": 99999, "profile_name": "p"},
    )
    assert bad_device.status_code == 400

    bad_filter = auth_client.get("/api/calibration-profiles/?device_id=abc")
    assert bad_filter.status_code == 400

    bad_active = auth_client.get("/api/calibration-profiles/?is_active=maybe")
    assert bad_active.status_code == 400
