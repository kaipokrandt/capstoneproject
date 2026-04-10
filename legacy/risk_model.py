#!/usr/bin/env python3
from __future__ import annotations

from typing import Optional, Tuple

from gait_features import clamp


def classify_fall_risk(
    *,
    avg_cop_v: float,
    sway_path_total: float,
    cadence_spm_avg: Optional[float],
    contact_ratio: float,
    asymmetry_index_abs_avg: float,
    duration_s: float,
) -> Tuple[float, str]:
    score = 0.0

    score += clamp(avg_cop_v / 6.0, 0.0, 1.0) * 30.0
    sway_norm = sway_path_total / max(duration_s, 1.0)
    score += clamp(sway_norm / 4.0, 0.0, 1.0) * 25.0

    if cadence_spm_avg is None:
        score += 10.0
    else:
        if cadence_spm_avg < 80:
            score += 20.0
        elif cadence_spm_avg < 95:
            score += 10.0
        elif cadence_spm_avg > 145:
            score += 6.0

    if contact_ratio > 0.98:
        score += 8.0
    elif contact_ratio < 0.30:
        score += 12.0

    score += clamp(asymmetry_index_abs_avg / 0.18, 0.0, 1.0) * 25.0
    score = clamp(score, 0.0, 100.0)

    if score < 33:
        return score, "low"
    if score < 66:
        return score, "moderate"
    return score, "high"
