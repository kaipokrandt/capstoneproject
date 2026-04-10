import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

from django.conf import settings
from django.http import FileResponse, HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .models import ComputedMetric, Report, Session


def _clinic_tz() -> ZoneInfo:
    tz_name = str(getattr(settings, "TIME_ZONE", "UTC") or "UTC")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def _us_to_local_date(ts_us: int, tz: ZoneInfo) -> date:
    dt_utc = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)
    return dt_utc.astimezone(tz).date()


def _date_to_us_start(d: date, tz: ZoneInfo) -> int:
    local = datetime.combine(d, time.min, tzinfo=tz)
    utc_dt = local.astimezone(timezone.utc)
    return int(utc_dt.timestamp() * 1_000_000)


def _date_to_us_end(d: date, tz: ZoneInfo) -> int:
    local = datetime.combine(d + timedelta(days=1), time.min, tzinfo=tz)
    utc_dt = local.astimezone(timezone.utc)
    return int(utc_dt.timestamp() * 1_000_000) - 1


def _json_body(request: HttpRequest) -> dict:
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _require_auth(request: HttpRequest):
    if request.user.is_authenticated:
        return None
    return JsonResponse({"detail": "authentication required"}, status=401)


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_minimal_pdf(lines: List[str]) -> bytes:
    ops = ["BT", "/F1 12 Tf", "50 780 Td"]
    for i, line in enumerate(lines):
        if i > 0:
            ops.append("0 -16 Td")
        ops.append(f"({_escape_pdf_text(line)}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("utf-8")

    objects = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    objects.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n"
    )
    objects.append(
        b"4 0 obj\n<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    header = b"%PDF-1.4\n"
    parts = [header]
    offsets = [0]
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        parts.append(obj)
        pos += len(obj)

    xref_start = pos
    xref = [f"xref\n0 {len(objects) + 1}\n".encode("ascii")]
    xref.append(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("ascii"))

    trailer = (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_start).encode("ascii")
        + b"\n%%EOF\n"
    )
    return b"".join(parts + xref + [trailer])


def _wrap_text(text: str, max_chars: int = 88) -> List[str]:
    words = (text or "").strip().split()
    if not words:
        return []
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _metrics_series_preview(session: Session, limit_per_metric: int = 80) -> Dict[str, List[dict]]:
    rows = list(
        ComputedMetric.objects.filter(session=session)
        .order_by("ts_us", "metric_id")
        .values("metric_name", "ts_us", "metric_value", "unit")
    )
    by_name: Dict[str, List[dict]] = {}
    for row in rows:
        name = row["metric_name"]
        by_name.setdefault(name, []).append(
            {
                "ts_us": row["ts_us"],
                "value": float(row["metric_value"]),
                "unit": row["unit"] or "",
            }
        )

    out: Dict[str, List[dict]] = {}
    for name, items in by_name.items():
        if len(items) <= limit_per_metric:
            out[name] = items
            continue
        step = max(1, len(items) // limit_per_metric)
        sampled = [items[i] for i in range(0, len(items), step)]
        out[name] = sampled[:limit_per_metric]
    return out


def _build_pdf_from_streams(streams: List[bytes], page_size: tuple[int, int] = (612, 792)) -> bytes:
    page_w, page_h = page_size
    page_count = len(streams)
    pages_obj_id = 2
    first_page_obj_id = 3
    first_content_obj_id = first_page_obj_id + page_count
    font_obj_id = first_content_obj_id + page_count

    objects: List[bytes] = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    kids_refs = " ".join([f"{first_page_obj_id + i} 0 R" for i in range(page_count)])
    objects.append(f"2 0 obj\n<< /Type /Pages /Kids [{kids_refs}] /Count {page_count} >>\nendobj\n".encode("ascii"))

    for i in range(page_count):
        page_obj_id = first_page_obj_id + i
        content_obj_id = first_content_obj_id + i
        page_obj = (
            f"{page_obj_id} 0 obj\n"
            f"<< /Type /Page /Parent {pages_obj_id} 0 R "
            f"/MediaBox [0 0 {page_w} {page_h}] "
            f"/Resources << /Font << /F1 {font_obj_id} 0 R >> >> "
            f"/Contents {content_obj_id} 0 R >>\nendobj\n"
        ).encode("ascii")
        objects.append(page_obj)

    for i, stream in enumerate(streams):
        content_obj_id = first_content_obj_id + i
        content_obj = (
            f"{content_obj_id} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream\nendobj\n"
        )
        objects.append(content_obj)

    objects.append(f"{font_obj_id} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n".encode("ascii"))

    header = b"%PDF-1.4\n"
    parts = [header]
    offsets = [0]
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        parts.append(obj)
        pos += len(obj)

    xref_start = pos
    xref = [f"xref\n0 {len(objects) + 1}\n".encode("ascii")]
    xref.append(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("ascii"))

    trailer = (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_start).encode("ascii")
        + b"\n%%EOF\n"
    )
    return b"".join(parts + xref + [trailer])


def _build_polished_pdf(report: Report, session: Session, payload: dict, clinician_notes: str) -> bytes:
    aggregate = payload.get("aggregate") if isinstance(payload.get("aggregate"), dict) else {}
    weekly_mode = aggregate.get("mode") == "weekly"
    metrics = (aggregate.get("metrics_summary") if weekly_mode else None) or payload.get("metrics_summary") or {}
    series = payload.get("metrics_series_preview") or {}
    metric_names = list(metrics.keys()) or list(series.keys())
    metric_names = sorted(metric_names)
    report_type = str(report.report_type or "").strip().lower()
    fall_risk = report_type in ("fall_risk_summary", "weekly_fall_risk_summary")
    weekly_title = "Weekly Rollup" if weekly_mode else "Session Report"
    priority_fall = ["asymmetry_index", "sway_path", "cop_v", "stability_score", "symmetry_index", "stance_pct", "swing_pct", "total_load", "cop_x", "cop_y"]
    if fall_risk:
        prioritized = [n for n in priority_fall if n in metric_names]
        tail = [n for n in metric_names if n not in prioritized]
        metric_names = prioritized + tail

    def make_ops() -> tuple[List[str], dict]:
        ops: List[str] = []

        def rect_fill(x: float, y: float, w: float, h: float, color_rgb: tuple[float, float, float]):
            r, g, b = color_rgb
            ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
            ops.append(f"{x:.1f} {y:.1f} {w:.1f} {h:.1f} re f")

        def rect_stroke(x: float, y: float, w: float, h: float, color_rgb: tuple[float, float, float], line_width: float = 1.0):
            r, g, b = color_rgb
            ops.append(f"{line_width:.2f} w")
            ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG")
            ops.append(f"{x:.1f} {y:.1f} {w:.1f} {h:.1f} re S")

        def line(x1: float, y1: float, x2: float, y2: float, color_rgb: tuple[float, float, float], line_width: float = 1.0):
            r, g, b = color_rgb
            ops.append(f"{line_width:.2f} w")
            ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG")
            ops.append(f"{x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S")

        def text(x: float, y: float, value: str, size: int = 11, color_rgb: tuple[float, float, float] = (0.1, 0.11, 0.12)):
            escaped = _escape_pdf_text(value)
            r, g, b = color_rgb
            ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
            ops.append("BT")
            ops.append(f"/F1 {size} Tf")
            ops.append(f"{x:.1f} {y:.1f} Td")
            ops.append(f"({escaped}) Tj")
            ops.append("ET")

        return ops, {"rect_fill": rect_fill, "rect_stroke": rect_stroke, "line": line, "text": text}

    streams: List[bytes] = []

    # Page 1: Overview + visual charts
    ops, d = make_ops()
    rect_fill, rect_stroke, line, text = d["rect_fill"], d["rect_stroke"], d["line"], d["text"]
    rect_fill(0, 0, 612, 792, (0.98, 0.98, 0.99))
    header_color = (0.58, 0.08, 0.08) if fall_risk else (0.00, 0.125, 0.271)
    rect_fill(24, 736, 564, 40, header_color)
    if weekly_mode and fall_risk:
        title = "InsolePro Weekly Fall Risk Assessment"
    elif weekly_mode:
        title = "InsolePro Weekly Clinical Report"
    else:
        title = "InsolePro Fall Risk Assessment Report" if fall_risk else "InsolePro Clinical Report"
    text(36, 753, title, 15, (1, 1, 1))
    text(392, 753, f"Report #{report.report_id}", 10, (0.82, 0.9, 1))

    rect_fill(24, 675, 564, 50, (0.93, 0.95, 0.97))
    text(36, 706, f"Patient: {session.patient_id or '-'}", 10)
    if weekly_mode:
        text(180, 706, f"Window: {aggregate.get('window_start', '-')} to {aggregate.get('window_end', '-')}", 10)
        text(36, 688, f"Sessions in Week: {aggregate.get('session_count', '-')}", 10)
        text(320, 688, f"Anchor Session: {aggregate.get('anchor_session_id', session.session_id)}", 10)
        text(320, 678, f"Generated: {report.generated_at.isoformat() if report.generated_at else '-'}", 10)
    else:
        text(180, 706, f"Session: {session.session_id}", 10)
        text(320, 706, f"Assessment: {session.source or 'Assessment'}", 10)
        text(36, 688, f"Risk: {session.risk_label or 'not classified'} ({session.risk_score if session.risk_score is not None else '-'})", 10)
        text(320, 688, f"Generated: {report.generated_at.isoformat() if report.generated_at else '-'}", 10)

    summary_heading = "Fall-Risk Indicators (All Metrics - Avg Values)" if fall_risk else "Metric Summary (All Metrics - Avg Values)"
    if weekly_mode:
        summary_heading = "Weekly " + summary_heading
    text(24, 655, summary_heading, 11, (0.00, 0.125, 0.271))
    chart_x, chart_y, chart_w, chart_h = 24.0, 495.0, 564.0, 148.0
    rect_stroke(chart_x, chart_y, chart_w, chart_h, (0.72, 0.75, 0.8))
    line(chart_x + 36, chart_y + 22, chart_x + 36, chart_y + chart_h - 12, (0.55, 0.58, 0.62), 0.8)
    line(chart_x + 36, chart_y + 22, chart_x + chart_w - 12, chart_y + 22, (0.55, 0.58, 0.62), 0.8)

    avg_values = [float(metrics.get(name, {}).get("avg", 0.0)) for name in metric_names]
    max_abs = max([abs(v) for v in avg_values] + [1.0])
    n = max(1, len(metric_names))
    slot = (chart_w - 58) / n
    label_every = 1 if n <= 10 else 2 if n <= 20 else 3
    for i, name in enumerate(metric_names):
        v = float(metrics.get(name, {}).get("avg", 0.0))
        bh = max(2.0, (abs(v) / max_abs) * (chart_h - 42))
        bx = chart_x + 40 + i * slot + 1.8
        by = chart_y + 22
        bw = max(2.0, slot - 3.5)
        rect_fill(
            bx,
            by,
            bw,
            bh,
            ((0.73, 0.10, 0.10) if v >= 0 else (0.08, 0.41, 0.42)) if fall_risk else ((0.08, 0.41, 0.42) if v >= 0 else (0.73, 0.10, 0.10)),
        )
        if i % label_every == 0:
            text(bx, chart_y + 8, name[:10], 6, (0.25, 0.28, 0.31))

    if weekly_mode:
        trend_title = "Weekly Trend Plot (per-session averages)"
    else:
        trend_title = "Trend Plot (Sway Path / Fallback Composite)" if fall_risk else "Trend Plot (Total Load / Fallback Composite)"
    text(24, 476, trend_title, 11, (0.00, 0.125, 0.271))
    trend_x, trend_y, trend_w, trend_h = 24.0, 332.0, 564.0, 138.0
    rect_stroke(trend_x, trend_y, trend_w, trend_h, (0.72, 0.75, 0.8))
    line(trend_x + 34, trend_y + 20, trend_x + 34, trend_y + trend_h - 12, (0.55, 0.58, 0.62), 0.8)
    line(trend_x + 34, trend_y + 20, trend_x + trend_w - 12, trend_y + 20, (0.55, 0.58, 0.62), 0.8)

    trend_series = series.get("sway_path") or [] if fall_risk else series.get("total_load") or []
    if len(trend_series) < 2:
        trend_series = []
        for name in metric_names:
            row = metrics.get(name, {})
            if "avg" in row:
                trend_series.append({"value": float(row["avg"])})
    if len(trend_series) >= 2:
        vals = [float(row.get("value", 0.0)) for row in trend_series]
        v_min, v_max = min(vals), max(vals)
        span = max(1e-9, v_max - v_min)
        usable_w = trend_w - 52
        usable_h = trend_h - 36
        prev = None
        for i, value in enumerate(vals):
            x = trend_x + 36 + (i / max(1, len(vals) - 1)) * usable_w
            y = trend_y + 20 + ((value - v_min) / span) * usable_h
            rect_fill(x - 1.6, y - 1.6, 3.2, 3.2, (0.70, 0.12, 0.12) if fall_risk else (0.11, 0.31, 0.85))
            if prev is not None:
                line(prev[0], prev[1], x, y, (0.70, 0.12, 0.12) if fall_risk else (0.11, 0.31, 0.85), 1.3)
            prev = (x, y)

    notes_title = "Clinician Notes" if not fall_risk else "Fall Risk Interpretation Notes"
    if weekly_mode:
        notes_title = f"Weekly {notes_title}"
    text(24, 315, notes_title, 11, (0.00, 0.125, 0.271))
    rect_fill(24, 186, 564, 120, (0.97, 0.98, 0.99))
    rect_stroke(24, 186, 564, 120, (0.8, 0.83, 0.86), 0.8)
    note_lines = _wrap_text(clinician_notes or "No clinician notes provided.", 95)[:8]
    y = 288
    for line_text in note_lines:
        text(32, y, line_text, 9, (0.2, 0.22, 0.25))
        y -= 14

    text(24, 168, "Status Timeline", 11, (0.00, 0.125, 0.271))
    text(32, 150, f"Generated at {report.generated_at.isoformat() if report.generated_at else '-'}", 9, (0.2, 0.22, 0.25))
    text(32, 136, "Synced to EMR" if report.report_type == "fhir_export" else "Pending EMR sync", 9, (0.2, 0.22, 0.25))
    text(32, 122, f"Raw Frames: {payload.get('counts', {}).get('raw_frames', '-')}", 9, (0.2, 0.22, 0.25))
    text(32, 108, f"Computed Metrics: {payload.get('counts', {}).get('computed_metrics', '-')}", 9, (0.2, 0.22, 0.25))
    if weekly_mode:
        text(32, 94, f"Scope: {weekly_title} over calendar week (Mon-Sun)", 9, (0.2, 0.22, 0.25))
    else:
        text(
            32,
            94,
            "Interpretation mode: Fall-risk prioritization using the same complete metric dataset"
            if fall_risk
            else "Interpretation mode: Clinical balance prioritization using the same complete metric dataset",
            9,
            (0.2, 0.22, 0.25),
        )
    streams.append("\n".join(ops).encode("utf-8"))

    # Page 2+: Full metric detail table (all metrics)
    rows = []
    for name in metric_names:
        m = metrics.get(name, {})
        samples = series.get(name) or []
        unit = ""
        if samples:
            unit = str(samples[-1].get("unit") or "")
        rows.append(
            {
                "name": name,
                "count": int(float(m.get("count", len(samples) or 0))),
                "min": float(m.get("min", 0.0)),
                "avg": float(m.get("avg", 0.0)),
                "max": float(m.get("max", 0.0)),
                "last": float(m.get("last", 0.0)),
                "unit": unit or "-",
                "samples": len(samples),
            }
        )

    rows_per_page = 30
    for page_idx in range(max(1, (len(rows) + rows_per_page - 1) // rows_per_page)):
        ops, d = make_ops()
        rect_fill, rect_stroke, line, text = d["rect_fill"], d["rect_stroke"], d["line"], d["text"]
        rect_fill(0, 0, 612, 792, (0.985, 0.985, 0.99))
        rect_fill(24, 736, 564, 34, header_color)
        text(36, 750, f"{'Fall-Risk' if fall_risk else 'Clinical'} Metric Detail - Page {page_idx + 2}", 12, (1, 1, 1))
        text(430, 750, f"Report #{report.report_id}", 9, (0.82, 0.9, 1))

        table_x, table_y, table_w, table_h = 24.0, 64.0, 564.0, 654.0
        rect_fill(table_x, table_y, table_w, table_h, (1, 1, 1))
        rect_stroke(table_x, table_y, table_w, table_h, (0.72, 0.75, 0.8), 0.8)

        header_y = 700
        rect_fill(table_x, header_y, table_w, 20, (0.93, 0.95, 0.97))
        text(30, 706, "Metric", 8, (0.0, 0.125, 0.271))
        text(150, 706, "Count", 8, (0.0, 0.125, 0.271))
        text(205, 706, "Min", 8, (0.0, 0.125, 0.271))
        text(260, 706, "Avg", 8, (0.0, 0.125, 0.271))
        text(315, 706, "Max", 8, (0.0, 0.125, 0.271))
        text(370, 706, "Last", 8, (0.0, 0.125, 0.271))
        text(425, 706, "Unit", 8, (0.0, 0.125, 0.271))
        text(485, 706, "Samples", 8, (0.0, 0.125, 0.271))

        start = page_idx * rows_per_page
        chunk = rows[start : start + rows_per_page]
        y = 688
        for idx, row in enumerate(chunk):
            if idx % 2 == 0:
                rect_fill(table_x + 1, y - 12, table_w - 2, 14, (0.985, 0.99, 0.995))
            text(30, y, str(row["name"])[:18], 8, (0.16, 0.18, 0.2))
            text(150, y, str(row["count"]), 8, (0.16, 0.18, 0.2))
            text(205, y, f"{row['min']:.3f}", 8, (0.16, 0.18, 0.2))
            text(260, y, f"{row['avg']:.3f}", 8, (0.16, 0.18, 0.2))
            text(315, y, f"{row['max']:.3f}", 8, (0.16, 0.18, 0.2))
            text(370, y, f"{row['last']:.3f}", 8, (0.16, 0.18, 0.2))
            text(425, y, str(row["unit"])[:8], 8, (0.16, 0.18, 0.2))
            text(485, y, str(row["samples"]), 8, (0.16, 0.18, 0.2))
            y -= 14

        footer_scope = (
            f"Weekly {aggregate.get('window_start', '-')} to {aggregate.get('window_end', '-')}"
            if weekly_mode
            else f"Session {session.session_id} · Source {session.source or 'Assessment'}"
        )
        text(24, 42, footer_scope, 9, (0.35, 0.38, 0.42))
        text(390, 42, f"Rows {start + 1}-{start + len(chunk)} of {len(rows)}", 9, (0.35, 0.38, 0.42))
        streams.append("\n".join(ops).encode("utf-8"))

    return _build_pdf_from_streams(streams)


def _report_dir() -> Path:
    p = Path(getattr(settings, "REPORTS_DIR", settings.BASE_DIR / "generated_reports"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _serialize_report(r: Report) -> dict:
    return {
        "report_id": r.report_id,
        "session_id": r.session_id,
        "patient_id": r.session.patient_id,
        "started_at_us": r.session.started_at_us,
        "session_source": r.session.source,
        "risk_label": r.session.risk_label,
        "risk_score": r.session.risk_score,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "report_type": r.report_type,
        "pdf_file_path": r.pdf_file_path,
        "payload": r.payload,
        "clinician_notes": r.clinician_notes,
    }


def _metrics_summary(session: Session) -> Dict[str, Dict[str, float]]:
    summary: Dict[str, Dict[str, float]] = {}
    rows = ComputedMetric.objects.filter(session=session).values("metric_name", "metric_value")
    buckets: Dict[str, List[float]] = {}
    for row in rows:
        buckets.setdefault(row["metric_name"], []).append(float(row["metric_value"]))

    for name, vals in buckets.items():
        summary[name] = {
            "count": len(vals),
            "min": min(vals),
            "max": max(vals),
            "avg": sum(vals) / len(vals),
            "last": vals[-1],
        }
    return summary


def _metrics_summary_for_sessions(sessions: List[Session]) -> Dict[str, Dict[str, float]]:
    summary: Dict[str, Dict[str, float]] = {}
    if not sessions:
        return summary

    session_ids = [s.session_id for s in sessions]
    rows = ComputedMetric.objects.filter(session_id__in=session_ids).values("metric_name", "metric_value")
    buckets: Dict[str, List[float]] = {}
    for row in rows:
        buckets.setdefault(row["metric_name"], []).append(float(row["metric_value"]))

    for name, vals in buckets.items():
        if not vals:
            continue
        summary[name] = {
            "count": len(vals),
            "min": min(vals),
            "max": max(vals),
            "avg": sum(vals) / len(vals),
            "last": vals[-1],
        }
    return summary


def _weekly_series_preview(per_session_metrics: List[dict], metric_names: List[str]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for metric in metric_names:
        points = []
        for idx, row in enumerate(per_session_metrics):
            m = row.get("metrics", {}).get(metric, {})
            if m.get("avg") is None:
                continue
            points.append(
                {
                    "ts_us": row.get("started_at_us"),
                    "value": float(m.get("avg")),
                    "unit": m.get("unit") or "",
                    "ordinal": idx + 1,
                }
            )
        if points:
            out[metric] = points
    return out


def _build_weekly_payload(patient_id: int, week_start_date: date, sessions: List[Session], anchor_session: Session) -> dict:
    week_end_date = week_start_date + timedelta(days=6)
    session_ids = [s.session_id for s in sessions]
    metrics_summary = _metrics_summary_for_sessions(sessions)
    metric_rows = list(
        ComputedMetric.objects.filter(session_id__in=session_ids)
        .order_by("session__started_at_us", "ts_us", "metric_id")
        .values("session_id", "metric_name", "metric_value", "unit")
    )
    by_session_metric: Dict[tuple[int, str], List[dict]] = {}
    for row in metric_rows:
        key = (int(row["session_id"]), str(row["metric_name"]))
        by_session_metric.setdefault(key, []).append(
            {
                "value": float(row["metric_value"]),
                "unit": row["unit"] or "",
            }
        )

    per_session_metrics = []
    for s in sessions:
        session_metrics = {}
        metric_names = {k[1] for k in by_session_metric.keys() if k[0] == s.session_id}
        for metric_name in sorted(metric_names):
            values = [v["value"] for v in by_session_metric.get((s.session_id, metric_name), [])]
            if not values:
                continue
            unit = by_session_metric[(s.session_id, metric_name)][-1]["unit"]
            session_metrics[metric_name] = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "last": values[-1],
                "unit": unit,
            }
        per_session_metrics.append(
            {
                "session_id": s.session_id,
                "started_at_us": s.started_at_us,
                "ended_at_us": s.ended_at_us,
                "source": s.source,
                "risk_label": s.risk_label,
                "risk_score": s.risk_score,
                "raw_frames": s.raw_frames.count(),
                "computed_metrics": s.computed_metrics.count(),
                "metrics": session_metrics,
            }
        )

    metric_names = sorted(metrics_summary.keys())
    return {
        "session": {
            "session_id": anchor_session.session_id,
            "patient_id": anchor_session.patient_id,
            "device_id": anchor_session.device_id,
            "started_at_us": anchor_session.started_at_us,
            "ended_at_us": anchor_session.ended_at_us,
            "source": anchor_session.source,
            "risk_label": anchor_session.risk_label,
            "risk_score": anchor_session.risk_score,
        },
        "counts": {
            "raw_frames": sum(s.raw_frames.count() for s in sessions),
            "computed_metrics": sum(s.computed_metrics.count() for s in sessions),
        },
        "metrics_summary": metrics_summary,
        "metrics_series_preview": _weekly_series_preview(per_session_metrics, metric_names),
        "aggregate": {
            "mode": "weekly",
            "patient_id": patient_id,
            "window_start": week_start_date.isoformat(),
            "window_end": week_end_date.isoformat(),
            "session_ids": session_ids,
            "session_count": len(session_ids),
            "anchor_session_id": anchor_session.session_id,
            "metrics_summary": metrics_summary,
            "per_session_metrics": per_session_metrics,
        },
    }


def _write_report_pdf(report: Report) -> Path:
    session = report.session
    payload = report.payload if isinstance(report.payload, dict) else {}
    if not isinstance(payload.get("counts"), dict):
        payload["counts"] = {
            "raw_frames": session.raw_frames.count(),
            "computed_metrics": session.computed_metrics.count(),
        }
    if not isinstance(payload.get("metrics_summary"), dict):
        payload["metrics_summary"] = _metrics_summary(session)
    if not isinstance(payload.get("metrics_series_preview"), dict):
        payload["metrics_series_preview"] = _metrics_series_preview(session)

    report.payload = payload
    pdf_bytes = _build_polished_pdf(report, session, payload, report.clinician_notes or "")
    pdf_path = _report_dir() / f"report_{report.report_id}.pdf"
    pdf_path.write_bytes(pdf_bytes)
    report.pdf_file_path = str(pdf_path)
    report.save(update_fields=["payload", "pdf_file_path"])
    return pdf_path


@require_POST
def generate_report(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    data = _json_body(request)
    scope = str(data.get("scope") or "single").strip().lower() or "single"
    report_type = (data.get("report_type") or "clinical_summary").strip() or "clinical_summary"
    clinician_notes = (data.get("clinician_notes") or "").strip()

    if scope == "weekly":
        raw_patient_id = data.get("patient_id")
        raw_week_start = (data.get("week_start") or "").strip()
        if raw_patient_id is None:
            return JsonResponse({"detail": "patient_id is required for weekly scope"}, status=400)
        if not raw_week_start:
            return JsonResponse({"detail": "week_start is required for weekly scope"}, status=400)
        try:
            patient_id = int(raw_patient_id)
        except (TypeError, ValueError):
            return JsonResponse({"detail": "patient_id must be an integer"}, status=400)
        try:
            week_start_date = date.fromisoformat(raw_week_start)
        except ValueError:
            return JsonResponse({"detail": "week_start must be YYYY-MM-DD"}, status=400)
        if week_start_date.weekday() != 0:
            return JsonResponse({"detail": "week_start must be a Monday date"}, status=400)

        tz = _clinic_tz()
        week_end_date = week_start_date + timedelta(days=6)
        start_us = _date_to_us_start(week_start_date, tz)
        end_us = _date_to_us_end(week_end_date, tz)
        sessions = list(
            Session.objects.filter(
                patient_id=patient_id,
                started_at_us__gte=start_us,
                started_at_us__lte=end_us,
            ).order_by("started_at_us", "session_id")
        )
        if not sessions:
            return JsonResponse({"detail": "no sessions found for patient in selected week"}, status=400)

        anchor_session = sessions[-1]
        payload = _build_weekly_payload(patient_id, week_start_date, sessions, anchor_session)
        if report_type not in ("weekly_clinical_summary", "weekly_fall_risk_summary"):
            report_type = "weekly_clinical_summary"
        report = Report.objects.create(
            session=anchor_session,
            report_type=report_type,
            payload=payload,
            clinician_notes=clinician_notes,
        )
    else:
        session_id = data.get("session_id")
        if session_id is None:
            return JsonResponse({"detail": "session_id is required"}, status=400)

        try:
            session = Session.objects.get(pk=int(session_id))
        except (ValueError, Session.DoesNotExist):
            return JsonResponse({"detail": "invalid session_id"}, status=400)

        payload = {
            "session": {
                "session_id": session.session_id,
                "patient_id": session.patient_id,
                "device_id": session.device_id,
                "started_at_us": session.started_at_us,
                "ended_at_us": session.ended_at_us,
                "source": session.source,
                "risk_label": session.risk_label,
                "risk_score": session.risk_score,
            },
            "counts": {
                "raw_frames": session.raw_frames.count(),
                "computed_metrics": session.computed_metrics.count(),
            },
            "metrics_summary": _metrics_summary(session),
            "metrics_series_preview": _metrics_series_preview(session),
        }
        if report_type not in ("clinical_summary", "fall_risk_summary", "fhir_export"):
            report_type = "clinical_summary"
        report = Report.objects.create(
            session=session,
            report_type=report_type,
            payload=payload,
            clinician_notes=clinician_notes,
        )

    _write_report_pdf(report)

    return JsonResponse(_serialize_report(report), status=201)


@require_GET
def reports(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    qs = Report.objects.all().order_by("-report_id")
    session_id = request.GET.get("session_id")
    if session_id is not None:
        try:
            qs = qs.filter(session_id=int(session_id))
        except ValueError:
            return JsonResponse({"detail": "session_id must be an integer"}, status=400)
    patient_id = request.GET.get("patient_id")
    if patient_id is not None:
        try:
            qs = qs.filter(session__patient_id=int(patient_id))
        except ValueError:
            return JsonResponse({"detail": "patient_id must be an integer"}, status=400)
    report_type = (request.GET.get("report_type") or "").strip()
    if report_type:
        qs = qs.filter(report_type=report_type)

    return JsonResponse({"items": [_serialize_report(r) for r in qs]})


@require_GET
def report_detail(request: HttpRequest, report_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        report = Report.objects.get(pk=report_id)
    except Report.DoesNotExist:
        return JsonResponse({"detail": "report not found"}, status=404)

    return JsonResponse(_serialize_report(report))


@require_GET
def report_download(request: HttpRequest, report_id: int):
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        report = Report.objects.get(pk=report_id)
    except Report.DoesNotExist:
        return JsonResponse({"detail": "report not found"}, status=404)

    pdf_path = _write_report_pdf(report)

    return FileResponse(pdf_path.open("rb"), content_type="application/pdf", filename=pdf_path.name)
