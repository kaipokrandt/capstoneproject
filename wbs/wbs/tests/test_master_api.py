import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from wbs.models import Report, Session, default_sensor_layout


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
    assert client.get("/api/ui-preferences/").status_code == 401
    assert post_json(client, "/api/devices/pair/", {}).status_code == 401
    assert post_json(client, "/api/calibration/run/", {}).status_code == 401


@pytest.mark.django_db
def test_ui_preferences_default_and_patch(auth_client):
    got = auth_client.get("/api/ui-preferences/")
    assert got.status_code == 200
    assert got.json()["sensor_layout"] == default_sensor_layout()

    payload = default_sensor_layout()
    payload["left"][0]["x"] = 0.5
    patched = patch_json(auth_client, "/api/ui-preferences/", {"sensor_layout": payload})
    assert patched.status_code == 200
    assert patched.json()["sensor_layout"]["left"][0]["x"] == 0.5

    bad = patch_json(auth_client, "/api/ui-preferences/", {"sensor_layout": {"left": [], "right": []}})
    assert bad.status_code == 400


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


@pytest.mark.django_db
def test_annotation_crud_and_filters(auth_client):
    patient_id = post_json(auth_client, "/api/patients/", {"external_id": "P-ANN-1"}).json()["patient_id"]
    device_id = post_json(auth_client, "/api/devices/", {"serial_number": "DEV-ANN-1"}).json()["device_id"]
    session = post_json(
        auth_client,
        "/api/sessions/start/",
        {"source": "ann-source", "patient_id": patient_id, "device_id": device_id},
    ).json()["session_id"]

    frame_payload = {
        "ts_us": 1000,
        "gw": 2,
        "gh": 2,
        "battery_pct": 90,
        "flags": 0,
        "total_load": 10.0,
        "adc_base64": "AQACAAMABAA=",
    }
    post_json(auth_client, f"/api/sessions/{session}/frames/", frame_payload)
    report_id = Report.objects.create(session=Session.objects.get(session_id=session)).report_id

    created = post_json(
        auth_client,
        "/api/annotations/",
        {
            "patient_id": patient_id,
            "session_id": session,
            "report_id": report_id,
            "author": "clinician",
            "body": "Initial note",
            "metadata": {"severity": "low"},
        },
    )
    assert created.status_code == 201
    annotation_id = created.json()["annotation_id"]

    detail = auth_client.get(f"/api/annotations/{annotation_id}/")
    assert detail.status_code == 200
    assert detail.json()["body"] == "Initial note"

    filtered = auth_client.get(f"/api/annotations/?patient_id={patient_id}")
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1

    patched = patch_json(
        auth_client,
        f"/api/annotations/{annotation_id}/",
        {"body": "Updated note", "metadata": {"severity": "medium"}},
    )
    assert patched.status_code == 200
    assert patched.json()["body"] == "Updated note"

    deleted = delete_json(auth_client, f"/api/annotations/{annotation_id}/")
    assert deleted.status_code == 200
    assert auth_client.get(f"/api/annotations/{annotation_id}/").status_code == 404


@pytest.mark.django_db
def test_annotation_validation_and_auth(auth_client):
    unauth = Client(enforce_csrf_checks=True)
    assert unauth.get("/api/annotations/").status_code == 401

    missing_body = post_json(auth_client, "/api/annotations/", {})
    assert missing_body.status_code == 400

    bad_patient = post_json(auth_client, "/api/annotations/", {"body": "x", "patient_id": 99999})
    assert bad_patient.status_code == 400

    bad_filter = auth_client.get("/api/annotations/?session_id=abc")
    assert bad_filter.status_code == 400

    not_found = auth_client.get("/api/annotations/99999/")
    assert not_found.status_code == 404


@pytest.mark.django_db
def test_device_pairing_firmware_and_calibration_run(auth_client):
    device_id = post_json(auth_client, "/api/devices/", {"serial_number": "DEV-RUN-1"}).json()["device_id"]

    paired = post_json(
        auth_client,
        "/api/devices/pair/",
        {"device_id": device_id, "connection_status": "connected", "connection_quality": "excellent"},
    )
    assert paired.status_code == 200
    assert paired.json()["pairing"]["status"] == "paired"

    status = auth_client.get(f"/api/devices/{device_id}/status/")
    assert status.status_code == 200
    assert status.json()["connection"]["quality"] == "excellent"

    fw_start = post_json(
        auth_client,
        f"/api/devices/{device_id}/firmware/update/",
        {"target_version": "9.9.9", "duration_sec": 0},
    )
    assert fw_start.status_code == 200
    fw_status = auth_client.get(f"/api/devices/{device_id}/firmware/")
    assert fw_status.status_code == 200
    assert fw_status.json()["update"]["status"] == "completed"
    assert fw_status.json()["current_version"] == "9.9.9"

    cal_start = post_json(
        auth_client,
        "/api/calibration/run/",
        {
            "device_id": device_id,
            "profile_name": "clinic-default",
            "version": "v2",
            "parameters": {"gain": 1.4},
            "duration_sec": 0,
        },
    )
    assert cal_start.status_code == 200
    cal_status = auth_client.get(f"/api/calibration/run/{device_id}/")
    assert cal_status.status_code == 200
    job = cal_status.json()["calibration_job"]
    assert job["status"] == "completed"
    assert job["created_profile_id"] is not None

    profile = auth_client.get(f"/api/calibration-profiles/{job['created_profile_id']}/")
    assert profile.status_code == 200
    assert profile.json()["profile_name"] == "clinic-default"


@pytest.mark.django_db
def test_device_workflow_validation(auth_client):
    missing_pair_target = post_json(auth_client, "/api/devices/pair/", {})
    assert missing_pair_target.status_code == 400

    bad_fw = post_json(auth_client, "/api/devices/99999/firmware/update/", {"target_version": "1.0.0"})
    assert bad_fw.status_code == 404

    device_id = post_json(auth_client, "/api/devices/", {"serial_number": "DEV-RUN-VAL-1"}).json()["device_id"]
    missing_target = post_json(auth_client, f"/api/devices/{device_id}/firmware/update/", {})
    assert missing_target.status_code == 400

    bad_cal_start = post_json(auth_client, "/api/calibration/run/", {"device_id": 99999})
    assert bad_cal_start.status_code == 400
