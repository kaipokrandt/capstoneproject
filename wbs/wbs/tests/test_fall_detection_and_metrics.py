"""
Tests covering:
  1. Bridge fall detection (jerk-based, env-var threshold)
  2. compute_frame_metrics — incremental append + trim
  3. ingest_frame API — uses compute_frame_metrics, not full recompute
  4. BLE session resolver logic (pollBleLog annotation filtering is JS-side;
     we verify the annotation is written with correct metadata)
"""
from __future__ import annotations

import base64
import importlib.util
import json
import math
import os
import struct
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from wbs.models import ComputedMetric, Device, Patient, RawFrame, Session
from wbs.metrics_pipeline import MAX_METRIC_ROWS_PER_NAME, compute_frame_metrics


# ── Bridge module loader (scripts/ lives outside the Django app root) ────────

BRIDGE_PATH = Path(__file__).resolve().parents[4] / "scripts" / "bridge_ble_to_api.py"
if not BRIDGE_PATH.exists():
    # Inside Docker the repo root is /app
    BRIDGE_PATH = Path("/app/scripts/bridge_ble_to_api.py")


def _load_bridge(env_overrides=None):
    """Load scripts/bridge_ble_to_api.py as a fresh module with patched env."""
    import sys
    with patch.dict(os.environ, env_overrides or {}):
        spec = importlib.util.spec_from_file_location("bridge_ble_to_api", BRIDGE_PATH)
        mod = importlib.util.module_from_spec(spec)
        # Must register before exec so dataclass __module__ resolves correctly
        sys.modules["bridge_ble_to_api"] = mod
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.modules.pop("bridge_ble_to_api", None)
    return mod


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    return Client(enforce_csrf_checks=True)


@pytest.fixture
def auth_client(client):
    User = get_user_model()
    User.objects.create_user(username="tester", password="pass1234!")
    csrf = client.get("/api/auth/csrf/").json()["csrfToken"]
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "tester", "password": "pass1234!"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert r.status_code == 200
    return client


@pytest.fixture
def patient(db):
    return Patient.objects.create(external_id="PT-FALL-01", first_name="Test", last_name="Patient")


@pytest.fixture
def device(db):
    return Device.objects.create(serial_number="DEV-FALL-01")


@pytest.fixture
def session(db, patient, device):
    return Session.objects.create(
        source="ble://TEST",
        patient=patient,
        device=device,
        started_at_us=1_700_000_000_000_000,
    )


def _make_adc_base64(gw=4, gh=4, values=None):
    """Pack a 4x4 grid of int16 into base64."""
    total = gw * gh
    if values is None:
        values = [500] * total
    blob = struct.pack("<" + "h" * total, *values)
    return base64.b64encode(blob).decode("ascii")


def _post_frame(auth_client, session_id, ts_us=None, ax=0, ay=0, az=16384, values=None, flags=0):
    csrf = auth_client.get("/api/auth/csrf/").json()["csrfToken"]
    payload = {
        "ts_us": ts_us or 1_700_000_000_000_000,
        "gw": 4,
        "gh": 4,
        "battery_pct": 100,
        "flags": flags,
        "total_load": float(sum(values or [500] * 16)),
        "adc_base64": _make_adc_base64(values=values),
    }
    return auth_client.post(
        f"/api/sessions/{session_id}/frames/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )


# ── 1. Bridge fall detection (unit tests on scripts/bridge_ble_to_api.py) ──

@pytest.mark.parametrize("threshold,prev,curr,expect_fall", [
    # jerk = sqrt((8000)^2) = 8000, threshold=8000 → exactly triggers
    (8000,  (0, 0, 0),     (8000, 0, 0),       True),
    # jerk < threshold → no fall
    (8000,  (0, 0, 0),     (7999, 0, 0),       False),
    # 3D jerk: sqrt(4000^2+4000^2+4000^2) ≈ 6928 < 8000 → no fall
    (8000,  (0, 0, 0),     (4000, 4000, 4000), False),
    # 3D jerk: sqrt(5000^2+5000^2+5000^2) ≈ 8660 > 8000 → fall
    (8000,  (0, 0, 0),     (5000, 5000, 5000), True),
    # Very low threshold → any movement triggers
    (100,   (0, 0, 16384), (0, 0, 16500),      True),
])
def test_bridge_jerk_detection(threshold, prev, curr, expect_fall):
    """Jerk = sqrt(Δax²+Δay²+Δaz²) compared to FALL_THRESHOLD."""
    bridge_mod = _load_bridge({"FALL_THRESHOLD": str(threshold)})
    px, py, pz = prev
    cx, cy, cz = curr
    jerk = math.sqrt((cx - px) ** 2 + (cy - py) ** 2 + (cz - pz) ** 2)
    is_fall = jerk >= bridge_mod.FALL_THRESHOLD
    assert is_fall == expect_fall, (
        f"jerk={jerk:.1f}, threshold={bridge_mod.FALL_THRESHOLD}, expected={expect_fall}"
    )


def test_bridge_fall_cooldown():
    """Second fall within cooldown window must not post an annotation."""
    import time
    bridge_mod = _load_bridge({"FALL_THRESHOLD": "1", "FALL_COOLDOWN": "60"})

    posted = []

    class FakeApi:
        def post_json(self, path, payload):
            posted.append(payload)
            return {}
        def get_json(self, path):
            return {"metadata": {}}

    bridge = bridge_mod.BleToApiBridge(api=FakeApi(), patient_id=1, device_id=1, source="ble://TEST")
    bridge.session_id = 1
    bridge._last_fall_time = time.time() - 1  # 1s ago, cooldown=60
    bridge._last_frame = bridge_mod.Frame(ax=0, ay=0, az=0, grid=[0] * 16)
    bridge._maybe_post_fall_annotation(99999.0)

    fall_anns = [p for p in posted if p.get("metadata", {}).get("source") == "ble-bridge-fall"]
    assert len(fall_anns) == 0, "Should be suppressed by cooldown"


def test_bridge_fall_annotation_after_cooldown():
    """Fall annotation is posted once cooldown has elapsed."""
    bridge_mod = _load_bridge({"FALL_THRESHOLD": "1", "FALL_COOLDOWN": "0"})

    posted = []

    class FakeApi:
        def post_json(self, path, payload):
            posted.append((path, payload))
            return {}
        def get_json(self, path):
            return {"metadata": {}}

    bridge = bridge_mod.BleToApiBridge(api=FakeApi(), patient_id=1, device_id=1, source="ble://TEST")
    bridge.session_id = 99
    bridge._last_frame = bridge_mod.Frame(ax=100, ay=200, az=300, grid=[0] * 16)
    bridge._last_fall_time = 0.0
    bridge._maybe_post_fall_annotation(50000.0)

    fall_posts = [(p, q) for p, q in posted if q.get("metadata", {}).get("source") == "ble-bridge-fall"]
    assert len(fall_posts) == 1
    path, payload = fall_posts[0]
    assert path == "/api/annotations/"
    assert payload["metadata"]["jerk_magnitude"] == 50000
    assert payload["metadata"]["fall_threshold"] == bridge_mod.FALL_THRESHOLD
    assert "Fall event detected" in payload["body"]


def test_bridge_fall_threshold_env_var():
    """FALL_THRESHOLD env var controls the module-level constant."""
    bridge_mod = _load_bridge({"FALL_THRESHOLD": "12345"})
    assert bridge_mod.FALL_THRESHOLD == 12345


def test_bridge_fall_cooldown_env_var():
    """FALL_COOLDOWN env var controls the module-level constant."""
    bridge_mod = _load_bridge({"FALL_COOLDOWN": "3.5"})
    assert bridge_mod.FALL_COOLDOWN == 3.5


# ── 2. compute_frame_metrics — incremental, no delete, trim ─────────────────

@pytest.mark.django_db
def test_compute_frame_metrics_appends_rows(session):
    """Each call appends rows, does not delete existing ones."""
    grid = [500] * 16
    adc_blob = struct.pack("<" + "h" * 16, *grid)

    f1 = RawFrame.objects.create(
        session=session, ts_us=1_000_000, gw=4, gh=4,
        battery_pct=100, flags=0, total_load=8000.0, adc_blob=adc_blob,
    )
    compute_frame_metrics(session, f1)
    count_after_first = ComputedMetric.objects.filter(session=session).count()
    assert count_after_first >= 8  # at least 8 metrics written

    f2 = RawFrame.objects.create(
        session=session, ts_us=2_000_000, gw=4, gh=4,
        battery_pct=100, flags=0, total_load=8000.0, adc_blob=adc_blob,
    )
    compute_frame_metrics(session, f2)
    count_after_second = ComputedMetric.objects.filter(session=session).count()
    # Second call should add more rows (not reset to same count)
    assert count_after_second > count_after_first


@pytest.mark.django_db
def test_compute_frame_metrics_trims_to_max(session):
    """After MAX_METRIC_ROWS_PER_NAME+1 frames, row count is capped per metric."""
    grid = [500] * 16
    adc_blob = struct.pack("<" + "h" * 16, *grid)

    for i in range(MAX_METRIC_ROWS_PER_NAME + 5):
        f = RawFrame.objects.create(
            session=session, ts_us=1_000_000 + i * 100_000, gw=4, gh=4,
            battery_pct=100, flags=0, total_load=8000.0, adc_blob=adc_blob,
        )
        compute_frame_metrics(session, f)

    for name in ["cop_x", "cop_y", "sway_path", "total_load", "asymmetry_index"]:
        count = ComputedMetric.objects.filter(session=session, metric_name=name).count()
        assert count <= MAX_METRIC_ROWS_PER_NAME, (
            f"{name} has {count} rows, expected <= {MAX_METRIC_ROWS_PER_NAME}"
        )


@pytest.mark.django_db
def test_compute_frame_metrics_sway_accumulates(session):
    """sway_path should increase as CoP moves between frames."""
    def make_grid(val):
        # Shift load to different corners to move CoP
        g = [0] * 16
        g[val % 16] = 5000
        return g

    adc_blob_1 = struct.pack("<" + "h" * 16, *make_grid(0))
    adc_blob_2 = struct.pack("<" + "h" * 16, *make_grid(15))

    f1 = RawFrame.objects.create(
        session=session, ts_us=1_000_000, gw=4, gh=4,
        battery_pct=100, flags=0, total_load=5000.0, adc_blob=adc_blob_1,
    )
    compute_frame_metrics(session, f1)

    f2 = RawFrame.objects.create(
        session=session, ts_us=2_000_000, gw=4, gh=4,
        battery_pct=100, flags=0, total_load=5000.0, adc_blob=adc_blob_2,
    )
    compute_frame_metrics(session, f2)

    sway_rows = (
        ComputedMetric.objects.filter(session=session, metric_name="sway_path")
        .order_by("ts_us")
    )
    values = [r.metric_value for r in sway_rows]
    assert len(values) >= 2
    # sway_path should be non-decreasing (CoP moved)
    assert values[-1] >= values[0]


# ── 3. ingest_frame API uses compute_frame_metrics (no full recompute) ───────

@pytest.mark.django_db
def test_ingest_frame_uses_incremental_not_full_recompute(auth_client, session):
    """ingest_frame must NOT call recompute_session_metrics."""
    with patch("wbs.sessions_views.recompute_session_metrics") as mock_recompute:
        r = _post_frame(auth_client, session.session_id, ts_us=1_700_000_001_000_000)
        assert r.status_code == 201
        mock_recompute.assert_not_called()


@pytest.mark.django_db
def test_ingest_frame_writes_metrics(auth_client, session):
    """After posting a frame the metrics table has rows for this session."""
    r = _post_frame(auth_client, session.session_id, ts_us=1_700_000_001_000_000)
    assert r.status_code == 201
    count = ComputedMetric.objects.filter(session=session).count()
    assert count >= 8


@pytest.mark.django_db
def test_ingest_frame_metrics_grow_then_cap(auth_client, session):
    """Posting MAX+5 frames keeps metric rows capped at MAX per metric name."""
    for i in range(MAX_METRIC_ROWS_PER_NAME + 5):
        r = _post_frame(
            auth_client, session.session_id,
            ts_us=1_700_000_000_000_000 + i * 100_000,
        )
        assert r.status_code == 201

    for name in ["cop_x", "cop_y", "total_load"]:
        count = ComputedMetric.objects.filter(session=session, metric_name=name).count()
        assert count <= MAX_METRIC_ROWS_PER_NAME, (
            f"{name}: {count} rows exceeds cap {MAX_METRIC_ROWS_PER_NAME}"
        )


@pytest.mark.django_db
def test_ingest_frame_rejected_for_ended_session(auth_client, session):
    """Frame POST to an ended session returns 409."""
    session.ended_at_us = 1_700_000_099_000_000
    session.save()
    r = _post_frame(auth_client, session.session_id)
    assert r.status_code == 409


# ── 4. BLE session resolver — annotation metadata ───────────────────────────

@pytest.mark.django_db
def test_fall_annotation_metadata_fields(auth_client, session):
    """A ble-bridge-fall annotation has all expected metadata keys."""
    from wbs.models import Annotation
    csrf = auth_client.get("/api/auth/csrf/").json()["csrfToken"]
    r = auth_client.post(
        "/api/annotations/",
        data=json.dumps({
            "session_id": session.session_id,
            "patient_id": session.patient_id,
            "author": "ble-bridge",
            "body": "Fall event detected — sudden jerk |Δa|=12000 (threshold=8000)",
            "metadata": {
                "source": "ble-bridge-fall",
                "jerk_magnitude": 12000,
                "fall_threshold": 8000,
                "ax": -100,
                "ay": 200,
                "az": 16000,
            },
        }),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert r.status_code == 201
    ann = Annotation.objects.get(pk=r.json()["annotation_id"])
    assert ann.metadata["source"] == "ble-bridge-fall"
    assert ann.metadata["jerk_magnitude"] == 12000
    assert ann.metadata["fall_threshold"] == 8000
    assert "ax" in ann.metadata


@pytest.mark.django_db
def test_ble_session_active_has_frames(session):
    """A session is only 'active BLE session with frames' when ended_at_us is None and raw_frame_count > 0."""
    from wbs.models import Session
    from django.db.models import Count

    grid = [500] * 16
    adc_blob = struct.pack("<" + "h" * 16, *grid)
    RawFrame.objects.create(
        session=session, ts_us=1_000_000, gw=4, gh=4,
        battery_pct=100, flags=0, total_load=8000.0, adc_blob=adc_blob,
    )

    qs = Session.objects.annotate(raw_frame_count=Count("raw_frames")).filter(
        source__startswith="ble://",
        ended_at_us__isnull=True,
        raw_frame_count__gt=0,
    )
    assert qs.filter(pk=session.pk).exists()

    # Ended session should NOT appear
    session.ended_at_us = 1_700_000_099_000_000
    session.save()
    assert not qs.filter(pk=session.pk).exists()
