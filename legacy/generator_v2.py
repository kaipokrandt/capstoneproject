#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import struct
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from calibration import adc_counts_to_pressure
from gait_features import compute_cop_from_grid
from packet_format import FLAG_PACKET_LOSS_SIM, build_packet


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


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _gaussian2d(x: float, y: float, mx: float, my: float, sx: float, sy: float) -> float:
    return math.exp(-(((x - mx) ** 2) / (2 * sx * sx) + ((y - my) ** 2) / (2 * sy * sy)))


def synth_force_grid(
    gw: int,
    gh: int,
    scenario: str,
    t: float,
    rng: random.Random,
) -> List[float]:
    """
    Generate a latent force/pressure-like grid before sensor electrical conversion.
    """
    noise = 0.03
    base = 0.02

    if scenario == "quiet_stance":
        mx = (gw - 1) * (0.50 + 0.03 * math.sin(2 * math.pi * 0.25 * t) + 0.02 * rng.uniform(-1, 1))
        my = (gh - 1) * (0.55 + 0.04 * math.sin(2 * math.pi * 0.18 * t + 1.2) + 0.02 * rng.uniform(-1, 1))
        amp = 1.0
        sx, sy = gw * 0.18, gh * 0.20

    elif scenario == "walk":
        step_hz = 1.8 + 0.2 * math.sin(2 * math.pi * 0.05 * t)
        phase = (t * step_hz) % 1.0
        my_norm = 0.15 + 0.75 * _clamp((phase / 0.75), 0.0, 1.0)
        mx_norm = 0.50 + 0.10 * math.sin(2 * math.pi * step_hz * t + 0.6)
        mx = (gw - 1) * mx_norm
        my = (gh - 1) * my_norm
        amp = 1.2 if phase < 0.85 else 0.4
        sx, sy = gw * 0.16, gh * 0.18

    elif scenario == "tug":
        scenario2 = "quiet_stance" if t < 8 else "walk" if t < 28 else "quiet_stance" if t < 35 else "walk"
        grid = synth_force_grid(gw, gh, scenario2, t, rng)
        if 28 <= t < 35:
            wob = 0.12 * math.sin(2 * math.pi * 1.2 * t)
            grid = [_clamp(v * (1.0 + wob), 0.0, 2.5) for v in grid]
        return grid

    else:
        raise ValueError(f"Unknown scenario: {scenario}")

    out: List[float] = []
    for yy in range(gh):
        for xx in range(gw):
            g = _gaussian2d(xx, yy, mx, my, sx, sy)
            heel_boost = 0.9 + 0.3 * _gaussian2d(xx, yy, (gw - 1) * 0.5, (gh - 1) * 0.10, gw * 0.35, gh * 0.12)
            toe_boost = 0.9 + 0.2 * _gaussian2d(xx, yy, (gw - 1) * 0.55, (gh - 1) * 0.85, gw * 0.25, gh * 0.10)
            val = base + amp * g * heel_boost * toe_boost
            val += noise * rng.gauss(0, 1)
            out.append(_clamp(val, 0.0, 2.5))
    return out


def force_to_adc_counts(
    force_grid: List[float],
    *,
    adc_bits: int = 12,
    noise_std: float = 6.0,
    rng: Optional[random.Random] = None,
) -> List[int]:
    """
    Approximate hardware behavior:
    force -> resistive change -> voltage divider response -> ADC counts.
    """
    if rng is None:
        rng = random.Random()

    max_count = (1 << adc_bits) - 1
    out: List[int] = []

    for force in force_grid:
        fn = _clamp(force / 2.5, 0.0, 1.0)

        # Simple nonlinear sensor response.
        # More force => more voltage, but not perfectly linear.
        vn = math.sqrt(fn) if fn > 0 else 0.0

        adc = int(_clamp(vn * max_count + rng.gauss(0.0, noise_std), 0, max_count))
        out.append(adc)

    return out


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


def update_step_metrics(t: float, in_contact: bool, st: StepState) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if in_contact and not st.last_contact:
        if st.last_hs_time is not None:
            dt = t - st.last_hs_time
            if 0.2 < dt < 3.0:
                st.step_intervals.append(dt)
                if len(st.step_intervals) > 12:
                    st.step_intervals = st.step_intervals[-12:]
                mean_dt = sum(st.step_intervals) / len(st.step_intervals)
                out["cadence_spm"] = 60.0 / mean_dt
        st.last_hs_time = t
    st.last_contact = in_contact
    return out


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
    contact_thresh = 2.5e7
    sway_path = 0.0

    for i in range(n):
        t = i * dt
        ts_us = start_ts_us + int(t * 1_000_000)

        battery = max(5.0, battery - 0.0008 * (100.0 / hz))
        bat_pct = int(round(battery))

        flags = 0
        if rng.random() < loss_rate:
            flags |= FLAG_PACKET_LOSS_SIM

        force_grid = synth_force_grid(gw, gh, scenario, t, rng)
        adc_grid = force_to_adc_counts(force_grid, rng=rng)

        # Debug-only local reconstruction for CSV/NDJSON generation
        pressure_grid = adc_counts_to_pressure(adc_grid)
        cop_x, cop_y, total_load = compute_cop_from_grid(gw, gh, pressure_grid)

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

        packet = build_packet(ts_us, gw, gh, bat_pct, flags, adc_grid)

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

        event: Dict[str, object] = {
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
            event["cadence_spm"] = step_metrics["cadence_spm"]

        yield packet, decoded, event


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
    ap = argparse.ArgumentParser(description="Synthetic ADC-traffic generator for Wearable Balance Sensor.")
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
                f.write(struct.pack("<I", len(p)))
                f.write(p)

    if args.out_csv:
        write_csv(args.out_csv, decoded_frames)

    if args.out_ndjson:
        write_ndjson(args.out_ndjson, events)

    if events:
        cad = [ev.get("cadence_spm") for ev in events if "cadence_spm" in ev]
        cad_s = f"{(sum(cad)/len(cad)):.1f} spm" if cad else "n/a"
        print(
            f"Generated {len(events)} frames @ {args.hz} Hz, scenario={args.scenario}, avg cadence={cad_s}",
            file=os.sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
