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


@pytest.fixture
def auth_client():
    client = Client(enforce_csrf_checks=True)
    user_model = get_user_model()
    user_model.objects.create_user(username="fhir", password="secretpass123")

    token = csrf_token(client)
    login_resp = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "fhir", "password": "secretpass123"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert login_resp.status_code == 200
    return client


@pytest.fixture
def seeded_session(auth_client):
    patient_id = post_json(auth_client, "/api/patients/", {"external_id": "P-FHIR-1", "first_name": "Pat"}).json()[
        "patient_id"
    ]
    device_id = post_json(auth_client, "/api/devices/", {"serial_number": "DEV-FHIR-1", "model": "wbs-v1"}).json()[
        "device_id"
    ]

    started = post_json(
        auth_client,
        "/api/sessions/start/",
        {"source": "fhir-seed", "patient_id": patient_id, "device_id": device_id, "started_at_us": 1000},
    )
    assert started.status_code == 201
    session_id = started.json()["session_id"]

    frame = {
        "ts_us": 1000,
        "gw": 2,
        "gh": 2,
        "battery_pct": 90,
        "flags": 0,
        "total_load": 10.0,
        "adc_base64": "AQACAAMABAA=",
    }
    ingested = post_json(auth_client, f"/api/sessions/{session_id}/frames/", frame)
    assert ingested.status_code == 201

    ended = post_json(
        auth_client,
        f"/api/sessions/{session_id}/end/",
        {"ended_at_us": 2000, "risk_label": "low", "risk_score": 10.5},
    )
    assert ended.status_code == 200
    return session_id


@pytest.mark.django_db
def test_generate_and_fetch_latest_fhir_export(auth_client, seeded_session):
    generated = post_json(auth_client, f"/api/fhir/export/session/{seeded_session}/", {})
    assert generated.status_code == 201
    payload = generated.json()

    assert payload["session_id"] == seeded_session
    assert payload["report_type"] == "fhir_export"
    assert payload["bundle"]["resourceType"] == "Bundle"

    entries = payload["bundle"]["entry"]
    resource_types = [e["resource"]["resourceType"] for e in entries]
    assert "Encounter" in resource_types
    assert "Observation" in resource_types
    assert "Patient" in resource_types
    assert "Device" in resource_types

    latest = auth_client.get(f"/api/fhir/export/session/{seeded_session}/")
    assert latest.status_code == 200
    latest_payload = latest.json()
    assert latest_payload["report_id"] == payload["report_id"]
    assert latest_payload["bundle"]["resourceType"] == "Bundle"


@pytest.mark.django_db
def test_fhir_export_validation_and_auth(auth_client, seeded_session):
    unauth = Client(enforce_csrf_checks=True)
    assert unauth.get(f"/api/fhir/export/session/{seeded_session}/").status_code == 401

    not_found_session = post_json(auth_client, "/api/fhir/export/session/99999/", {})
    assert not_found_session.status_code == 404

    no_export_yet = auth_client.get("/api/fhir/export/session/99998/")
    assert no_export_yet.status_code == 404
