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
    user_model.objects.create_user(username="reporter", password="secretpass123")

    token = csrf_token(client)
    login_resp = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "reporter", "password": "secretpass123"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert login_resp.status_code == 200
    return client


@pytest.fixture
def seeded_session(auth_client):
    started = post_json(auth_client, "/api/sessions/start/", {"source": "report-seed"})
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
def test_generate_report_and_download(auth_client, seeded_session, settings, tmp_path):
    settings.REPORTS_DIR = str(tmp_path)

    generated = post_json(
        auth_client,
        "/api/reports/generate/",
        {
            "session_id": seeded_session,
            "report_type": "clinical_summary",
            "clinician_notes": "Patient stable.",
        },
    )
    assert generated.status_code == 201
    payload = generated.json()
    assert payload["session_id"] == seeded_session
    assert payload["pdf_file_path"]

    report_id = payload["report_id"]

    listed = auth_client.get(f"/api/reports/?session_id={seeded_session}")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) >= 1

    detail = auth_client.get(f"/api/reports/{report_id}/")
    assert detail.status_code == 200
    assert detail.json()["report_id"] == report_id

    download = auth_client.get(f"/api/reports/{report_id}/download/")
    assert download.status_code == 200
    assert download["Content-Type"] == "application/pdf"
    body = b"".join(download.streaming_content)
    assert body.startswith(b"%PDF-")


@pytest.mark.django_db
def test_reports_validation_and_auth(auth_client, settings, tmp_path):
    settings.REPORTS_DIR = str(tmp_path)

    unauth = Client(enforce_csrf_checks=True)
    assert unauth.get("/api/reports/").status_code == 401

    missing = post_json(auth_client, "/api/reports/generate/", {})
    assert missing.status_code == 400

    invalid_session = post_json(auth_client, "/api/reports/generate/", {"session_id": 99999})
    assert invalid_session.status_code == 400

    bad_filter = auth_client.get("/api/reports/?session_id=abc")
    assert bad_filter.status_code == 400

    not_found = auth_client.get("/api/reports/99999/")
    assert not_found.status_code == 404

    missing_pdf = auth_client.get("/api/reports/99999/download/")
    assert missing_pdf.status_code == 404


@pytest.mark.django_db
def test_fall_risk_report_pdf_has_distinct_template(auth_client, seeded_session, settings, tmp_path):
    settings.REPORTS_DIR = str(tmp_path)

    generated = post_json(
        auth_client,
        "/api/reports/generate/",
        {
            "session_id": seeded_session,
            "report_type": "fall_risk_summary",
            "clinician_notes": "High-risk gait indicators reviewed.",
        },
    )
    assert generated.status_code == 201
    report_id = generated.json()["report_id"]

    download = auth_client.get(f"/api/reports/{report_id}/download/")
    assert download.status_code == 200
    body = b"".join(download.streaming_content)
    assert body.startswith(b"%PDF-")
    assert b"Fall Risk Assessment" in body
