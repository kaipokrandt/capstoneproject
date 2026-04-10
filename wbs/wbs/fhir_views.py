from datetime import datetime, timezone
from typing import Dict, List

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from .models import ComputedMetric, Report, Session


def _require_auth(request: HttpRequest):
    if request.user.is_authenticated:
        return None
    return JsonResponse({"detail": "authentication required"}, status=401)


def _us_to_iso(ts_us: int | None) -> str | None:
    if ts_us is None:
        return None
    return datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc).isoformat()


def _metric_stats(session: Session) -> Dict[str, Dict[str, float]]:
    rows = ComputedMetric.objects.filter(session=session).values("metric_name", "metric_value", "unit")
    buckets: Dict[str, List[tuple[float, str | None]]] = {}
    for row in rows:
        buckets.setdefault(row["metric_name"], []).append((float(row["metric_value"]), row["unit"]))

    out: Dict[str, Dict[str, float]] = {}
    for name, vals in buckets.items():
        numbers = [v for v, _ in vals]
        out[name] = {
            "count": len(numbers),
            "min": min(numbers),
            "max": max(numbers),
            "avg": sum(numbers) / len(numbers),
            "last": numbers[-1],
            "unit": vals[-1][1] or "",
        }
    return out


def _build_bundle(session: Session) -> dict:
    stats = _metric_stats(session)

    entries = []

    if session.patient_id is not None:
        p = session.patient
        entries.append(
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": str(p.patient_id),
                    "identifier": [{"system": "urn:wbs:patient:external_id", "value": p.external_id}],
                    "name": [{"family": p.last_name, "given": [p.first_name]}],
                    "birthDate": p.date_of_birth.isoformat() if p.date_of_birth else None,
                    "gender": p.sex or "unknown",
                }
            }
        )

    if session.device_id is not None:
        d = session.device
        entries.append(
            {
                "resource": {
                    "resourceType": "Device",
                    "id": str(d.device_id),
                    "serialNumber": d.serial_number,
                    "deviceName": [{"name": d.model or "smart-insole", "type": "user-friendly-name"}],
                    "version": [{"value": d.firmware_version}] if d.firmware_version else [],
                }
            }
        )

    entries.append(
        {
            "resource": {
                "resourceType": "Encounter",
                "id": str(session.session_id),
                "status": "finished" if session.ended_at_us else "in-progress",
                "class": {"code": "AMB", "display": "ambulatory"},
                "period": {"start": _us_to_iso(session.started_at_us), "end": _us_to_iso(session.ended_at_us)},
            }
        }
    )

    for metric_name, s in stats.items():
        entries.append(
            {
                "resource": {
                    "resourceType": "Observation",
                    "status": "final",
                    "code": {"text": metric_name},
                    "subject": {"reference": f"Patient/{session.patient_id}"} if session.patient_id else None,
                    "encounter": {"reference": f"Encounter/{session.session_id}"},
                    "valueQuantity": {"value": s["last"], "unit": s["unit"]},
                    "component": [
                        {"code": {"text": "avg"}, "valueQuantity": {"value": s["avg"], "unit": s["unit"]}},
                        {"code": {"text": "min"}, "valueQuantity": {"value": s["min"], "unit": s["unit"]}},
                        {"code": {"text": "max"}, "valueQuantity": {"value": s["max"], "unit": s["unit"]}},
                        {"code": {"text": "count"}, "valueQuantity": {"value": s["count"], "unit": "samples"}},
                    ],
                }
            }
        )

    # Remove null fields in observations.
    for e in entries:
        resource = e["resource"]
        keys = [k for k, v in resource.items() if v is None]
        for k in keys:
            del resource[k]

    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "identifier": {"system": "urn:wbs:fhir-export", "value": f"session-{session.session_id}"},
        "entry": entries,
    }


@require_http_methods(["GET", "POST"])
def session_export(request: HttpRequest, session_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        session = Session.objects.get(pk=session_id)
    except Session.DoesNotExist:
        return JsonResponse({"detail": "session not found"}, status=404)

    if request.method == "POST":
        bundle = _build_bundle(session)
        report = Report.objects.create(
            session=session,
            report_type="fhir_export",
            payload=bundle,
            clinician_notes="",
        )
        return JsonResponse(
            {
                "session_id": session.session_id,
                "report_id": report.report_id,
                "report_type": report.report_type,
                "bundle": bundle,
            },
            status=201,
        )

    latest = (
        Report.objects.filter(session=session, report_type="fhir_export").order_by("-generated_at", "-report_id").first()
    )
    if latest is None:
        return JsonResponse({"detail": "no FHIR export found for session"}, status=404)

    return JsonResponse(
        {
            "session_id": session.session_id,
            "report_id": latest.report_id,
            "report_type": latest.report_type,
            "bundle": latest.payload,
        }
    )
