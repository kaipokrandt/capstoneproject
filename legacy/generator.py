#!/usr/bin/env python3
"""
generator.py

Traffic/metrics generator for the "Wearable Balance Sensor" host app.

What it generates
- Synthetic *raw frames* that resemble proposed BLE packet format:
  [Header | Timestamp | GridWidth | GridHeight | PressureData | Battery | Flags | CRC]
— PressureData is a flattened grid.

- Synthetic *derived metrics* similar to what host pipeline will compute:
  CoP position/velocity, sway path length, cadence, stance:swing %, asymmetry, etc.
  (see proposal §2.0, §4.2.1, §4.4.2)

Outputs 
- .bin : binary packets (framing compatible with simple parsing)
- .csv : per-frame decoded fields (timestamp, CoP, battery, etc.)
- .ndjson : one JSON object per line for metrics/events (easy to stream/plot)


Usage examples
--------------
# 60s quiet stance at 80 Hz, write binary + csv + ndjson
python metric_traffic_generator.py --scenario quiet_stance --seconds 60 --hz 80 \
  --out_bin stance.bin --out_csv stance.csv --out_ndjson stance.ndjson

# 30s walking at 100 Hz with mild packet loss
python metric_traffic_generator.py --scenario walk --seconds 30 --hz 100 \
  --loss_rate 0.01 --out_csv walk.csv --out_ndjson walk.ndjson

# Stream ndjson to stdout (for piping to another process)
python metric_traffic_generator.py --scenario tug --seconds 45 --hz 75 --ndjson_stdout
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import struct
import time
import zlib
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


# -----------------------------
# Packet format 
# -----------------------------
MAGIC = b"WBS1"  # 4B header/magic
VERSION = 1      # 1B

# Binary layout:
#   MAGIC(4) | VERSION(1) | FLAGS(1) | RESERVED(2) |
#   TS_US(8) | GW(2) | GH(2) | BAT_PCT(1) | PAD_TYPE(1) | RESERVED2(2) |
#   PRESSURE_DATA (GW*GH int16 LE) |
#   CRC32 (4)  over everything except CRC itself
#
# Notes:
# - Proposal's fields are covered; some extra bytes are reserved for future use.
# - PressureData is int16 to keep packets modest; you can change to uint16/float32 later.

HEADER_STRUCT = struct.Struct("<4sBBH")         # MAGIC, VERSION, FLAGS, RESERVED
META_STRUCT = struct.Struct("<QHHBBH")          # ts_us, gw, gh, bat_pct, pad_type, reserved2
CRC_STRUCT = struct.Struct("<I")                # crc32


# Flags bitfield (you can extend)
FLAG_PACKET_LOSS_SIM = 1 << 0
FLAG_INTERPOLATED     = 1 << 1
FLAG_CALIB_APPLIED    = 1 << 2
FLAG_ACCEL_PRESENT    = 1 << 3  # if you later embed accel in packet

PAD_TYPE_SINGLE = 1  # single continuous pad (proposal §4.4.1 / §4.7)


@dataclass
class FrameDecoded:
    t_s: float
    ts_us: int
    gw: int
    gh: int
    battery_pct: int
    flags: int
    cop_x: float
    cop_y: float
    cop_v: float
    total_load: float


# -----------------------------
# Synthetic pressure models
# -----------------------------
def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _gaussian2d(x: float, y: float, mx: float, my: float, sx: float, sy: float) -> float:
    # Unnormalized Gaussian bump
    return math.exp(-(((x - mx) ** 2) / (2 * sx * sx) + ((y - my) ** 2) / (2 * sy * sy)))


def synth_pressure_grid(
    gw: int,
    gh: int,
    scenario: str,
    t: float,
    rng: random.Random,
) -> List[int]:
    """
    Returns flattened int16 pressure grid.
    Coordinate convention:
      x in [0, gw-1] left->right, y in [0, gh-1] heel->toe (0 = heel).
    """
    # Baselines (arbitrary units)
    noise = 0.03
    base  = 0.02

    # Scenario-specific CoP/pressure behavior:
    # - quiet_stance: CoP jitters near midfoot, small sway.
    # - walk: traveling load from heel->toe, periodic steps.
    # - tug: stance + walk burst + turn wobble.
    if scenario == "quiet_stance":
        # Gentle sway around center
        mx = (gw - 1) * (0.50 + 0.03 * math.sin(2 * math.pi * 0.25 * t) + 0.02 * rng.uniform(-1, 1))
        my = (gh - 1) * (0.55 + 0.04 * math.sin(2 * math.pi * 0.18 * t + 1.2) + 0.02 * rng.uniform(-1, 1))
        amp = 1.0
        sx, sy = gw * 0.18, gh * 0.20

    elif scenario == "walk":
        # Steps at ~1.8 Hz; within each step, load moves heel->toe
        step_hz = 1.8 + 0.2 * math.sin(2 * math.pi * 0.05 * t)
        phase = (t * step_hz) % 1.0  # 0..1
        # Heel strike: phase ~0, toe off: phase ~0.7
        my_norm = 0.15 + 0.75 * _clamp((phase / 0.75), 0.0, 1.0)
        mx_norm = 0.50 + 0.10 * math.sin(2 * math.pi * step_hz * t + 0.6)
        mx = (gw - 1) * mx_norm
        my = (gh - 1) * my_norm
        amp = 1.2 if phase < 0.85 else 0.4  # unloading at end
        sx, sy = gw * 0.16, gh * 0.18

    elif scenario == "tug":
        # Rough: 0-8s stance, 8-28 walk, 28-35 turn wobble, 35+ walk back
        if t < 8:
            scenario2 = "quiet_stance"
        elif t < 28:
            scenario2 = "walk"
        elif t < 35:
            scenario2 = "quiet_stance"
        else:
            scenario2 = "walk"
        grid = synth_pressure_grid(gw, gh, scenario2, t, rng)
        # Add extra wobble during "turn"
        if 28 <= t < 35:
            wob = 0.12 * math.sin(2 * math.pi * 1.2 * t)
            for i in range(len(grid)):
                grid[i] = int(_clamp(grid[i] * (1.0 + wob), -32768, 32767))
        return grid

    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    out: List[int] = []
    for yy in range(gh):
        for xx in range(gw):
            g = _gaussian2d(xx, yy, mx, my, sx, sy)
            # Add slight heel/forefoot structure: more sensitivity near heel + met heads
            heel_boost = 0.9 + 0.3 * _gaussian2d(xx, yy, (gw - 1) * 0.5, (gh - 1) * 0.10, gw * 0.35, gh * 0.12)
            toe_boost  = 0.9 + 0.2 * _gaussian2d(xx, yy, (gw - 1) * 0.55, (gh - 1) * 0.85, gw * 0.25, gh * 0.10)
            val = base + amp * g * heel_boost * toe_boost
            val += noise * rng.gauss(0, 1)
            val = _clamp(val, 0.0, 2.5)
            # Scale to int16 "counts"
            out.append(int(val * 12000))
    return out


def compute_cop_from_grid(gw: int, gh: int, grid: List[int]) -> Tuple[float, float, float]:
    """
    Compute Center-of-Pressure from weighted centroid (proposal §3.1 / §4.7).
    Returns (cop_x, cop_y, total_load) in grid coordinates.
    """
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
        return (float("nan"), float("nan"), 0.0)
    return (sx / total, sy / total, total)


# -----------------------------
# Metrics synthesis (session-level)
# -----------------------------
@dataclass
class StepState:
    last_contact: bool = False
    last_hs_time: Optional[float] = None
    step_intervals: List[float] = None

    def __post_init__(self) -> None:
        if self.step_intervals is None:
            self.step_intervals = []


def detect_contact_simple(total_load: float, thresh: float) -> bool:
    return total_load > thresh


def update_step_metrics(
    t: float,
    in_contact: bool,
    st: StepState,
) -> Dict[str, float]:
    """
    Heuristic heel-strike detector based on rising contact edge.
    Returns metrics dict possibly containing cadence_spm.
    """
    out: Dict[str, float] = {}
    if in_contact and not st.last_contact:
        # "heel-strike" event (rising edge)
        if st.last_hs_time is not None:
            dt = t - st.last_hs_time
            if 0.2 < dt < 3.0:
                st.step_intervals.append(dt)
                if len(st.step_intervals) > 12:
                    st.step_intervals = st.step_intervals[-12:]
                mean_dt = sum(st.step_intervals) / len(st.step_intervals)
                cadence_spm = 60.0 / mean_dt  # steps per minute
                out["cadence_spm"] = cadence_spm
        st.last_hs_time = t

    st.last_contact = in_contact
    return out


# -----------------------------
# Packet building helper
# -----------------------------
def build_packet(
    ts_us: int,
    gw: int,
    gh: int,
    battery_pct: int,
    flags: int,
    pressure_flat: List[int],
) -> bytes:
    header = HEADER_STRUCT.pack(MAGIC, VERSION, flags & 0xFF, 0)
    meta = META_STRUCT.pack(ts_us, gw, gh, battery_pct & 0xFF, PAD_TYPE_SINGLE, 0)
    pdata = struct.pack("<" + "h" * (gw * gh), *pressure_flat)
    blob_wo_crc = header + meta + pdata
    crc = zlib.crc32(blob_wo_crc) & 0xFFFFFFFF
    return blob_wo_crc + CRC_STRUCT.pack(crc)


# -----------------------------
# Generator
# -----------------------------
def iter_frames(
    scenario: str,
    seconds: float,
    hz: float,
    gw: int,
    gh: int,
    seed: int,
    loss_rate: float,
    start_ts_us: Optional[int],
) -> Iterator[Tuple[bytes, FrameDecoded, Dict[str, object]]]:
    rng = random.Random(seed)

    dt = 1.0 / hz
    n = int(seconds * hz)

    if start_ts_us is None:
        start_ts_us = int(time.time() * 1_000_000)

    battery = 95.0

    last_cop: Optional[Tuple[float, float]] = None
    last_t: Optional[float] = None

    step_state = StepState()
    contact_thresh = 2.5e7  # tune as needed

    sway_path = 0.0

    for i in range(n):
        t = i * dt
        ts_us = start_ts_us + int(t * 1_000_000)

        battery = max(5.0, battery - 0.0008 * (100.0 / hz))
        bat_pct = int(round(battery))

        flags = 0
        if rng.random() < loss_rate:
            flags |= FLAG_PACKET_LOSS_SIM

        grid = synth_pressure_grid(gw, gh, scenario, t, rng)
        cop_x, cop_y, total_load = compute_cop_from_grid(gw, gh, grid)

        cop_v = 0.0
        if last_cop is not None and last_t is not None and not (math.isnan(cop_x) or math.isnan(cop_y)):
            dx = cop_x - last_cop[0]
            dy = cop_y - last_cop[1]
            dd = math.sqrt(dx * dx + dy * dy)
            dtv = t - last_t
            if dtv > 0:
                cop_v = dd / dtv
                sway_path += dd

        last_cop = (cop_x, cop_y)
        last_t = t

        in_contact = detect_contact_simple(total_load, contact_thresh)
        step_metrics = update_step_metrics(t, in_contact, step_state)

        stance_pct = 60.0 if scenario != "quiet_stance" else 100.0
        swing_pct = 40.0 if scenario != "quiet_stance" else 0.0
        asym = 0.05 * math.sin(2 * math.pi * 0.1 * t) + 0.01 * rng.gauss(0, 1)

        packet = build_packet(ts_us, gw, gh, bat_pct, flags, grid)

        decoded = FrameDecoded(
            t_s=t,
            ts_us=ts_us,
            gw=gw,
            gh=gh,
            battery_pct=bat_pct,
            flags=flags,
            cop_x=cop_x,
            cop_y=cop_y,
            cop_v=cop_v,
            total_load=total_load,
        )

        metrics_event: Dict[str, object] = {
            "type": "frame_metrics",
            "t_s": round(t, 6),
            "ts_us": ts_us,
            "scenario": scenario,
            "battery_pct": bat_pct,
            "flags": flags,
            "cop": {"x": cop_x, "y": cop_y},
            "cop_v": cop_v,
            "sway_path": sway_path,
            "stance_pct": stance_pct,
            "swing_pct": swing_pct,
            "asymmetry_index": asym,
        }
        if "cadence_spm" in step_metrics:
            metrics_event["cadence_spm"] = step_metrics["cadence_spm"]

        yield packet, decoded, metrics_event


def write_csv(path: str, frames: Iterable[FrameDecoded]) -> None:
    fieldnames = [
        "t_s", "ts_us", "gw", "gh", "battery_pct", "flags",
        "cop_x", "cop_y", "cop_v", "total_load",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for fr in frames:
            w.writerow({
                "t_s": f"{fr.t_s:.6f}",
                "ts_us": fr.ts_us,
                "gw": fr.gw,
                "gh": fr.gh,
                "battery_pct": fr.battery_pct,
                "flags": fr.flags,
                "cop_x": f"{fr.cop_x:.4f}",
                "cop_y": f"{fr.cop_y:.4f}",
                "cop_v": f"{fr.cop_v:.4f}",
                "total_load": f"{fr.total_load:.1f}",
            })


def write_ndjson(path: str, events: Iterable[Dict[str, object]]) -> None:
    with open(path, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Synthetic traffic/metrics generator for Wearable Balance Sensor.")
    ap.add_argument("--scenario", choices=["quiet_stance", "walk", "tug"], default="walk")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--hz", type=float, default=80.0)
    ap.add_argument("--gw", type=int, default=16)
    ap.add_argument("--gh", type=int, default=32)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--loss_rate", type=float, default=0.0)
    ap.add_argument("--start_ts_us", type=int, default=None)

    ap.add_argument("--out_bin", type=str, default=None)
    ap.add_argument("--out_csv", type=str, default=None)
    ap.add_argument("--out_ndjson", type=str, default=None)
    ap.add_argument("--ndjson_stdout", action="store_true")

    args = ap.parse_args()

    packets: List[bytes] = []
    decoded_frames: List[FrameDecoded] = []
    events: List[Dict[str, object]] = []

    for pkt, dec, ev in iter_frames(
        scenario=args.scenario,
        seconds=args.seconds,
        hz=args.hz,
        gw=args.gw,
        gh=args.gh,
        seed=args.seed,
        loss_rate=args.loss_rate,
        start_ts_us=args.start_ts_us,
    ):
        packets.append(pkt)
        decoded_frames.append(dec)
        events.append(ev)
        if args.ndjson_stdout:
            print(json.dumps(ev), flush=True)

    if args.out_bin:
        with open(args.out_bin, "wb") as f:
            for p in packets:
                f.write(struct.pack("<I", len(p)))  # length-prefixed replay file
                f.write(p)

    if args.out_csv:
        write_csv(args.out_csv, decoded_frames)

    if args.out_ndjson:
        write_ndjson(args.out_ndjson, events)

    if events:
        cad = [ev.get("cadence_spm") for ev in events if "cadence_spm" in ev]
        cad_s = f"{(sum(cad)/len(cad)):.1f} spm" if cad else "n/a"
        print(f"Generated {len(events)} frames @ {args.hz} Hz, scenario={args.scenario}, avg cadence={cad_s}", file=os.sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
