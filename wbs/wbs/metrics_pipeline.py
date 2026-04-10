import math
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .models import ComputedMetric, RawFrame, Session


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _adc_counts_to_pressure(adc_counts: List[int], adc_bits: int = 12) -> List[int]:
    max_count = (1 << adc_bits) - 1
    out: List[int] = []
    for c in adc_counts:
        xn = _clamp(c / max_count, 0.0, 1.0)
        out.append(int((xn * xn) * 30000))
    return out


def _compute_cop_from_grid(gw: int, gh: int, grid: List[int]) -> Tuple[float, float, float]:
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


def _compute_left_right_asymmetry(gw: int, grid: List[int]) -> float:
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


def _finite_or_zero(x: float) -> float:
    return x if math.isfinite(x) else 0.0


@dataclass
class _StepState:
    last_contact: bool = False
    last_hs_time: Optional[float] = None
    step_intervals: List[float] = field(default_factory=list)


def recompute_session_metrics(session: Session) -> int:
    frames = list(RawFrame.objects.filter(session=session).order_by("ts_us", "frame_id"))
    ComputedMetric.objects.filter(session=session).delete()

    if not frames:
        return 0

    start_ts_us = frames[0].ts_us
    last_cop: Optional[Tuple[float, float]] = None
    last_t_s: Optional[float] = None
    sway_path = 0.0
    contact_thresh = 5.0e5
    step_state = _StepState()
    cadence_values: List[float] = []

    metric_rows: List[ComputedMetric] = []

    for fr in frames:
        count = fr.gw * fr.gh
        adc_flat = list(struct.unpack("<" + "h" * count, bytes(fr.adc_blob)))
        pressure = _adc_counts_to_pressure(adc_flat)
        cop_x, cop_y, total_load = _compute_cop_from_grid(fr.gw, fr.gh, pressure)
        asym = _compute_left_right_asymmetry(fr.gw, pressure)

        t_s = (fr.ts_us - start_ts_us) / 1_000_000.0

        cop_v = 0.0
        if last_cop is not None and last_t_s is not None and not (math.isnan(cop_x) or math.isnan(cop_y)):
            dx = cop_x - last_cop[0]
            dy = cop_y - last_cop[1]
            dist = math.sqrt(dx * dx + dy * dy)
            dt = t_s - last_t_s
            if dt > 0:
                cop_v = dist / dt
                sway_path += dist

        last_cop = (cop_x, cop_y)
        last_t_s = t_s

        in_contact = total_load > contact_thresh
        cadence_spm: Optional[float] = None
        if in_contact and not step_state.last_contact:
            if step_state.last_hs_time is not None:
                dt = t_s - step_state.last_hs_time
                if 0.2 < dt < 3.0:
                    step_state.step_intervals.append(dt)
                    if len(step_state.step_intervals) > 12:
                        step_state.step_intervals = step_state.step_intervals[-12:]
                    mean_dt = sum(step_state.step_intervals) / len(step_state.step_intervals)
                    cadence_spm = 60.0 / mean_dt
                    cadence_values.append(cadence_spm)
            step_state.last_hs_time = t_s
        step_state.last_contact = in_contact

        stance_pct = 100.0 if not cadence_values else 60.0
        swing_pct = 0.0 if stance_pct == 100.0 else 40.0

        rows = [
            ("cop_x", _finite_or_zero(cop_x), "grid_x"),
            ("cop_y", _finite_or_zero(cop_y), "grid_y"),
            ("cop_v", _finite_or_zero(cop_v), "grid_per_s"),
            ("sway_path", _finite_or_zero(sway_path), "grid_units"),
            ("total_load", _finite_or_zero(total_load), "counts"),
            ("stance_pct", _finite_or_zero(stance_pct), "percent"),
            ("swing_pct", _finite_or_zero(swing_pct), "percent"),
            ("asymmetry_index", _finite_or_zero(asym), "ratio"),
        ]
        if cadence_spm is not None:
            rows.append(("cadence_spm", cadence_spm, "steps_per_min"))

        for metric_name, metric_value, unit in rows:
            metric_rows.append(
                ComputedMetric(
                    session=session,
                    ts_us=fr.ts_us,
                    metric_name=metric_name,
                    metric_value=float(metric_value),
                    unit=unit,
                )
            )

    ComputedMetric.objects.bulk_create(metric_rows)
    return len(metric_rows)
