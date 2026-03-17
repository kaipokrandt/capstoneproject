#!/usr/bin/env python3
from __future__ import annotations

from typing import List


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def adc_counts_to_voltage(adc_counts: List[int], adc_bits: int = 12, vref: float = 3.3) -> List[float]:
    """
    Convert raw ADC counts into voltages.
    """
    max_count = (1 << adc_bits) - 1
    return [(_clamp(c, 0, max_count) / max_count) * vref for c in adc_counts]


def adc_counts_to_pressure(
    adc_counts: List[int],
    *,
    adc_bits: int = 12,
    vref: float = 3.3,
) -> List[int]:
    """
    Placeholder host-side calibration model:
    ADC counts -> normalized pressure-like values.

    This is intentionally simple. Replace later with per-cell
    calibration curves, offsets, gains, and nonlinearity correction.
    """
    max_count = (1 << adc_bits) - 1
    out: List[int] = []

    for c in adc_counts:
        xn = _clamp(c / max_count, 0.0, 1.0)

        # Simple inverse of a square-root-like sensor simulation:
        # generator uses roughly sqrt(force) -> ADC, so undo with x^2.
        p = xn * xn

        out.append(int(p * 30000))

    return out
