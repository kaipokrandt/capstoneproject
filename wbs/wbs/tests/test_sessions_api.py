import base64
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from wbs.models import CalibrationProfile, ComputedMetric, Device, Patient, RawFrame, Session


@pytest.fixture
def session_client():
    return Client(enforce_csrf_checks=True)


@pytest.fixture
def auth_session_client(session_client):
    user_model = get_user_model()
    user_model.objects.create_user(username="apiuser", password="secretpass123")

    csrf = session_client.get("/api/auth/csrf/")
    token = csrf.json()["csrfToken"]
    login_resp = session_client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "apiuser", "password": "secretpass123"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert login_resp.status_code == 200
    return session_client


def post_json(client, url, payload):
    csrf = client.get("/api/auth/csrf/")
    assert csrf.status_code == 200
    token = csrf.json()["csrfToken"]
    return client.post(
        url,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )


@pytest.mark.django_db
def test_session_endpoints_require_auth(session_client):
    start_resp = post_json(session_client, "/api/sessions/start/", {"source": "x"})
    assert start_resp.status_code == 401

    s = Session.objects.create(started_at_us=1, source="x")
    frame_resp = post_json(
        session_client,
        f"/api/sessions/{s.session_id}/frames/",
        {
            "ts_us": 1,
            "gw": 1,
            "gh": 1,
            "battery_pct": 90,
            "flags": 0,
            "total_load": 1,
            "adc_base64": base64.b64encode(b"\x00\x01").decode("ascii"),
        },
    )
    assert frame_resp.status_code == 401

    end_resp = post_json(session_client, f"/api/sessions/{s.session_id}/end/", {})
    assert end_resp.status_code == 401

    detail = session_client.get(f"/api/sessions/{s.session_id}/")
    assert detail.status_code == 401


@pytest.mark.django_db
def test_start_session_with_links(auth_session_client):
    patient = Patient.objects.create(external_id="P-API-1")
    device = Device.objects.create(serial_number="DEV-API-1")
    calibration = CalibrationProfile.objects.create(
        device=device,
        profile_name="default",
        version="v1",
    )

    resp = post_json(
        auth_session_client,
        "/api/sessions/start/",
        {
            "patient_id": patient.patient_id,
            "device_id": device.device_id,
            "calibration_profile_id": calibration.calibration_profile_id,
            "started_at_us": 123456789,
            "source": "device-stream",
            "notes": "clinic visit",
        },
    )
    assert resp.status_code == 201
    payload = resp.json()
    assert payload["source"] == "device-stream"
    assert payload["patient_id"] == patient.patient_id
    assert payload["device_id"] == device.device_id


@pytest.mark.django_db
def test_start_session_validation_errors(auth_session_client):
    missing_source = post_json(auth_session_client, "/api/sessions/start/", {})
    assert missing_source.status_code == 400

    bad_patient = post_json(
        auth_session_client,
        "/api/sessions/start/",
        {"source": "stream", "patient_id": 9999},
    )
    assert bad_patient.status_code == 400

    d1 = Device.objects.create(serial_number="DEV-API-2")
    d2 = Device.objects.create(serial_number="DEV-API-3")
    cp = CalibrationProfile.objects.create(device=d1, profile_name="p", version="v")

    mismatch = post_json(
        auth_session_client,
        "/api/sessions/start/",
        {
            "source": "stream",
            "device_id": d2.device_id,
            "calibration_profile_id": cp.calibration_profile_id,
        },
    )
    assert mismatch.status_code == 400


@pytest.mark.django_db
def test_frame_ingest_and_session_detail(auth_session_client):
    start = post_json(auth_session_client, "/api/sessions/start/", {"source": "live"})
    session_id = start.json()["session_id"]

    frame_resp = post_json(
        auth_session_client,
        f"/api/sessions/{session_id}/frames/",
        {
            "ts_us": 2000,
            "gw": 2,
            "gh": 2,
            "battery_pct": 88,
            "flags": 1,
            "total_load": 15.5,
            "adc_base64": base64.b64encode(b"\x01\x00\x02\x00").decode("ascii"),
        },
    )
    assert frame_resp.status_code == 201
    frame_id = frame_resp.json()["frame_id"]
    frame = RawFrame.objects.get(frame_id=frame_id)
    assert bytes(frame.adc_blob) == b"\x01\x00\x02\x00"

    session = Session.objects.get(session_id=session_id)
    ComputedMetric.objects.create(
        session=session,
        ts_us=2000,
        metric_name="cop_x",
        metric_value=1.0,
        unit="grid_x",
    )

    detail = auth_session_client.get(f"/api/sessions/{session_id}/")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["raw_frame_count"] == 1
    assert payload["computed_metric_count"] == 1


@pytest.mark.django_db
def test_frame_ingest_validation(auth_session_client):
    start = post_json(auth_session_client, "/api/sessions/start/", {"source": "live"})
    session_id = start.json()["session_id"]

    missing = post_json(auth_session_client, f"/api/sessions/{session_id}/frames/", {"ts_us": 1})
    assert missing.status_code == 400

    bad_base64 = post_json(
        auth_session_client,
        f"/api/sessions/{session_id}/frames/",
        {
            "ts_us": 1,
            "gw": 1,
            "gh": 1,
            "battery_pct": 90,
            "flags": 0,
            "total_load": 1,
            "adc_base64": "not-base64@@",
        },
    )
    assert bad_base64.status_code == 400


@pytest.mark.django_db
def test_end_session_and_block_future_frames(auth_session_client):
    start = post_json(auth_session_client, "/api/sessions/start/", {"source": "live"})
    session_id = start.json()["session_id"]

    end_resp = post_json(
        auth_session_client,
        f"/api/sessions/{session_id}/end/",
        {"ended_at_us": 9999, "risk_label": "moderate", "risk_score": 57.2},
    )
    assert end_resp.status_code == 200
    assert end_resp.json()["risk_label"] == "moderate"

    blocked = post_json(
        auth_session_client,
        f"/api/sessions/{session_id}/frames/",
        {
            "ts_us": 10000,
            "gw": 1,
            "gh": 1,
            "battery_pct": 90,
            "flags": 0,
            "total_load": 1,
            "adc_base64": base64.b64encode(b"\x00\x01").decode("ascii"),
        },
    )
    assert blocked.status_code == 409


@pytest.mark.django_db
def test_not_found_session_paths(auth_session_client):
    frame_resp = post_json(
        auth_session_client,
        "/api/sessions/99999/frames/",
        {
            "ts_us": 1,
            "gw": 1,
            "gh": 1,
            "battery_pct": 90,
            "flags": 0,
            "total_load": 1,
            "adc_base64": base64.b64encode(b"\x00\x01").decode("ascii"),
        },
    )
    assert frame_resp.status_code == 404

    end_resp = post_json(auth_session_client, "/api/sessions/99999/end/", {})
    assert end_resp.status_code == 404

    detail = auth_session_client.get("/api/sessions/99999/")
    assert detail.status_code == 404
