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
    list_resp = session_client.get("/api/sessions/")
    assert list_resp.status_code == 401

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
            "adc_base64": base64.b64encode(b"\x01\x00\x02\x00\x03\x00\x04\x00").decode("ascii"),
        },
    )
    assert frame_resp.status_code == 201
    frame_id = frame_resp.json()["frame_id"]
    assert frame_resp.json()["metric_rows_written"] == 8
    frame = RawFrame.objects.get(frame_id=frame_id)
    assert bytes(frame.adc_blob) == b"\x01\x00\x02\x00\x03\x00\x04\x00"

    session = Session.objects.get(session_id=session_id)
    names = set(ComputedMetric.objects.filter(session=session).values_list("metric_name", flat=True))
    assert names == {
        "cop_x",
        "cop_y",
        "cop_v",
        "sway_path",
        "total_load",
        "stance_pct",
        "swing_pct",
        "asymmetry_index",
    }

    detail = auth_session_client.get(f"/api/sessions/{session_id}/")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["raw_frame_count"] == 1
    assert payload["computed_metric_count"] == 8


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


@pytest.mark.django_db
def test_session_metrics_endpoint_returns_grouped_series(auth_session_client):
    start = post_json(auth_session_client, "/api/sessions/start/", {"source": "live"})
    session_id = start.json()["session_id"]

    post_json(
        auth_session_client,
        f"/api/sessions/{session_id}/frames/",
        {
            "ts_us": 2000,
            "gw": 2,
            "gh": 2,
            "battery_pct": 88,
            "flags": 1,
            "total_load": 15.5,
            "adc_base64": base64.b64encode(b"\x01\x00\x02\x00\x03\x00\x04\x00").decode("ascii"),
        },
    )
    post_json(
        auth_session_client,
        f"/api/sessions/{session_id}/frames/",
        {
            "ts_us": 3000,
            "gw": 2,
            "gh": 2,
            "battery_pct": 87,
            "flags": 0,
            "total_load": 16.2,
            "adc_base64": base64.b64encode(b"\x04\x00\x03\x00\x02\x00\x01\x00").decode("ascii"),
        },
    )

    resp = auth_session_client.get(f"/api/sessions/{session_id}/metrics/")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["session_id"] == session_id
    assert payload["count"] > 0
    assert "cop_x" in payload["metric_names"]
    assert "cop_x" in payload["series"]
    assert all("ts_us" in p and "value" in p for p in payload["series"]["cop_x"])


@pytest.mark.django_db
def test_session_metrics_endpoint_supports_filters(auth_session_client):
    start = post_json(auth_session_client, "/api/sessions/start/", {"source": "live"})
    session_id = start.json()["session_id"]

    post_json(
        auth_session_client,
        f"/api/sessions/{session_id}/frames/",
        {
            "ts_us": 1000,
            "gw": 2,
            "gh": 2,
            "battery_pct": 90,
            "flags": 0,
            "total_load": 10.0,
            "adc_base64": base64.b64encode(b"\x01\x00\x02\x00\x03\x00\x04\x00").decode("ascii"),
        },
    )
    post_json(
        auth_session_client,
        f"/api/sessions/{session_id}/frames/",
        {
            "ts_us": 2000,
            "gw": 2,
            "gh": 2,
            "battery_pct": 89,
            "flags": 0,
            "total_load": 11.0,
            "adc_base64": base64.b64encode(b"\x02\x00\x02\x00\x02\x00\x02\x00").decode("ascii"),
        },
    )

    filtered = auth_session_client.get(
        f"/api/sessions/{session_id}/metrics/?metric_name=total_load&ts_from=1500&limit=1"
    )
    assert filtered.status_code == 200
    payload = filtered.json()
    assert payload["metric_names"] == ["total_load"]
    assert payload["count"] == 1
    assert payload["series"]["total_load"][0]["ts_us"] >= 1500


@pytest.mark.django_db
def test_session_metrics_endpoint_validation_and_auth(auth_session_client, session_client):
    start = post_json(auth_session_client, "/api/sessions/start/", {"source": "live"})
    session_id = start.json()["session_id"]

    unauth_client = Client(enforce_csrf_checks=True)
    unauth = unauth_client.get(f"/api/sessions/{session_id}/metrics/")
    assert unauth.status_code == 401

    not_found = auth_session_client.get("/api/sessions/99999/metrics/")
    assert not_found.status_code == 404

    bad_ts = auth_session_client.get(f"/api/sessions/{session_id}/metrics/?ts_from=abc")
    assert bad_ts.status_code == 400

    bad_limit = auth_session_client.get(f"/api/sessions/{session_id}/metrics/?limit=0")
    assert bad_limit.status_code == 400


@pytest.mark.django_db
def test_session_compare_endpoint_returns_summary_and_deltas(auth_session_client):
    patient = Patient.objects.create(external_id="P-CMP-1")
    first = post_json(
        auth_session_client,
        "/api/sessions/start/",
        {"source": "live", "patient_id": patient.patient_id},
    ).json()["session_id"]
    second = post_json(
        auth_session_client,
        "/api/sessions/start/",
        {"source": "live", "patient_id": patient.patient_id},
    ).json()["session_id"]

    post_json(
        auth_session_client,
        f"/api/sessions/{first}/frames/",
        {
            "ts_us": 1000,
            "gw": 2,
            "gh": 2,
            "battery_pct": 90,
            "flags": 0,
            "total_load": 10.0,
            "adc_base64": base64.b64encode(b"\x01\x00\x02\x00\x03\x00\x04\x00").decode("ascii"),
        },
    )
    post_json(
        auth_session_client,
        f"/api/sessions/{second}/frames/",
        {
            "ts_us": 2000,
            "gw": 2,
            "gh": 2,
            "battery_pct": 88,
            "flags": 0,
            "total_load": 15.0,
            "adc_base64": base64.b64encode(b"\x04\x00\x03\x00\x02\x00\x01\x00").decode("ascii"),
        },
    )

    resp = auth_session_client.get(
        f"/api/sessions/compare/?session_ids={first},{second}&metric_name=total_load,cop_x"
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["session_ids"] == [first, second]
    assert payload["patient_id"] == patient.patient_id
    assert len(payload["comparison"]) == 2
    assert "total_load" in payload["comparison"][0]["metrics"]
    assert str(second) in payload["delta_from_first"]


@pytest.mark.django_db
def test_session_compare_validation_and_auth(auth_session_client):
    unauth = Client(enforce_csrf_checks=True)
    assert unauth.get("/api/sessions/compare/?session_ids=1,2").status_code == 401

    missing = auth_session_client.get("/api/sessions/compare/")
    assert missing.status_code == 400

    single = auth_session_client.get("/api/sessions/compare/?session_ids=1")
    assert single.status_code == 400

    bad = auth_session_client.get("/api/sessions/compare/?session_ids=abc,2")
    assert bad.status_code == 400

    not_found = auth_session_client.get("/api/sessions/compare/?session_ids=1,2")
    assert not_found.status_code == 404


@pytest.mark.django_db
def test_sessions_list_endpoint_returns_items_and_supports_filters(auth_session_client):
    p1 = Patient.objects.create(external_id="P-LIST-1", first_name="Maya", last_name="Singh")
    p2 = Patient.objects.create(external_id="P-LIST-2", first_name="Noah", last_name="Lee")
    d1 = Device.objects.create(serial_number="DEV-LIST-1")
    d2 = Device.objects.create(serial_number="DEV-LIST-2")

    s1 = post_json(
        auth_session_client,
        "/api/sessions/start/",
        {"source": "assessment_a", "patient_id": p1.patient_id, "device_id": d1.device_id, "started_at_us": 1000},
    ).json()["session_id"]
    s2 = post_json(
        auth_session_client,
        "/api/sessions/start/",
        {"source": "assessment_b", "patient_id": p2.patient_id, "device_id": d2.device_id, "started_at_us": 2000},
    ).json()["session_id"]

    assert s1 != s2

    all_resp = auth_session_client.get("/api/sessions/")
    assert all_resp.status_code == 200
    all_items = all_resp.json()["items"]
    assert len(all_items) >= 2
    assert all_items[0]["started_at_us"] >= all_items[1]["started_at_us"]

    first = next(item for item in all_items if item["session_id"] == s1)
    assert first["patient_id"] == p1.patient_id
    assert first["patient_external_id"] == "P-LIST-1"
    assert first["patient_name"] == "Maya Singh"
    assert first["device_serial_number"] == "DEV-LIST-1"

    by_patient = auth_session_client.get(f"/api/sessions/?patient_id={p1.patient_id}")
    assert by_patient.status_code == 200
    ids_by_patient = [item["session_id"] for item in by_patient.json()["items"]]
    assert ids_by_patient == [s1]

    by_device = auth_session_client.get(f"/api/sessions/?device_id={d2.device_id}")
    assert by_device.status_code == 200
    ids_by_device = [item["session_id"] for item in by_device.json()["items"]]
    assert ids_by_device == [s2]


@pytest.mark.django_db
def test_sessions_list_endpoint_validation(auth_session_client):
    bad_patient = auth_session_client.get("/api/sessions/?patient_id=abc")
    assert bad_patient.status_code == 400

    bad_device = auth_session_client.get("/api/sessions/?device_id=abc")
    assert bad_device.status_code == 400
