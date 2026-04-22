#!/usr/bin/env python3
"""
bridge_ble_to_api.py — STEPPA BLE → /api/live-frame/

Reads BLE notifications from the STEPPA insole and POSTs each parsed
frame directly to /api/live-frame/ (no session, no auth, no DB).
The Django view stores the latest frame in memory; the browser polls it.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import struct
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib import request
from urllib.error import HTTPError

from bleak import BleakClient, BleakScanner

DEVICE_NAME = "STEPPA"
UART_TX_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"

GW = 4
GH = 4

# ── Fall detection ───────────────────────────────────────────────────────────
# Jerk = magnitude of change in accel vector between consecutive frames.
# STEPPA ADC units: ~16384 counts ≈ 1 g on az at rest.
# 8000 ≈ 0.5 g/frame sudden change — adjust down to make more sensitive.
FALL_THRESHOLD = 8000   # ADC counts
FALL_COOLDOWN  = 3.0    # seconds between successive fall alerts (de-bounce)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Frame:
    ax: int
    ay: int
    az: int
    grid: List[int]


def parse_steppa_line(line: str) -> Frame:
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
            key, value = key.strip(), value.strip()
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
        elif current_sensor is not None and part:
            sensors[current_sensor].append(int(part))

    if ax is None or ay is None or az is None:
        raise ValueError(f"missing accel fields: {line}")

    s0 = sensors.get("S0", [])
    s1 = sensors.get("S1", [])
    s2 = sensors.get("S2", [])
    s3 = sensors.get("S3", [])

    grid = [
        s0[0] if len(s0) > 0 else 0, s0[1] if len(s0) > 1 else 0, 0, 0,
        s1[0] if len(s1) > 0 else 0, s1[1] if len(s1) > 1 else 0,
        s1[2] if len(s1) > 2 else 0, s1[3] if len(s1) > 3 else 0,
        s2[0] if len(s2) > 0 else 0, s2[1] if len(s2) > 1 else 0,
        s2[2] if len(s2) > 2 else 0, s2[3] if len(s2) > 3 else 0,
        s3[0] if len(s3) > 0 else 0, s3[1] if len(s3) > 1 else 0, 0, 0,
    ]
    return Frame(ax=ax, ay=ay, az=az, grid=grid)


def post_frame(base_url: str, frame: Frame, frames_sent: int, is_fall: bool = False) -> None:
    adc_blob = struct.pack("<" + "h" * (GW * GH), *frame.grid)
    payload = {
        "adc_base64":  base64.b64encode(adc_blob).decode("ascii"),
        "gw":          GW,
        "gh":          GH,
        "total_load":  float(sum(frame.grid)),
        "battery_pct": 100,
        "ax":          frame.ax,
        "ay":          frame.ay,
        "az":          frame.az,
        "flags":       1 if is_fall else 0,
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url}/api/live-frame/",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=2) as resp:
            resp.read()
        print(f"frame {frames_sent:5d}  load={payload['total_load']:.0f}  ax={frame.ax:6d}  ay={frame.ay:6d}  az={frame.az:6d}")
    except (HTTPError, OSError) as exc:
        print(f"[warn] POST failed: {exc}", file=sys.stderr)


async def find_device(name: str):
    for d in await BleakScanner.discover(timeout=5.0):
        if d.name == name:
            return d
    return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--device-name", default=DEVICE_NAME)
    args = ap.parse_args()

    device = await find_device(args.device_name)
    if not device:
        print(f"Device '{args.device_name}' not found", file=sys.stderr)
        return 2

    print(f"Found: {device.name} ({device.address})")

    buffer = ""
    frames_sent = 0
    prev_ax: Optional[int] = None
    prev_ay: Optional[int] = None
    prev_az: Optional[int] = None
    last_fall_time: float = 0.0

    def handle_notify(_sender: int, data: bytearray) -> None:
        nonlocal buffer, frames_sent, prev_ax, prev_ay, prev_az, last_fall_time
        buffer += data.decode("utf-8", errors="replace")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            try:
                frame = parse_steppa_line(line)
                frames_sent += 1

                # ── Fall detection ──────────────────────────────────────────
                is_fall = False
                if prev_ax is not None:
                    jerk = (
                        (frame.ax - prev_ax) ** 2 +
                        (frame.ay - prev_ay) ** 2 +
                        (frame.az - prev_az) ** 2
                    ) ** 0.5
                    now = time.time()
                    if jerk >= FALL_THRESHOLD and (now - last_fall_time) >= FALL_COOLDOWN:
                        is_fall = True
                        last_fall_time = now
                        print()
                        print(f"{'!'*60}")
                        print(f"  ⚠  FALL DETECTED  frame={frames_sent}")
                        print(f"     jerk={jerk:.0f}  threshold={FALL_THRESHOLD}")
                        print(f"     ax={frame.ax}  ay={frame.ay}  az={frame.az}")
                        print(f"{'!'*60}")
                        print()
                prev_ax, prev_ay, prev_az = frame.ax, frame.ay, frame.az
                # ───────────────────────────────────────────────────────────

                post_frame(args.base_url, frame, frames_sent, is_fall)
            except Exception as exc:
                print(f"[skip] {line!r} ({exc})", file=sys.stderr)

    try:
        async with BleakClient(device.address) as client:
            print("Connected — streaming. Ctrl+C to stop.")
            await client.start_notify(UART_TX_UUID, handle_notify)
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("\nStopped.")
            finally:
                try:
                    await client.stop_notify(UART_TX_UUID)
                except Exception:
                    pass
    except Exception as exc:
        print(f"BLE error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
