import json
from pathlib import Path
from typing import Dict, List

from django.conf import settings
from django.http import FileResponse, HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .models import ComputedMetric, Report, Session


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


@require_POST
def generate_report(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    data = _json_body(request)
    session_id = data.get("session_id")
    if session_id is None:
        return JsonResponse({"detail": "session_id is required"}, status=400)

    try:
        session = Session.objects.get(pk=int(session_id))
    except (ValueError, Session.DoesNotExist):
        return JsonResponse({"detail": "invalid session_id"}, status=400)

    report_type = (data.get("report_type") or "clinical_summary").strip() or "clinical_summary"
    clinician_notes = (data.get("clinician_notes") or "").strip()

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
    }

    report = Report.objects.create(
        session=session,
        report_type=report_type,
        payload=payload,
        clinician_notes=clinician_notes,
    )

    lines = [
        "Balance Assessment Report",
        f"Report ID: {report.report_id}",
        f"Session ID: {session.session_id}",
        f"Patient ID: {session.patient_id}",
        f"Device ID: {session.device_id}",
        f"Source: {session.source}",
        f"Raw Frames: {payload['counts']['raw_frames']}",
        f"Computed Metrics: {payload['counts']['computed_metrics']}",
        f"Risk: {session.risk_label or 'n/a'} ({session.risk_score if session.risk_score is not None else 'n/a'})",
    ]
    if clinician_notes:
        lines.append(f"Notes: {clinician_notes}")

    pdf_bytes = _build_minimal_pdf(lines)
    pdf_path = _report_dir() / f"report_{report.report_id}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    report.pdf_file_path = str(pdf_path)
    report.save(update_fields=["pdf_file_path"])

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

    if not report.pdf_file_path:
        return JsonResponse({"detail": "report PDF not available"}, status=404)

    pdf_path = Path(report.pdf_file_path)
    if not pdf_path.exists():
        return JsonResponse({"detail": "report PDF missing on disk"}, status=404)

    return FileResponse(pdf_path.open("rb"), content_type="application/pdf", filename=pdf_path.name)
