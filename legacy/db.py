#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import struct

from gait_features import FrameMetrics
from pad_decoder import PacketDecoded

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
    adc_blob BLOB NOT NULL,
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
        adc_blob = struct.pack("<" + "h" * len(dec.adc_flat), *dec.adc_flat)
        self.conn.execute(
            """
            INSERT INTO raw_frames(session_id, ts_us, gw, gh, battery_pct, flags, total_load, adc_blob)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, dec.ts_us, dec.gw, dec.gh, dec.battery_pct, dec.flags, total_load, adc_blob),
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
