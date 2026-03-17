#!/usr/bin/env python3
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from calibration import adc_counts_to_pressure
from pad_decoder import PacketDecoded


@dataclass
class StepState:
    last_contact: bool = False
    last_hs_time: Optional[float] = None
    step_intervals: Optional[List[float]] = None

    def __post_init__(self) -> None:
        if self.step_intervals is None:
            self.step_intervals = []


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

        # Convert raw ADC grid into calibrated pressure-like grid
        pressure_grid = adc_counts_to_pressure(dec.adc_flat)

        cop_x, cop_y, total_load = compute_cop_from_grid(dec.gw, dec.gh, pressure_grid)
        asym = compute_left_right_asymmetry(dec.gw, dec.gh, pressure_grid)

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
