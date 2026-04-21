from datetime import datetime, timezone

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from .models import Device, Patient, Report, Session


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Unauthenticated liveness probe used by startup scripts and load balancers."""
    return JsonResponse({"status": "ok"})


@require_GET
def overview(request: HttpRequest) -> JsonResponse:
    authenticated = bool(request.user.is_authenticated)

    payload = {
        "health": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "authenticated": authenticated,
        "user": None,
        "counts": None,
        "latest": None,
    }

    if authenticated:
        payload["user"] = {
            "id": request.user.id,
            "username": request.user.get_username(),
            "email": request.user.email,
        }
        payload["counts"] = {
            "patients": Patient.objects.count(),
            "devices": Device.objects.count(),
            "sessions": Session.objects.count(),
            "reports": Report.objects.count(),
        }
        latest_session = Session.objects.order_by("-session_id").values_list("session_id", flat=True).first()
        latest_report = Report.objects.order_by("-report_id").values_list("report_id", flat=True).first()
        payload["latest"] = {
            "session_id": latest_session,
            "report_id": latest_report,
        }

    return JsonResponse(payload)
