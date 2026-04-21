#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import json
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
        self.post_json("/api/auth/login/", {"username": username, "password": password})


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


def frame_to_payload(frame: Frame) -> Dict[str, Any]:
    ts_us = int(time.time() * 1_000_000)
    battery_pct = 100
    flags = 0
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
    ) -> None:
        self.api = api
        self.patient_id = patient_id
        self.device_id = device_id
        self.source = source
        self.notes = notes
        self.session_id: Optional[int] = None
        self.buffer = ""
        self.frames_sent = 0

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

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return

        print("RAW:", line)
        frame = parse_steppa_line(line)
        payload = frame_to_payload(frame)

        self.start_session()
        assert self.session_id is not None
        self.api.post_json(f"/api/sessions/{self.session_id}/frames/", payload)
        self.frames_sent += 1
        print(f"Posted frame {self.frames_sent} to session {self.session_id}")


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