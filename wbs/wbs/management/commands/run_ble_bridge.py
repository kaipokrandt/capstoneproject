"""
Management command: run_ble_bridge

Connects to the STEPPA BLE device, decodes incoming UART frames, and writes
them directly to the database via the Django ORM (same path as the HTTP API).

Usage:
    python wbs/manage.py run_ble_bridge \\
        --patient-id 1 --device-id 1

Optional:
    --device-name   STEPPA (default)
    --notes         "live BLE ingest"
    --source        overrides the ble://<address> source label

Requires:
    bleak (pip install bleak)
"""
from __future__ import annotations

import asyncio
import base64
import struct
import time
from typing import Dict, List, Optional

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

# ---------------------------------------------------------------------------
# BLE constants — identical to scripts/bridge_ble_to_api.py
# ---------------------------------------------------------------------------
DEFAULT_DEVICE_NAME = "STEPPA"
UART_TX_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"  # board -> host (notify)

GW = 4
GH = 4


# ---------------------------------------------------------------------------
# Packet parsing — exact same logic as scripts/bridge_ble_to_api.py
# ---------------------------------------------------------------------------

def _parse_steppa_line(line: str) -> Optional[Dict]:
    """
    Parse a single comma-separated firmware line such as:
        AX:-576,AY:-384,AZ:15680,S0:539,405,S1:850,1186,933,1292,S2:388,482,368,526,S3:262,326

    Returns a dict with keys ax, ay, az, grid (list[int] of GW*GH values)
    or None if the line is empty / unparseable.
    """
    line = line.strip()
    if not line:
        return None

    parts = line.split(",")
    ax = ay = az = None
    sensors: Dict[str, List[int]] = {}
    current_sensor: Optional[str] = None

    for part in parts:
        part = part.strip()
        if ":" in part:
            key, value = part.split(":", 1)
            key = key.strip()
            value = value.strip()

            if key in ("AX", "AY", "AZ"):
                iv = int(value)
                if key == "AX":
                    ax = iv
                elif key == "AY":
                    ay = iv
                else:
                    az = iv
                current_sensor = None
            elif key.startswith("S"):
                current_sensor = key
                sensors[current_sensor] = [int(value)]
        else:
            if current_sensor is not None and part:
                sensors[current_sensor].append(int(part))

    if ax is None or ay is None or az is None:
        raise ValueError(f"missing accel fields in line: {line!r}")

    s0 = sensors.get("S0", [])
    s1 = sensors.get("S1", [])
    s2 = sensors.get("S2", [])
    s3 = sensors.get("S3", [])

    # Firmware currently sends 12 of 16 cells.
    # S0 and S3 each provide 2 values; the 4 corner cells are zero-padded so
    # the 4x4 (GW*GH*2 = 32 bytes) blob always satisfies the backend contract.
    grid: List[int] = [
        s0[0] if len(s0) > 0 else 0,
        s0[1] if len(s0) > 1 else 0,
        0,
        0,

        s1[0] if len(s1) > 0 else 0,
        s1[1] if len(s1) > 1 else 0,
        s1[2] if len(s1) > 2 else 0,
        s1[3] if len(s1) > 3 else 0,

        s2[0] if len(s2) > 0 else 0,
        s2[1] if len(s2) > 1 else 0,
        s2[2] if len(s2) > 2 else 0,
        s2[3] if len(s2) > 3 else 0,

        s3[0] if len(s3) > 0 else 0,
        s3[1] if len(s3) > 1 else 0,
        0,
        0,
    ]

    return {"ax": ax, "ay": ay, "az": az, "grid": grid}


def _grid_to_adc_base64(grid: List[int]) -> str:
    """Pack grid as little-endian signed int16 blob and base64-encode it."""
    blob = struct.pack("<" + "h" * (GW * GH), *grid)
    return base64.b64encode(blob).decode("ascii")


# ---------------------------------------------------------------------------
# ORM bridge
# ---------------------------------------------------------------------------

class _BleBridge:
    """
    Owns the active session and writes frames directly via Django ORM.
    Mirrors BleToApiBridge from scripts/bridge_ble_to_api.py but uses the
    ORM instead of HTTP so it integrates cleanly with the rest of the app.
    """

    def __init__(
        self,
        patient_id: int,
        device_id: int,
        source_override: Optional[str],
        notes: str,
        stdout,
        stderr,
    ) -> None:
        # Import models here so they are resolved after Django setup.
        from wbs.models import CalibrationProfile, Device, Patient, RawFrame, Session
        from wbs.metrics_pipeline import recompute_session_metrics

        self._Patient = Patient
        self._Device = Device
        self._Session = Session
        self._RawFrame = RawFrame
        self._recompute = recompute_session_metrics

        self.patient_id = patient_id
        self.device_id = device_id
        self.source_override = source_override
        self.notes = notes
        self.stdout = stdout
        self.stderr = stderr

        self.session = None
        self.frames_sent = 0
        self.buffer = ""

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _ensure_session(self, source: str) -> None:
        if self.session is not None:
            return

        try:
            patient = self._Patient.objects.get(pk=self.patient_id)
        except self._Patient.DoesNotExist:
            raise CommandError(f"Patient id={self.patient_id} not found")

        try:
            device = self._Device.objects.get(pk=self.device_id)
        except self._Device.DoesNotExist:
            raise CommandError(f"Device id={self.device_id} not found")

        self.session = self._Session.objects.create(
            patient=patient,
            device=device,
            started_at_us=int(time.time() * 1_000_000),
            source=self.source_override or source,
            notes=self.notes or "BLE live ingest from STEPPA",
        )
        self.stdout.write(f"Started session {self.session.session_id}")

    def end_session(self) -> None:
        if self.session is None:
            return
        self.session.ended_at_us = int(time.time() * 1_000_000)
        self.session.save(update_fields=["ended_at_us"])
        self.stdout.write(
            f"Ended session {self.session.session_id} "
            f"({self.frames_sent} frames ingested)"
        )

    # ------------------------------------------------------------------
    # Frame handling
    # ------------------------------------------------------------------

    def handle_line(self, line: str, ble_address: str) -> None:
        line = line.strip()
        if not line:
            return

        self.stdout.write(f"RAW: {line}")
        parsed = _parse_steppa_line(line)
        if parsed is None:
            return

        ts_us = int(time.time() * 1_000_000)
        grid = parsed["grid"]
        total_load = float(sum(grid))
        adc_blob = struct.pack("<" + "h" * (GW * GH), *grid)

        self._ensure_session(source=f"ble://{ble_address}")

        frame = self._RawFrame.objects.create(
            session=self.session,
            ts_us=ts_us,
            gw=GW,
            gh=GH,
            battery_pct=100,
            flags=0,
            total_load=total_load,
            adc_blob=adc_blob,
        )

        metric_rows = self._recompute(self.session)
        self.frames_sent += 1
        self.stdout.write(
            f"Frame {self.frames_sent} → session {self.session.session_id} "
            f"(frame_id={frame.frame_id}, metrics={metric_rows})"
        )


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = (
        "Connect to the STEPPA BLE device and ingest pressure frames "
        "directly into the database (ORM path, no HTTP)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--patient-id",
            type=int,
            required=True,
            help="Primary key of the Patient record to link sessions to.",
        )
        parser.add_argument(
            "--device-id",
            type=int,
            required=True,
            help="Primary key of the Device record to link sessions to.",
        )
        parser.add_argument(
            "--device-name",
            default=DEFAULT_DEVICE_NAME,
            help=f"BLE advertised name to scan for (default: {DEFAULT_DEVICE_NAME}).",
        )
        parser.add_argument(
            "--notes",
            default="BLE live ingest from STEPPA",
            help="Session notes stored on the Session record.",
        )
        parser.add_argument(
            "--source",
            default=None,
            help=(
                "Override the session source label. "
                "Defaults to ble://<device_address>."
            ),
        )

    def handle(self, *args, **options):
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError:
            raise CommandError(
                "bleak is not installed. Run: pip install bleak"
            )

        bridge = _BleBridge(
            patient_id=options["patient_id"],
            device_id=options["device_id"],
            source_override=options.get("source"),
            notes=options["notes"],
            stdout=self.stdout,
            stderr=self.stderr,
        )

        device_name = options["device_name"]

        async def _run():
            self.stdout.write(f"Scanning for BLE device '{device_name}' ...")
            devices = await BleakScanner.discover(timeout=5.0)
            target = next((d for d in devices if d.name == device_name), None)

            if target is None:
                raise CommandError(f"BLE device '{device_name}' not found")

            self.stdout.write(
                f"Found: {target.name} ({target.address})"
            )

            def _on_notify(sender: int, data: bytearray) -> None:
                bridge.buffer += data.decode("utf-8", errors="replace")
                while "\n" in bridge.buffer:
                    line, bridge.buffer = bridge.buffer.split("\n", 1)
                    try:
                        bridge.handle_line(line, target.address)
                    except CommandError:
                        raise
                    except Exception as exc:
                        self.stderr.write(
                            f"Skipping bad line: {line!r} ({exc})"
                        )

            try:
                async with BleakClient(target.address) as client:
                    self.stdout.write(f"Connected to {device_name}")
                    await client.start_notify(UART_TX_UUID, _on_notify)
                    self.stdout.write(
                        "Listening and ingesting frames. Press Ctrl+C to stop."
                    )
                    try:
                        while True:
                            await asyncio.sleep(1)
                    except KeyboardInterrupt:
                        self.stdout.write("\nStopped by user.")
                    finally:
                        try:
                            await client.stop_notify(UART_TX_UUID)
                        except Exception:
                            pass
            except CommandError:
                raise
            except Exception as exc:
                raise CommandError(f"BLE connection error: {exc}") from exc
            finally:
                bridge.end_session()

        asyncio.run(_run())
