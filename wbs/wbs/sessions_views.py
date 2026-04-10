import base64
import json
import time

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .metrics_pipeline import recompute_session_metrics
from .models import CalibrationProfile, ComputedMetric, Device, Patient, RawFrame, Session


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


def _get_object_or_none(model, pk):
    if pk is None:
        return None
    try:
        return model.objects.get(pk=pk)
    except model.DoesNotExist:
        return None


@require_POST
def start_session(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    data = _json_body(request)
    source = (data.get("source") or "").strip()
    if not source:
        return JsonResponse({"detail": "source is required"}, status=400)

    patient_id = data.get("patient_id")
    device_id = data.get("device_id")
    calibration_profile_id = data.get("calibration_profile_id")

    patient = _get_object_or_none(Patient, patient_id) if patient_id is not None else None
    device = _get_object_or_none(Device, device_id) if device_id is not None else None
    calibration = (
        _get_object_or_none(CalibrationProfile, calibration_profile_id)
        if calibration_profile_id is not None
        else None
    )

    if patient_id is not None and patient is None:
        return JsonResponse({"detail": "invalid patient_id"}, status=400)
    if device_id is not None and device is None:
        return JsonResponse({"detail": "invalid device_id"}, status=400)
    if calibration_profile_id is not None and calibration is None:
        return JsonResponse({"detail": "invalid calibration_profile_id"}, status=400)
    if calibration is not None and device is not None and calibration.device_id != device.device_id:
        return JsonResponse(
            {"detail": "calibration profile does not belong to device"},
            status=400,
        )

    started_at_us = data.get("started_at_us")
    if started_at_us is None:
        started_at_us = int(time.time() * 1_000_000)
    try:
        started_at_us = int(started_at_us)
    except (TypeError, ValueError):
        return JsonResponse({"detail": "started_at_us must be an integer"}, status=400)

    session = Session.objects.create(
        patient=patient,
        device=device,
        calibration_profile=calibration,
        started_at_us=started_at_us,
        source=source,
        notes=(data.get("notes") or ""),
    )

    return JsonResponse(
        {
            "session_id": session.session_id,
            "started_at_us": session.started_at_us,
            "source": session.source,
            "patient_id": session.patient_id,
            "device_id": session.device_id,
            "calibration_profile_id": session.calibration_profile_id,
        },
        status=201,
    )


@require_POST
def ingest_frame(request: HttpRequest, session_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        session = Session.objects.get(pk=session_id)
    except Session.DoesNotExist:
        return JsonResponse({"detail": "session not found"}, status=404)

    if session.ended_at_us is not None:
        return JsonResponse({"detail": "session already ended"}, status=409)

    data = _json_body(request)
    required_fields = ["ts_us", "gw", "gh", "battery_pct", "flags", "total_load", "adc_base64"]
    missing = [f for f in required_fields if data.get(f) is None]
    if missing:
        return JsonResponse({"detail": f"missing required fields: {', '.join(missing)}"}, status=400)

    try:
        adc_blob = base64.b64decode(data["adc_base64"], validate=True)
    except (ValueError, TypeError):
        return JsonResponse({"detail": "adc_base64 must be valid base64"}, status=400)

    try:
        ts_us = int(data["ts_us"])
        gw = int(data["gw"])
        gh = int(data["gh"])
        battery_pct = int(data["battery_pct"])
        flags = int(data["flags"])
        total_load = float(data["total_load"])
    except (TypeError, ValueError):
        return JsonResponse({"detail": "invalid numeric frame field"}, status=400)

    expected_len = gw * gh * 2
    if len(adc_blob) != expected_len:
        return JsonResponse(
            {"detail": f"adc_base64 payload size must be exactly {expected_len} bytes for gw={gw}, gh={gh}"},
            status=400,
        )

    frame = RawFrame.objects.create(
        session=session,
        ts_us=ts_us,
        gw=gw,
        gh=gh,
        battery_pct=battery_pct,
        flags=flags,
        total_load=total_load,
        adc_blob=adc_blob,
    )

    metric_rows = recompute_session_metrics(session)
    return JsonResponse({"frame_id": frame.frame_id, "metric_rows_written": metric_rows}, status=201)


@require_POST
def end_session(request: HttpRequest, session_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        session = Session.objects.get(pk=session_id)
    except Session.DoesNotExist:
        return JsonResponse({"detail": "session not found"}, status=404)

    data = _json_body(request)
    ended_at_us = data.get("ended_at_us")
    if ended_at_us is None:
        ended_at_us = int(time.time() * 1_000_000)
    try:
        session.ended_at_us = int(ended_at_us)
    except (TypeError, ValueError):
        return JsonResponse({"detail": "ended_at_us must be an integer"}, status=400)

    if data.get("risk_label") is not None:
        session.risk_label = str(data.get("risk_label"))
    if data.get("risk_score") is not None:
        try:
            session.risk_score = float(data.get("risk_score"))
        except (TypeError, ValueError):
            return JsonResponse({"detail": "risk_score must be numeric"}, status=400)

    session.save(update_fields=["ended_at_us", "risk_label", "risk_score"])
    return JsonResponse(
        {
            "session_id": session.session_id,
            "ended_at_us": session.ended_at_us,
            "risk_label": session.risk_label,
            "risk_score": session.risk_score,
        }
    )


@require_GET
def session_detail(request: HttpRequest, session_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        session = Session.objects.get(pk=session_id)
    except Session.DoesNotExist:
        return JsonResponse({"detail": "session not found"}, status=404)

    return JsonResponse(
        {
            "session_id": session.session_id,
            "started_at_us": session.started_at_us,
            "ended_at_us": session.ended_at_us,
            "source": session.source,
            "notes": session.notes,
            "risk_label": session.risk_label,
            "risk_score": session.risk_score,
            "patient_id": session.patient_id,
            "device_id": session.device_id,
            "calibration_profile_id": session.calibration_profile_id,
            "raw_frame_count": RawFrame.objects.filter(session=session).count(),
            "computed_metric_count": ComputedMetric.objects.filter(session=session).count(),
        }
    )


@require_GET
def session_metrics(request: HttpRequest, session_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        session = Session.objects.get(pk=session_id)
    except Session.DoesNotExist:
        return JsonResponse({"detail": "session not found"}, status=404)

    qs = ComputedMetric.objects.filter(session=session)

    metric_name = (request.GET.get("metric_name") or "").strip()
    if metric_name:
        names = [n.strip() for n in metric_name.split(",") if n.strip()]
        qs = qs.filter(metric_name__in=names)

    ts_from = request.GET.get("ts_from")
    if ts_from is not None:
        try:
            qs = qs.filter(ts_us__gte=int(ts_from))
        except (TypeError, ValueError):
            return JsonResponse({"detail": "ts_from must be an integer"}, status=400)

    ts_to = request.GET.get("ts_to")
    if ts_to is not None:
        try:
            qs = qs.filter(ts_us__lte=int(ts_to))
        except (TypeError, ValueError):
            return JsonResponse({"detail": "ts_to must be an integer"}, status=400)

    limit = request.GET.get("limit")
    if limit is not None:
        try:
            n = int(limit)
        except (TypeError, ValueError):
            return JsonResponse({"detail": "limit must be an integer"}, status=400)
        if n <= 0:
            return JsonResponse({"detail": "limit must be > 0"}, status=400)
    else:
        n = None

    rows = list(qs.order_by("ts_us", "metric_id").values("metric_name", "ts_us", "metric_value", "unit"))
    if n is not None:
        rows = rows[:n]

    series = {}
    for row in rows:
        name = row["metric_name"]
        if name not in series:
            series[name] = []
        series[name].append(
            {
                "ts_us": row["ts_us"],
                "value": row["metric_value"],
                "unit": row["unit"],
            }
        )

    return JsonResponse(
        {
            "session_id": session.session_id,
            "count": len(rows),
            "metric_names": sorted(series.keys()),
            "series": series,
        }
    )
