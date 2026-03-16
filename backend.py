#!/usr/bin/env python3
"""
wearable_balance_backend.py

Backend pipeline for the Wearable Balance Sensor project.

What it does
- Ingests binary packets produced by metric_traffic_generator.py or a live socket stream.
- Validates packet CRC and decodes the pressure grid.
- Computes per-frame metrics:
  * Center of Pressure (CoP)
  * CoP velocity
  * sway path length
  * total load
  * contact state
  * cadence (heuristic)
- Aggregates session metrics and classifies fall risk.
- Persists sessions, frames, and metrics to SQLite.
- Emits NDJSON events for downstream visualization or host software integration.

Replay file format expected
- The generator writes packets as: [uint32 packet_len][packet bytes] repeated.

Packet layout expected
- Matches metric_traffic_generator.py:
  MAGIC(4) | VERSION(1) | FLAGS(1) | RESERVED(2) |
  TS_US(8) | GW(2) | GH(2) | BAT_PCT(1) | PAD_TYPE(1) | RESERVED2(2) |
  PRESSURE_DATA (GW*GH int16 LE) |
  CRC32 (4)

Example usage
-------------
# Process replay file and write events
python wearable_balance_backend.py replay walk.bin --db wearable.db --out_ndjson walk_events.ndjson

# Print summary only
python wearable_balance_backend.py replay stance.bin --summary_only

# Listen for a live TCP stream of length-prefixed packets
python wearable_balance_backend.py serve --host 0.0.0.0 --port 9009 --db wearable.db
"""
from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sqlite3
import struct
import sys
import time
import zlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, Iterator, List, Optional, Tuple


# ------------------------------------------------------------
# Shared packet definitions (kept compatible with generator)
# ------------------------------------------------------------
MAGIC = b"WBS1"
VERSION = 1
PAD_TYPE_SINGLE = 1

HEADER_STRUCT = struct.Struct("<4sBBH")
META_STRUCT = struct.Struct("<QHHBBH")
CRC_STRUCT = struct.Struct("<I")
UINT32_STRUCT = struct.Struct("<I")

FLAG_PACKET_LOSS_SIM = 1 << 0
FLAG_INTERPOLATED = 1 << 1
FLAG_CALIB_APPLIED = 1 << 2
FLAG_ACCEL_PRESENT = 1 << 3


# ------------------------------------------------------------
# Data classes
# ------------------------------------------------------------
@dataclass
class PacketDecoded:
    ts_us: int
    gw: int
    gh: int
    battery_pct: int
    pad_type: int
    flags: int
    pressure_flat: List[int]


@dataclass
class FrameMetrics:
    t_s: float
    ts_us: int
    battery_pct: int
    flags: int
    cop_x: float
    cop_y: float
    cop_v: float
    sway_path: float
    total_load: float
    in_contact: bool
    cadence_spm: Optional[float]
    stance_pct: float
    swing_pct: float
    asymmetry_index: float
    risk_label: Optional[str] = None
    risk_score: Optional[float] = None


@dataclass
class SessionSummary:
    frames: int
    duration_s: float
    avg_battery_pct: float
    avg_cop_v: float
    sway_path_total: float
    cadence_spm_avg: Optional[float]
    contact_ratio: float
    asymmetry_index_abs_avg: float
    risk_label: str
    risk_score: float


# ------------------------------------------------------------
# Utility / decoding
# ------------------------------------------------------------
def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def compute_cop_from_grid(gw: int, gh: int, grid: List[int]) -> Tuple[float, float, float]:
    total = 0.0
    sx = 0.0
    sy = 0.0
    for idx, p in enumerate(grid):
        if p <= 0:
            continue
        y = idx // gw
        x = idx - y * gw
        w = float(p)
        total += w
        sx += w * x
        sy += w * y
    if total <= 1e-9:
        return float("nan"), float("nan"), 0.0
    return sx / total, sy / total, total


def compute_left_right_asymmetry(gw: int, gh: int, grid: List[int]) -> float:
    """
    Simple load asymmetry across the pad midline.
    Returns normalized signed asymmetry in [-1, 1].
    Positive => right-heavy, negative => left-heavy.
    """
    left = 0.0
    right = 0.0
    mid = gw / 2.0
    for idx, p in enumerate(grid):
        if p <= 0:
            continue
        x = idx % gw
        if x < mid:
            left += p
        else:
            right += p
    denom = left + right
    if denom <= 1e-9:
        return 0.0
    return (right - left) / denom


def verify_and_decode_packet(packet: bytes) -> PacketDecoded:
    min_len = HEADER_STRUCT.size + META_STRUCT.size + CRC_STRUCT.size
    if len(packet) < min_len:
        raise ValueError("packet too short")

    payload = packet[:-CRC_STRUCT.size]
    crc_expected = CRC_STRUCT.unpack(packet[-CRC_STRUCT.size:])[0]
    crc_actual = zlib.crc32(payload) & 0xFFFFFFFF
    if crc_actual != crc_expected:
        raise ValueError(f"crc mismatch: expected={crc_expected:#010x}, actual={crc_actual:#010x}")

    magic, version, flags, _ = HEADER_STRUCT.unpack_from(packet, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic: {magic!r}")
    if version != VERSION:
        raise ValueError(f"unsupported version: {version}")

    off = HEADER_STRUCT.size
    ts_us, gw, gh, battery_pct, pad_type, _ = META_STRUCT.unpack_from(packet, off)
    off += META_STRUCT.size

    count = gw * gh
    pdata_len = 2 * count
    if len(packet) != HEADER_STRUCT.size + META_STRUCT.size + pdata_len + CRC_STRUCT.size:
        raise ValueError("packet length inconsistent with grid dimensions")

    pressure_flat = list(struct.unpack_from("<" + "h" * count, packet, off))
    return PacketDecoded(
        ts_us=ts_us,
        gw=gw,
        gh=gh,
        battery_pct=battery_pct,
        pad_type=pad_type,
        flags=flags,
        pressure_flat=pressure_flat,
    )


# ------------------------------------------------------------
# Step / cadence estimator
# ------------------------------------------------------------
@dataclass
class StepState:
    last_contact: bool = False
    last_hs_time: Optional[float] = None
    step_intervals: Optional[List[float]] = None

    def __post_init__(self) -> None:
        if self.step_intervals is None:
            self.step_intervals
