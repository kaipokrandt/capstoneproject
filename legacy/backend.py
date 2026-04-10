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
            self.step_intervals = []


class MetricEngine:
    def __init__(self, total_load_contact_thresh: float = 2.5e7) -> None:
        self.contact_thresh = total_load_contact_thresh
        self.step_state = StepState()
        self.start_ts_us: Optional[int] = None
        self.last_cop: Optional[Tuple[float, float]] = None
        self.last_t_s: Optional[float] = None
        self.sway_path = 0.0
        self.frames_seen = 0
        self.contact_frames = 0
        self.cadence_values: List[float] = []
        self.cop_v_values: List[float] = []
        self.asym_values: List[float] = []
        self.battery_values: List[int] = []

    def detect_contact(self, total_load: float) -> bool:
        return total_load > self.contact_thresh

    def update_cadence(self, t_s: float, in_contact: bool) -> Optional[float]:
        st = self.step_state
        cadence_spm: Optional[float] = None

        if in_contact and not st.last_contact:
            if st.last_hs_time is not None:
                dt = t_s - st.last_hs_time
                if 0.2 < dt < 3.0:
                    st.step_intervals.append(dt)
                    if len(st.step_intervals) > 12:
                        st.step_intervals = st.step_intervals[-12:]
                    mean_dt = sum(st.step_intervals) / len(st.step_intervals)
                    cadence_spm = 60.0 / mean_dt
                    self.cadence_values.append(cadence_spm)
            st.last_hs_time = t_s

        st.last_contact = in_contact
        return cadence_spm

    def process_packet(self, dec: PacketDecoded) -> FrameMetrics:
        if self.start_ts_us is None:
            self.start_ts_us = dec.ts_us

        t_s = (dec.ts_us - self.start_ts_us) / 1_000_000.0
        cop_x, cop_y, total_load = compute_cop_from_grid(dec.gw, dec.gh, dec.pressure_flat)
        asym = compute_left_right_asymmetry(dec.gw, dec.gh, dec.pressure_flat)

        cop_v = 0.0
        if self.last_cop is not None and self.last_t_s is not None and not (math.isnan(cop_x) or math.isnan(cop_y)):
            dx = cop_x - self.last_cop[0]
            dy = cop_y - self.last_cop[1]
            dist = math.sqrt(dx * dx + dy * dy)
            dt = t_s - self.last_t_s
            if dt > 0:
                cop_v = dist / dt
                self.sway_path += dist

        self.last_cop = (cop_x, cop_y)
        self.last_t_s = t_s

        in_contact = self.detect_contact(total_load)
        cadence_spm = self.update_cadence(t_s, in_contact)

        stance_pct = 100.0 if not self.cadence_values else 60.0
        swing_pct = 0.0 if stance_pct == 100.0 else 40.0

        self.frames_seen += 1
        self.contact_frames += int(in_contact)
        self.cop_v_values.append(cop_v)
        self.asym_values.append(asym)
        self.battery_values.append(dec.battery_pct)

        return FrameMetrics(
            t_s=t_s,
            ts_us=dec.ts_us,
            battery_pct=dec.battery_pct,
            flags=dec.flags,
            cop_x=cop_x,
            cop_y=cop_y,
            cop_v=cop_v,
            sway_path=self.sway_path,
            total_load=total_load,
            in_contact=in_contact,
            cadence_spm=cadence_spm,
            stance_pct=stance_pct,
            swing_pct=swing_pct,
            asymmetry_index=asym,
        )

    def summarize(self) -> SessionSummary:
        duration_s = self.last_t_s if self.last_t_s is not None else 0.0
        avg_battery = sum(self.battery_values) / len(self.battery_values) if self.battery_values else 0.0
        avg_cop_v = sum(self.cop_v_values) / len(self.cop_v_values) if self.cop_v_values else 0.0
        avg_cad = sum(self.cadence_values) / len(self.cadence_values) if self.cadence_values else None
        contact_ratio = self.contact_frames / self.frames_seen if self.frames_seen else 0.0
        asym_abs_avg = sum(abs(x) for x in self.asym_values) / len(self.asym_values) if self.asym_values else 0.0

        risk_score, risk_label = classify_fall_risk(
            avg_cop_v=avg_cop_v,
            sway_path_total=self.sway_path,
            cadence_spm_avg=avg_cad,
            contact_ratio=contact_ratio,
            asymmetry_index_abs_avg=asym_abs_avg,
            duration_s=duration_s,
        )

        return SessionSummary(
            frames=self.frames_seen,
            duration_s=duration_s,
            avg_battery_pct=avg_battery,
            avg_cop_v=avg_cop_v,
            sway_path_total=self.sway_path,
            cadence_spm_avg=avg_cad,
            contact_ratio=contact_ratio,
            asymmetry_index_abs_avg=asym_abs_avg,
            risk_label=risk_label,
            risk_score=risk_score,
        )


# ------------------------------------------------------------
# Risk model
# ------------------------------------------------------------
def classify_fall_risk(
    *,
    avg_cop_v: float,
    sway_path_total: float,
    cadence_spm_avg: Optional[float],
    contact_ratio: float,
    asymmetry_index_abs_avg: float,
    duration_s: float,
) -> Tuple[float, str]:
    """
    Simple heuristic risk model for development and demo use.
    This is not a clinical model.
    Score range roughly 0..100.
    """
    score = 0.0

    # Increased sway velocity and total sway raise risk.
    score += clamp(avg_cop_v / 6.0, 0.0, 1.0) * 30.0
    sway_norm = sway_path_total / max(duration_s, 1.0)
    score += clamp(sway_norm / 4.0, 0.0, 1.0) * 25.0

    # Missing or unusually low cadence can indicate reduced gait quality for walking sessions.
    if cadence_spm_avg is None:
        score += 10.0
    else:
        if cadence_spm_avg < 80:
            score += 20.0
        elif cadence_spm_avg < 95:
            score += 10.0
        elif cadence_spm_avg > 145:
            score += 6.0

    # Too much static contact or too little can be suspicious depending on task.
    if contact_ratio > 0.98:
        score += 8.0
    elif contact_ratio < 0.30:
        score += 12.0

    # Higher left/right imbalance raises risk.
    score += clamp(asymmetry_index_abs_avg / 0.18, 0.0, 1.0) * 25.0

    score = clamp(score, 0.0, 100.0)
    if score < 33:
        label = "low"
    elif score < 66:
        label = "moderate"
    else:
        label = "high"
    return score, label


# ------------------------------------------------------------
# SQLite persistence
# ------------------------------------------------------------
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at_us INTEGER NOT NULL,
    ended_at_us INTEGER,
    source TEXT NOT NULL,
    notes TEXT,
    risk_label TEXT,
    risk_score REAL
);

CREATE TABLE IF NOT EXISTS raw_frames (
    frame_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts_us INTEGER NOT NULL,
    gw INTEGER NOT NULL,
    gh INTEGER NOT NULL,
    battery_pct INTEGER NOT NULL,
    flags INTEGER NOT NULL,
    total_load REAL NOT NULL,
    pressure_blob BLOB NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS computed_metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts_us INTEGER NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    unit TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_frames_session ON raw_frames(session_id);
CREATE INDEX IF NOT EXISTS idx_metrics_session ON computed_metrics(session_id);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def create_session(self, started_at_us: int, source: str, notes: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions(started_at_us, source, notes) VALUES (?, ?, ?)",
            (started_at_us, source, notes),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finalize_session(self, session_id: int, ended_at_us: int, risk_label: str, risk_score: float) -> None:
        self.conn.execute(
            "UPDATE sessions SET ended_at_us = ?, risk_label = ?, risk_score = ? WHERE session_id = ?",
            (ended_at_us, risk_label, risk_score, session_id),
        )
        self.conn.commit()

    def save_frame(self, session_id: int, dec: PacketDecoded, total_load: float) -> None:
        pressure_blob = struct.pack("<" + "h" * len(dec.pressure_flat), *dec.pressure_flat)
        self.conn.execute(
            """
            INSERT INTO raw_frames(session_id, ts_us, gw, gh, battery_pct, flags, total_load, pressure_blob)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, dec.ts_us, dec.gw, dec.gh, dec.battery_pct, dec.flags, total_load, pressure_blob),
        )

    def save_metrics(self, session_id: int, fm: FrameMetrics) -> None:
        rows = [
            (session_id, fm.ts_us, "cop_x", fm.cop_x, "grid_x"),
            (session_id, fm.ts_us, "cop_y", fm.cop_y, "grid_y"),
            (session_id, fm.ts_us, "cop_v", fm.cop_v, "grid_per_s"),
            (session_id, fm.ts_us, "sway_path", fm.sway_path, "grid_units"),
            (session_id, fm.ts_us, "total_load", fm.total_load, "counts"),
            (session_id, fm.ts_us, "stance_pct", fm.stance_pct, "percent"),
            (session_id, fm.ts_us, "swing_pct", fm.swing_pct, "percent"),
            (session_id, fm.ts_us, "asymmetry_index", fm.asymmetry_index, "ratio"),
        ]
        if fm.cadence_spm is not None:
            rows.append((session_id, fm.ts_us, "cadence_spm", fm.cadence_spm, "steps_per_min"))
        self.conn.executemany(
            "INSERT INTO computed_metrics(session_id, ts_us, metric_name, metric_value, unit) VALUES (?, ?, ?, ?, ?)",
            rows,
        )

    def commit(self) -> None:
        self.conn.commit()


# ------------------------------------------------------------
# Event formatting
# ------------------------------------------------------------
def frame_metrics_to_event(fm: FrameMetrics, session_id: Optional[int]) -> Dict[str, object]:
    return {
        "type": "frame_metrics",
        "session_id": session_id,
        "t_s": round(fm.t_s, 6),
        "ts_us": fm.ts_us,
        "battery_pct": fm.battery_pct,
        "flags": fm.flags,
        "cop": {"x": fm.cop_x, "y": fm.cop_y},
        "cop_v": fm.cop_v,
        "sway_path": fm.sway_path,
        "total_load": fm.total_load,
        "in_contact": fm.in_contact,
        "cadence_spm": fm.cadence_spm,
        "stance_pct": fm.stance_pct,
        "swing_pct": fm.swing_pct,
        "asymmetry_index": fm.asymmetry_index,
        "risk_label": fm.risk_label,
        "risk_score": fm.risk_score,
    }


def summary_to_event(summary: SessionSummary, session_id: Optional[int]) -> Dict[str, object]:
    out = asdict(summary)
    out["type"] = "session_summary"
    out["session_id"] = session_id
    return out


# ------------------------------------------------------------
# Replay readers
# ------------------------------------------------------------
def iter_length_prefixed_packets(fp: BinaryIO) -> Iterator[bytes]:
    while True:
        hdr = fp.read(UINT32_STRUCT.size)
        if not hdr:
            break
        if len(hdr) != UINT32_STRUCT.size:
            raise ValueError("truncated packet length prefix")
        (n,) = UINT32_STRUCT.unpack(hdr)
        if n <= 0:
            raise ValueError("invalid packet length")
        data = fp.read(n)
        if len(data) != n:
            raise ValueError("truncated packet body")
        yield data


# ------------------------------------------------------------
# Processing pipeline
# ------------------------------------------------------------
def process_packet_stream(
    packets: Iterable[bytes],
    *,
    db: Optional[Database],
    source: str,
    out_ndjson_path: Optional[str],
    stdout_events: bool,
    summary_only: bool,
) -> SessionSummary:
    engine = MetricEngine()
    ndjson_fh = open(out_ndjson_path, "w") if out_ndjson_path else None
    session_id: Optional[int] = None
    started_at_us: Optional[int] = None
    last_ts_us: Optional[int] = None

    try:
        for packet in packets:
            dec = verify_and_decode_packet(packet)
            if started_at_us is None:
                started_at_us = dec.ts_us
                if db is not None:
                    session_id = db.create_session(started_at_us=dec.ts_us, source=source)

            fm = engine.process_packet(dec)
            last_ts_us = dec.ts_us

            # Per-frame provisional risk can be derived from running aggregates.
            running_summary = engine.summarize()
            fm.risk_label = running_summary.risk_label
            fm.risk_score = running_summary.risk_score

            if db is not None and session_id is not None:
                db.save_frame(session_id, dec, total_load=fm.total_load)
                db.save_metrics(session_id, fm)

            if not summary_only:
                event = frame_metrics_to_event(fm, session_id)
                line = json.dumps(event)
                if ndjson_fh is not None:
                    ndjson_fh.write(line + "\n")
                if stdout_events:
                    print(line, flush=True)

        summary = engine.summarize()
        if db is not None and session_id is not None and last_ts_us is not None:
            db.finalize_session(session_id, ended_at_us=last_ts_us, risk_label=summary.risk_label, risk_score=summary.risk_score)
            db.commit()

        summary_event = summary_to_event(summary, session_id)
        line = json.dumps(summary_event)
        if ndjson_fh is not None:
            ndjson_fh.write(line + "\n")
        if stdout_events or summary_only:
            print(line)

        return summary
    finally:
        if ndjson_fh is not None:
            ndjson_fh.close()


# ------------------------------------------------------------
# TCP server mode
# ------------------------------------------------------------
def recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise EOFError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


def iter_socket_packets(conn: socket.socket) -> Iterator[bytes]:
    while True:
        hdr = recv_exact(conn, UINT32_STRUCT.size)
        (n,) = UINT32_STRUCT.unpack(hdr)
        if n <= 0 or n > 10_000_000:
            raise ValueError(f"invalid packet length from socket: {n}")
        yield recv_exact(conn, n)


def serve_tcp(host: str, port: int, db_path: Optional[str], out_ndjson: Optional[str], stdout_events: bool) -> int:
    db = Database(db_path) if db_path else None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((host, port))
            srv.listen(1)
            print(f"Listening on {host}:{port}", file=sys.stderr)
            conn, addr = srv.accept()
            with conn:
                print(f"Client connected: {addr}", file=sys.stderr)
                try:
                    process_packet_stream(
                        iter_socket_packets(conn),
                        db=db,
                        source=f"tcp://{addr[0]}:{addr[1]}",
                        out_ndjson_path=out_ndjson,
                        stdout_events=stdout_events,
                        summary_only=False,
                    )
                except EOFError:
                    print("Client disconnected", file=sys.stderr)
        return 0
    finally:
        if db is not None:
            db.close()


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Backend for Wearable Balance Sensor synthetic/live packet ingestion.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("replay", help="Process a generator replay file")
    rp.add_argument("input_bin", help="Length-prefixed packet replay file")
    rp.add_argument("--db", default=None, help="SQLite database path")
    rp.add_argument("--out_ndjson", default=None, help="Write per-frame events and summary to NDJSON")
    rp.add_argument("--stdout_events", action="store_true", help="Emit per-frame events to stdout")
    rp.add_argument("--summary_only", action="store_true", help="Only print session summary")

    sp = sub.add_parser("serve", help="Listen for a live TCP stream of length-prefixed packets")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=9009)
    sp.add_argument("--db", default=None, help="SQLite database path")
    sp.add_argument("--out_ndjson", default=None, help="Write events to NDJSON")
    sp.add_argument("--stdout_events", action="store_true")

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    if args.cmd == "replay":
        db = Database(args.db) if args.db else None
        try:
            with open(args.input_bin, "rb") as fh:
                summary = process_packet_stream(
                    iter_length_prefixed_packets(fh),
                    db=db,
                    source=os.path.abspath(args.input_bin),
                    out_ndjson_path=args.out_ndjson,
                    stdout_events=args.stdout_events,
                    summary_only=args.summary_only,
                )
            print(
                f"Processed {summary.frames} frames, duration={summary.duration_s:.2f}s, "
                f"risk={summary.risk_label} ({summary.risk_score:.1f})",
                file=sys.stderr,
            )
            return 0
        finally:
            if db is not None:
                db.close()

    if args.cmd == "serve":
        return serve_tcp(args.host, args.port, args.db, args.out_ndjson, args.stdout_events)

    ap.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
