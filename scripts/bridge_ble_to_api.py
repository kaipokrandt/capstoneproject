#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import struct
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib import request
from urllib.error import HTTPError
from http.cookiejar import CookieJar

from bleak import BleakClient, BleakScanner

DEVICE_NAME = "STEPPA"
UART_TX_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"  # notify from board -> Mac

GW = 4
GH = 4

# ── Fall detection config (all tunable via env vars) ────────────────────────
# STEPPA signed 16-bit ADC counts; ~16384 ≈ 1 g on az axis at rest.
#
#  FALL_THRESHOLD   — jerk magnitude |Δa| between consecutive frames in ADC
#                     units.  Measures sudden change, not absolute force.
#                     ~8000 ≈ 0.5 g/frame change — a light tap triggers it.
#                     Lower = more sensitive.
#
#  FALL_COOLDOWN    — seconds between successive fall annotations (de-bounce).
# ────────────────────────────────────────────────────────────────────────────
FALL_THRESHOLD  = int(float(os.environ.get("FALL_THRESHOLD", "8000")))
FALL_COOLDOWN   = float(os.environ.get("FALL_COOLDOWN",  "5.0"))
FALL_FLAG_BIT   = 0x01     # bit 0 of RawFrame.flags


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie_jar = CookieJar()
        self.opener = request.build_opener(request.HTTPCookieProcessor(self.cookie_jar))

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _json_bytes(self, payload: Dict[str, Any]) -> bytes:
        return json.dumps(payload).encode("utf-8")

    def _csrf(self) -> str:
        req = request.Request(self._url("/api/auth/csrf/"), method="GET")
        with self.opener.open(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["csrfToken"]

    def get_json(self, path: str) -> Dict[str, Any]:
        req = request.Request(self._url(path), method="GET")
        try:
            with self.opener.open(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GET {path} failed ({e.code}): {body}") from e

    def post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        csrf = self._csrf()
        req = request.Request(
            self._url(path),
            data=self._json_bytes(payload),
            headers={
                "Content-Type": "application/json",
                "X-CSRFToken": csrf,
            },
            method="POST",
        )
        try:
            with self.opener.open(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"POST {path} failed ({e.code}): {body}") from e

    def login(self, username: str, password: str) -> None:
        try:
            self.post_json("/api/auth/login/", {"username": username, "password": password})
        except RuntimeError as exc:
            if "(401)" in str(exc):
                raise RuntimeError(
                    f"Login failed for user '{username}' — check BLE_USERNAME/BLE_PASSWORD in .env "
                    f"and ensure the Docker superuser was bootstrapped correctly."
                ) from exc
            raise


@dataclass
class Frame:
    ax: int
    ay: int
    az: int
    grid: List[int]


def parse_steppa_line(line: str) -> Frame:
    """
    Example current firmware line:
    AX:-576,AY:-384,AZ:15680,S0:539,405,S1:850,1186,933,1292,S2:388,482,368,526,S3:262,326
    """
    line = line.strip()
    if not line:
        raise ValueError("empty line")

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
        raise ValueError(f"missing accel fields in line: {line}")

    s0 = sensors.get("S0", [])
    s1 = sensors.get("S1", [])
    s2 = sensors.get("S2", [])
    s3 = sensors.get("S3", [])

    # Current firmware only sends 12 of 16 cells.
    # Fill missing cells with 0 for now so the backend still accepts a 4x4 frame.
    grid = [
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

    return Frame(ax=ax, ay=ay, az=az, grid=grid)


def frame_to_payload(frame: Frame, flags: int = 0) -> Dict[str, Any]:
    ts_us = int(time.time() * 1_000_000)
    battery_pct = 100
    total_load = float(sum(frame.grid))

    adc_blob = struct.pack("<" + "h" * (GW * GH), *frame.grid)

    return {
        "ts_us": ts_us,
        "gw": GW,
        "gh": GH,
        "battery_pct": battery_pct,
        "flags": flags,
        "total_load": total_load,
        "adc_base64": base64.b64encode(adc_blob).decode("ascii"),
    }


class BleToApiBridge:
    def __init__(
        self,
        api: ApiClient,
        patient_id: int,
        device_id: int,
        source: str,
        notes: str = "",
        log_interval: float = 5.0,
    ) -> None:
        self.api = api
        self.patient_id = patient_id
        self.device_id = device_id
        self.source = source
        self.notes = notes
        self.session_id: Optional[int] = None
        self.buffer = ""
        self.frames_sent = 0
        self.log_interval = log_interval
        self._last_log_time: float = 0.0
        self._last_frame: Optional[Frame] = None
        self._frames_since_log: int = 0
        self._imu_offset: Dict[str, int] = {"ax": 0, "ay": 0, "az": 0}
        self._last_offset_check: float = 0.0
        self._offset_check_interval: float = 2.0  # poll for new calibration every 2s
        self._last_fall_time: float = 0.0
        self._prev_ax: Optional[int] = None
        self._prev_ay: Optional[int] = None
        self._prev_az: Optional[int] = None

    def _refresh_imu_offset(self) -> None:
        """Poll the API for an updated IMU offset and apply it locally."""
        now = time.time()
        if now - self._last_offset_check < self._offset_check_interval:
            return
        self._last_offset_check = now
        try:
            data = self.api.get_json(f"/api/devices/{self.device_id}/")
            offset = (data.get("metadata") or {}).get("imu_offset")
            if isinstance(offset, dict):
                new = {
                    "ax": int(offset.get("ax", 0)),
                    "ay": int(offset.get("ay", 0)),
                    "az": int(offset.get("az", 0)),
                }
                if new != self._imu_offset:
                    self._imu_offset = new
                    print(f"[calibration] IMU offset updated: ax={new['ax']} ay={new['ay']} az={new['az']}")
        except Exception as exc:
            print(f"[calibration] offset refresh failed: {exc}", file=sys.stderr)

    def start_session(self) -> None:
        if self.session_id is not None:
            return

        payload = {
            "source": self.source,
            "patient_id": self.patient_id,
            "device_id": self.device_id,
            "notes": self.notes or "BLE live ingest from STEPPA",
        }

        resp = self.api.post_json("/api/sessions/start/", payload)
        self.session_id = int(resp["session_id"])
        print(f"Started session {self.session_id}")

    def end_session(self) -> None:
        if self.session_id is None:
            return
        self.api.post_json(
            f"/api/sessions/{self.session_id}/end/",
            {"ended_at_us": int(time.time() * 1_000_000)},
        )
        print(f"Ended session {self.session_id}")

    def _maybe_post_fall_annotation(self, jerk: float) -> None:
        """Post a fall-event annotation, subject to cooldown."""
        now = time.time()
        if now - self._last_fall_time < FALL_COOLDOWN:
            return
        self._last_fall_time = now
        if self.session_id is None:
            return
        try:
            self.api.post_json("/api/annotations/", {
                "session_id": self.session_id,
                "patient_id": self.patient_id,
                "author": "ble-bridge",
                "body": f"Fall event detected — sudden jerk |\u0394a|={jerk:.0f} (threshold={FALL_THRESHOLD})",
                "metadata": {
                    "source": "ble-bridge-fall",
                    "jerk_magnitude": round(jerk),
                    "fall_threshold": FALL_THRESHOLD,
                    "ax": self._last_frame.ax if self._last_frame else None,
                    "ay": self._last_frame.ay if self._last_frame else None,
                    "az": self._last_frame.az if self._last_frame else None,
                },
            })
            print(f"[fall] annotation posted — |\u0394a|={jerk:.0f}")
        except Exception as exc:
            print(f"[fall] annotation post failed: {exc}", file=sys.stderr)

    def _maybe_post_log(self) -> None:
        now = time.time()
        if now - self._last_log_time < self.log_interval:
            return
        if self.session_id is None or self._last_frame is None:
            return
        f = self._last_frame
        total = sum(f.grid)
        accel_mag = round((f.ax ** 2 + f.ay ** 2 + f.az ** 2) ** 0.5)
        try:
            self.api.post_json("/api/annotations/", {
                "session_id": self.session_id,
                "patient_id": self.patient_id,
                "author": "ble-bridge",
                "body": (
                    f"BLE heartbeat — {self._frames_since_log} frames in last "
                    f"{self.log_interval:.0f}s | total_load={total} | |accel|={accel_mag}"
                ),
                "metadata": {
                    "source": "ble-bridge-heartbeat",
                    "frames_in_window": self._frames_since_log,
                    "total_frames": self.frames_sent,
                    "last_ax": f.ax,
                    "last_ay": f.ay,
                    "last_az": f.az,
                    "last_total_load": total,
                },
            })
            print(
                f"[ble-log] heartbeat — {self._frames_since_log} frames, "
                f"total_load={total}, |accel|={accel_mag}"
            )
        except Exception as exc:
            print(f"[ble-log] heartbeat post failed: {exc}", file=sys.stderr)
        self._last_log_time = now
        self._frames_since_log = 0

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return

        print("RAW:", line)
        frame = parse_steppa_line(line)

        # Apply IMU offset (zero calibration) — check for updated offset first
        self._refresh_imu_offset()
        frame = Frame(
            ax=frame.ax - self._imu_offset["ax"],
            ay=frame.ay - self._imu_offset["ay"],
            az=frame.az - self._imu_offset["az"],
            grid=frame.grid,
        )

        # ── Fall detection: jerk = change in accel vector between frames ──────
        is_fall = False
        jerk = 0.0
        if self._prev_ax is not None:
            jerk = ((frame.ax - self._prev_ax) ** 2 +
                    (frame.ay - self._prev_ay) ** 2 +
                    (frame.az - self._prev_az) ** 2) ** 0.5
            is_fall = jerk >= FALL_THRESHOLD
        self._prev_ax, self._prev_ay, self._prev_az = frame.ax, frame.ay, frame.az
        flags = FALL_FLAG_BIT if is_fall else 0
        # ──────────────────────────────────────────────────────────────────────────

        payload = frame_to_payload(frame, flags=flags)

        self.start_session()
        assert self.session_id is not None
        self.api.post_json(f"/api/sessions/{self.session_id}/frames/", payload)
        self.frames_sent += 1
        self._frames_since_log += 1
        self._last_frame = frame
        print(f"Posted frame {self.frames_sent} to session {self.session_id}" +
              (f" [FALL |\u0394a|={jerk:.0f}]" if is_fall else ""))

        if is_fall:
            self._maybe_post_fall_annotation(jerk)

        self._maybe_post_log()


async def find_device(device_name: str):
    devices = await BleakScanner.discover(timeout=5.0)
    for device in devices:
        if device.name == device_name:
            return device
    return None


async def main() -> int:
    ap = argparse.ArgumentParser(description="Bridge STEPPA BLE notifications into the Django API.")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--patient-id", required=True, type=int)
    ap.add_argument("--device-id", required=True, type=int)
    ap.add_argument("--device-name", default=DEVICE_NAME)
    ap.add_argument("--notes", default="live BLE ingest")
    args = ap.parse_args()

    api = ApiClient(args.base_url)
    api.login(args.username, args.password)

    device = await find_device(args.device_name)
    if not device:
        print(f"Device '{args.device_name}' not found", file=sys.stderr)
        return 2

    print(f"Found device: {device.name} ({device.address})")

    bridge = BleToApiBridge(
        api=api,
        patient_id=args.patient_id,
        device_id=args.device_id,
        source=f"ble://{device.address}",
        notes=args.notes,
    )

    def handle_notify(sender: int, data: bytearray) -> None:
        text = data.decode("utf-8", errors="replace")
        bridge.buffer += text

        while "\n" in bridge.buffer:
            line, bridge.buffer = bridge.buffer.split("\n", 1)
            try:
                bridge.handle_line(line)
            except Exception as e:
                print(f"Skipping bad line: {line!r} ({e})", file=sys.stderr)

    try:
        async with BleakClient(device.address) as client:
            print(f"Connected to {args.device_name}")
            await client.start_notify(UART_TX_UUID, handle_notify)
            print("Listening and forwarding frames. Press Ctrl+C to stop.")

            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("\nStopped by user")
            finally:
                try:
                    await client.stop_notify(UART_TX_UUID)
                except Exception:
                    pass
                bridge.end_session()

    except Exception as e:
        print(f"BLE connection error: {e}", file=sys.stderr)
        bridge.end_session()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))