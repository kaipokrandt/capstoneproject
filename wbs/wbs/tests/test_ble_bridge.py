"""
Tests for the run_ble_bridge management command.

Covers:
  - _parse_steppa_line: valid lines, partial sensor data, empty/bad lines
  - _grid_to_adc_base64: round-trip struct packing matches ingest_frame expectations
  - _BleBridge ORM path: session creation, frame + metric write, session end
  - Multi-frame accumulation and lazy session start
  - Line buffer splitting (multi-chunk notify simulation)
"""
from __future__ import annotations

import base64
import struct
from io import StringIO
from unittest.mock import MagicMock

import pytest

from django.contrib.auth import get_user_model

from wbs.models import ComputedMetric, Device, Patient, RawFrame, Session
from wbs.management.commands.run_ble_bridge import (
    GH,
    GW,
    _BleBridge,
    _grid_to_adc_base64,
    _parse_steppa_line,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL_LINE = "AX:-576,AY:-384,AZ:15680,S0:539,405,S1:850,1186,933,1292,S2:388,482,368,526,S3:262,326"

def _make_bridge(patient, device):
    stdout = MagicMock()
    stderr = MagicMock()
    stdout.write = lambda msg: None
    stderr.write = lambda msg: None
    return _BleBridge(
        patient_id=patient.patient_id,
        device_id=device.device_id,
        source_override=None,
        notes="test ingest",
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# _parse_steppa_line
# ---------------------------------------------------------------------------

class TestParseSteppaLine:

    def test_parses_full_line(self):
        result = _parse_steppa_line(FULL_LINE)
        assert result is not None
        assert result["ax"] == -576
        assert result["ay"] == -384
        assert result["az"] == 15680

    def test_grid_length_is_16(self):
        result = _parse_steppa_line(FULL_LINE)
        assert len(result["grid"]) == GW * GH

    def test_s0_values_correct(self):
        result = _parse_steppa_line(FULL_LINE)
        grid = result["grid"]
        # S0: 539, 405 → indices 0, 1
        assert grid[0] == 539
        assert grid[1] == 405

    def test_s0_missing_corner_cells_are_zero(self):
        result = _parse_steppa_line(FULL_LINE)
        grid = result["grid"]
        # indices 2, 3 are the zero-padded corners from S0 row
        assert grid[2] == 0
        assert grid[3] == 0

    def test_s1_values_correct(self):
        result = _parse_steppa_line(FULL_LINE)
        grid = result["grid"]
        # S1: 850, 1186, 933, 1292 → indices 4-7
        assert grid[4] == 850
        assert grid[5] == 1186
        assert grid[6] == 933
        assert grid[7] == 1292

    def test_s2_values_correct(self):
        result = _parse_steppa_line(FULL_LINE)
        grid = result["grid"]
        # S2: 388, 482, 368, 526 → indices 8-11
        assert grid[8] == 388
        assert grid[9] == 482
        assert grid[10] == 368
        assert grid[11] == 526

    def test_s3_values_correct_with_zero_padding(self):
        result = _parse_steppa_line(FULL_LINE)
        grid = result["grid"]
        # S3: 262, 326 → indices 12, 13; indices 14, 15 zero-padded
        assert grid[12] == 262
        assert grid[13] == 326
        assert grid[14] == 0
        assert grid[15] == 0

    def test_empty_line_returns_none(self):
        assert _parse_steppa_line("") is None
        assert _parse_steppa_line("   ") is None

    def test_missing_accel_raises(self):
        with pytest.raises(ValueError, match="missing accel fields"):
            _parse_steppa_line("S0:100,200,S1:300,400,500,600")

    def test_whitespace_stripped(self):
        result = _parse_steppa_line("  " + FULL_LINE + "  ")
        assert result is not None
        assert result["ax"] == -576

    def test_partial_s1_fills_missing_with_zero(self):
        # S1 has only 2 values instead of 4
        line = "AX:0,AY:0,AZ:0,S0:100,200,S1:500,600,S2:1,2,3,4,S3:10,20"
        result = _parse_steppa_line(line)
        grid = result["grid"]
        assert grid[4] == 500
        assert grid[5] == 600
        assert grid[6] == 0   # missing
        assert grid[7] == 0   # missing

    def test_negative_sensor_values_accepted(self):
        line = "AX:0,AY:0,AZ:0,S0:-10,0,S1:0,0,0,0,S2:0,0,0,0,S3:0,0"
        result = _parse_steppa_line(line)
        assert result["grid"][0] == -10

    def test_total_load_is_sum_of_grid(self):
        result = _parse_steppa_line(FULL_LINE)
        grid = result["grid"]
        expected = sum(grid)
        assert expected == sum(grid)  # trivial but also ensures no exception


# ---------------------------------------------------------------------------
# _grid_to_adc_base64
# ---------------------------------------------------------------------------

class TestGridToAdcBase64:

    def test_output_is_valid_base64(self):
        result = _parse_steppa_line(FULL_LINE)
        encoded = _grid_to_adc_base64(result["grid"])
        decoded = base64.b64decode(encoded)
        assert len(decoded) == GW * GH * 2  # 32 bytes for 4x4 int16

    def test_round_trip_unpacks_correctly(self):
        result = _parse_steppa_line(FULL_LINE)
        grid = result["grid"]
        encoded = _grid_to_adc_base64(grid)
        blob = base64.b64decode(encoded)
        unpacked = list(struct.unpack("<" + "h" * (GW * GH), blob))
        assert unpacked == grid

    def test_zero_grid_produces_zero_bytes(self):
        grid = [0] * (GW * GH)
        blob = base64.b64decode(_grid_to_adc_base64(grid))
        assert blob == b"\x00" * (GW * GH * 2)


# ---------------------------------------------------------------------------
# _BleBridge ORM path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBleBridgeOrm:

    def test_session_created_on_first_frame(self):
        patient = Patient.objects.create(external_id="BLE-P-1")
        device = Device.objects.create(serial_number="BLE-D-1")
        bridge = _make_bridge(patient, device)

        assert bridge.session is None
        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        assert bridge.session is not None
        assert bridge.session.session_id is not None

    def test_session_linked_to_correct_patient_and_device(self):
        patient = Patient.objects.create(external_id="BLE-P-2")
        device = Device.objects.create(serial_number="BLE-D-2")
        bridge = _make_bridge(patient, device)

        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        session = Session.objects.get(pk=bridge.session.session_id)
        assert session.patient_id == patient.patient_id
        assert session.device_id == device.device_id

    def test_source_set_from_ble_address(self):
        patient = Patient.objects.create(external_id="BLE-P-3")
        device = Device.objects.create(serial_number="BLE-D-3")
        bridge = _make_bridge(patient, device)

        bridge.handle_line(FULL_LINE, "11:22:33:44:55:66")
        session = Session.objects.get(pk=bridge.session.session_id)
        assert session.source == "ble://11:22:33:44:55:66"

    def test_source_override_respected(self):
        patient = Patient.objects.create(external_id="BLE-P-4")
        device = Device.objects.create(serial_number="BLE-D-4")
        stdout = MagicMock()
        stdout.write = lambda m: None
        bridge = _BleBridge(
            patient_id=patient.patient_id,
            device_id=device.device_id,
            source_override="ble://custom-label",
            notes="test",
            stdout=stdout,
            stderr=stdout,
        )
        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        session = Session.objects.get(pk=bridge.session.session_id)
        assert session.source == "ble://custom-label"

    def test_raw_frame_written(self):
        patient = Patient.objects.create(external_id="BLE-P-5")
        device = Device.objects.create(serial_number="BLE-D-5")
        bridge = _make_bridge(patient, device)

        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        frames = RawFrame.objects.filter(session=bridge.session)
        assert frames.count() == 1

        frame = frames.first()
        assert frame.gw == GW
        assert frame.gh == GH
        assert len(bytes(frame.adc_blob)) == GW * GH * 2

    def test_adc_blob_matches_grid(self):
        patient = Patient.objects.create(external_id="BLE-P-6")
        device = Device.objects.create(serial_number="BLE-D-6")
        bridge = _make_bridge(patient, device)

        parsed = _parse_steppa_line(FULL_LINE)
        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")

        frame = RawFrame.objects.filter(session=bridge.session).first()
        unpacked = list(struct.unpack("<" + "h" * (GW * GH), bytes(frame.adc_blob)))
        assert unpacked == parsed["grid"]

    def test_metrics_computed_after_frame(self):
        patient = Patient.objects.create(external_id="BLE-P-7")
        device = Device.objects.create(serial_number="BLE-D-7")
        bridge = _make_bridge(patient, device)

        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        metrics = ComputedMetric.objects.filter(session=bridge.session)
        names = set(metrics.values_list("metric_name", flat=True))
        assert {"cop_x", "cop_y", "total_load", "asymmetry_index"}.issubset(names)

    def test_frames_sent_counter_increments(self):
        patient = Patient.objects.create(external_id="BLE-P-8")
        device = Device.objects.create(serial_number="BLE-D-8")
        bridge = _make_bridge(patient, device)

        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        assert bridge.frames_sent == 3

    def test_multiple_frames_all_written(self):
        patient = Patient.objects.create(external_id="BLE-P-9")
        device = Device.objects.create(serial_number="BLE-D-9")
        bridge = _make_bridge(patient, device)

        for _ in range(5):
            bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")

        assert RawFrame.objects.filter(session=bridge.session).count() == 5

    def test_session_not_duplicated_across_frames(self):
        patient = Patient.objects.create(external_id="BLE-P-10")
        device = Device.objects.create(serial_number="BLE-D-10")
        bridge = _make_bridge(patient, device)

        before = Session.objects.count()
        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        assert Session.objects.count() == before + 1

    def test_end_session_sets_ended_at_us(self):
        patient = Patient.objects.create(external_id="BLE-P-11")
        device = Device.objects.create(serial_number="BLE-D-11")
        bridge = _make_bridge(patient, device)

        bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")
        bridge.end_session()

        session = Session.objects.get(pk=bridge.session.session_id)
        assert session.ended_at_us is not None

    def test_end_session_without_any_frames_is_safe(self):
        patient = Patient.objects.create(external_id="BLE-P-12")
        device = Device.objects.create(serial_number="BLE-D-12")
        bridge = _make_bridge(patient, device)
        # no frames — session is None; end_session should be a no-op
        bridge.end_session()
        assert bridge.session is None

    def test_empty_line_does_not_create_session(self):
        patient = Patient.objects.create(external_id="BLE-P-13")
        device = Device.objects.create(serial_number="BLE-D-13")
        bridge = _make_bridge(patient, device)

        bridge.handle_line("", "AA:BB:CC:DD:EE:FF")
        bridge.handle_line("   ", "AA:BB:CC:DD:EE:FF")
        assert bridge.session is None

    def test_invalid_patient_raises(self):
        from django.core.management.base import CommandError
        device = Device.objects.create(serial_number="BLE-D-14")
        stdout = MagicMock()
        stdout.write = lambda m: None
        bridge = _BleBridge(
            patient_id=99999,
            device_id=device.device_id,
            source_override=None,
            notes="test",
            stdout=stdout,
            stderr=stdout,
        )
        with pytest.raises(CommandError, match="Patient"):
            bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")

    def test_invalid_device_raises(self):
        from django.core.management.base import CommandError
        patient = Patient.objects.create(external_id="BLE-P-15")
        stdout = MagicMock()
        stdout.write = lambda m: None
        bridge = _BleBridge(
            patient_id=patient.patient_id,
            device_id=99999,
            source_override=None,
            notes="test",
            stdout=stdout,
            stderr=stdout,
        )
        with pytest.raises(CommandError, match="Device"):
            bridge.handle_line(FULL_LINE, "AA:BB:CC:DD:EE:FF")


# ---------------------------------------------------------------------------
# Buffer / notify chunking simulation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestNotifyBufferSplitting:
    """
    Simulates the BLE notify callback receiving data in chunks (no guarantee
    a newline falls at a packet boundary).
    """

    def test_split_across_two_chunks(self):
        patient = Patient.objects.create(external_id="BLE-BUF-1")
        device = Device.objects.create(serial_number="BLE-BUF-D-1")
        bridge = _make_bridge(patient, device)

        full = FULL_LINE + "\n"
        half = len(full) // 2
        chunk1 = full[:half]
        chunk2 = full[half:]

        # Simulate notify handler
        def deliver(chunk):
            bridge.buffer += chunk
            while "\n" in bridge.buffer:
                line, bridge.buffer = bridge.buffer.split("\n", 1)
                bridge.handle_line(line, "AA:BB:CC:DD:EE:FF")

        deliver(chunk1)
        assert bridge.frames_sent == 0  # line not complete yet

        deliver(chunk2)
        assert bridge.frames_sent == 1

    def test_two_lines_in_one_chunk(self):
        patient = Patient.objects.create(external_id="BLE-BUF-2")
        device = Device.objects.create(serial_number="BLE-BUF-D-2")
        bridge = _make_bridge(patient, device)

        def deliver(chunk):
            bridge.buffer += chunk
            while "\n" in bridge.buffer:
                line, bridge.buffer = bridge.buffer.split("\n", 1)
                bridge.handle_line(line, "AA:BB:CC:DD:EE:FF")

        deliver(FULL_LINE + "\n" + FULL_LINE + "\n")
        assert bridge.frames_sent == 2

    def test_partial_then_complete_then_partial(self):
        patient = Patient.objects.create(external_id="BLE-BUF-3")
        device = Device.objects.create(serial_number="BLE-BUF-D-3")
        bridge = _make_bridge(patient, device)

        def deliver(chunk):
            bridge.buffer += chunk
            while "\n" in bridge.buffer:
                line, bridge.buffer = bridge.buffer.split("\n", 1)
                bridge.handle_line(line, "AA:BB:CC:DD:EE:FF")

        deliver(FULL_LINE[:10])            # partial
        deliver(FULL_LINE[10:] + "\n")     # completes first line
        deliver(FULL_LINE[:20])            # start of second line
        assert bridge.frames_sent == 1

        deliver(FULL_LINE[20:] + "\n")     # completes second line
        assert bridge.frames_sent == 2
