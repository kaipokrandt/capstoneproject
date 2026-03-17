#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Dict, Iterable, Optional

from db import Database
from gait_features import FrameMetrics, MetricEngine, SessionSummary
from pad_decoder import verify_and_decode_packet
from risk_model import classify_fall_risk


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

            running_summary = engine.summarize()
            fm.risk_label = running_summary.risk_label
            fm.risk_score = running_summary.risk_score

            if db is not None and session_id is not None:
                db.save_frame(session_id, dec, total_load=fm.total_load)
                db.save_metrics(session_id, fm)

            if not summary_only:
                line = json.dumps(frame_metrics_to_event(fm, session_id))
                if ndjson_fh is not None:
                    ndjson_fh.write(line + "\n")
                if stdout_events:
                    print(line, flush=True)

        summary = engine.summarize()
        if db is not None and session_id is not None and last_ts_us is not None:
            db.finalize_session(
                session_id,
                ended_at_us=last_ts_us,
                risk_label=summary.risk_label,
                risk_score=summary.risk_score,
            )
            db.commit()

        line = json.dumps(summary_to_event(summary, session_id))
        if ndjson_fh is not None:
            ndjson_fh.write(line + "\n")
        if stdout_events or summary_only:
            print(line)

        return summary
    finally:
        if ndjson_fh is not None:
            ndjson_fh.close()
