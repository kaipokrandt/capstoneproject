import json
import time
from datetime import date
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from .models import (
    Annotation,
    CalibrationProfile,
    ClinicianUiPreference,
    Device,
    Patient,
    Report,
    Session,
    default_sensor_layout,
)


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


def _parse_date(value, field_name: str):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format")


def _now_us() -> int:
    return int(time.time() * 1_000_000)


def _coerce_duration_seconds(value, default_seconds: int = 8) -> float:
    if value is None:
        return float(default_seconds)
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise ValueError("duration_sec must be numeric")
    if seconds < 0:
        raise ValueError("duration_sec must be >= 0")
    return seconds


def _refresh_firmware_update(device: Device) -> dict:
    metadata = device.metadata if isinstance(device.metadata, dict) else {}
    update = metadata.get("firmware_update")
    if not isinstance(update, dict):
        return {
            "status": "idle",
            "target_version": None,
            "requested_at_us": None,
            "started_at_us": None,
            "completed_at_us": None,
            "progress_pct": 0,
            "duration_sec": None,
        }

    if update.get("status") == "in_progress":
        now_us = _now_us()
        started_at_us = int(update.get("started_at_us") or now_us)
        duration_sec = float(update.get("duration_sec") or 0.0)
        elapsed_sec = max(0.0, (now_us - started_at_us) / 1_000_000.0)
        if duration_sec <= 0:
            progress_pct = 100
        else:
            progress_pct = min(100, int(round((elapsed_sec / duration_sec) * 100)))
        update["progress_pct"] = progress_pct
        if progress_pct >= 100:
            update["status"] = "completed"
            update["completed_at_us"] = now_us
            target_version = (update.get("target_version") or "").strip()
            if target_version:
                device.firmware_version = target_version
        metadata["firmware_update"] = update
        device.metadata = metadata
        device.save(update_fields=["metadata", "firmware_version", "updated_at"])
    return update


def _refresh_calibration_job(device: Device) -> dict:
    metadata = device.metadata if isinstance(device.metadata, dict) else {}
    job = metadata.get("calibration_job")
    if not isinstance(job, dict):
        return {
            "status": "idle",
            "started_at_us": None,
            "completed_at_us": None,
            "progress_pct": 0,
            "duration_sec": None,
            "profile_name": None,
            "version": None,
            "created_profile_id": None,
        }

    changed = False
    if job.get("status") == "in_progress":
        now_us = _now_us()
        started_at_us = int(job.get("started_at_us") or now_us)
        duration_sec = float(job.get("duration_sec") or 0.0)
        elapsed_sec = max(0.0, (now_us - started_at_us) / 1_000_000.0)
        if duration_sec <= 0:
            progress_pct = 100
        else:
            progress_pct = min(100, int(round((elapsed_sec / duration_sec) * 100)))
        job["progress_pct"] = progress_pct
        if progress_pct >= 100:
            job["status"] = "completed"
            job["completed_at_us"] = now_us
        changed = True

    if job.get("status") == "completed" and not job.get("created_profile_id"):
        profile_name = (job.get("profile_name") or "").strip() or "auto-calibration"
        version = (job.get("version") or "").strip() or "auto"
        parameters = job.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}
        CalibrationProfile.objects.filter(device=device, is_active=True).update(is_active=False)
        profile = CalibrationProfile.objects.create(
            device=device,
            profile_name=profile_name,
            version=version,
            parameters=parameters,
            is_active=True,
        )
        job["created_profile_id"] = profile.calibration_profile_id
        changed = True

    if changed:
        metadata["calibration_job"] = job
        device.metadata = metadata
        device.save(update_fields=["metadata", "updated_at"])
    return job


def _serialize_patient(p: Patient) -> dict:
    return {
        "patient_id": p.patient_id,
        "external_id": p.external_id,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "sex": p.sex,
        "metadata": p.metadata,
    }


def _serialize_device(d: Device) -> dict:
    return {
        "device_id": d.device_id,
        "serial_number": d.serial_number,
        "model": d.model,
        "firmware_version": d.firmware_version,
        "metadata": d.metadata,
    }


def _serialize_calibration(c: CalibrationProfile) -> dict:
    return {
        "calibration_profile_id": c.calibration_profile_id,
        "device_id": c.device_id,
        "profile_name": c.profile_name,
        "version": c.version,
        "parameters": c.parameters,
        "is_active": c.is_active,
    }


def _serialize_annotation(a: Annotation) -> dict:
    return {
        "annotation_id": a.annotation_id,
        "patient_id": a.patient_id,
        "session_id": a.session_id,
        "report_id": a.report_id,
        "author": a.author,
        "body": a.body,
        "metadata": a.metadata,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _coerce_sensor_layout(raw_layout):
    default_layout = default_sensor_layout()
    if not isinstance(raw_layout, dict):
        raise ValueError("sensor_layout must be an object")

    left = raw_layout.get("left")
    right = raw_layout.get("right")
    if not isinstance(left, list) or not isinstance(right, list):
        raise ValueError("sensor_layout must include left and right arrays")
    if len(left) != len(default_layout["left"]) or len(right) != len(default_layout["right"]):
        raise ValueError("sensor_layout must include 12 sensors for each foot")

    def _sanitize(entries):
        out = []
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("each sensor must be an object")
            try:
                x = float(item.get("x"))
                y = float(item.get("y"))
                w = float(item.get("w", 1.0))
            except (TypeError, ValueError):
                raise ValueError("sensor values x,y,w must be numeric")
            if not (0.0 <= x <= 1.0):
                raise ValueError("sensor x must be between 0 and 1")
            if not (0.0 <= y <= 1.0):
                raise ValueError("sensor y must be between 0 and 1")
            if not (0.4 <= w <= 1.6):
                raise ValueError("sensor w must be between 0.4 and 1.6")
            out.append({"x": x, "y": y, "w": w})
        return out

    return {"left": _sanitize(left), "right": _sanitize(right)}


def _serialize_ui_preference(pref: ClinicianUiPreference) -> dict:
    return {
        "preference_id": pref.preference_id,
        "user_id": pref.user_id,
        "sensor_layout": pref.sensor_layout,
        "updated_at": pref.updated_at.isoformat() if pref.updated_at else None,
    }


@require_http_methods(["GET", "POST"])
def patients(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    if request.method == "GET":
        qs = Patient.objects.all().order_by("patient_id")
        external_id = (request.GET.get("external_id") or "").strip()
        if external_id:
            qs = qs.filter(external_id=external_id)
        return JsonResponse({"items": [_serialize_patient(p) for p in qs]})

    data = _json_body(request)
    external_id = (data.get("external_id") or "").strip()
    if not external_id:
        return JsonResponse({"detail": "external_id is required"}, status=400)

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return JsonResponse({"detail": "metadata must be an object"}, status=400)

    try:
        dob = _parse_date(data.get("date_of_birth"), "date_of_birth")
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    if Patient.objects.filter(external_id=external_id).exists():
        return JsonResponse({"detail": "external_id already exists"}, status=409)
    patient = Patient.objects.create(
        external_id=external_id,
        first_name=(data.get("first_name") or "").strip(),
        last_name=(data.get("last_name") or "").strip(),
        date_of_birth=dob,
        sex=(data.get("sex") or "").strip(),
        metadata=metadata,
    )

    return JsonResponse(_serialize_patient(patient), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def patient_detail(request: HttpRequest, patient_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        patient = Patient.objects.get(pk=patient_id)
    except Patient.DoesNotExist:
        return JsonResponse({"detail": "patient not found"}, status=404)

    if request.method == "GET":
        return JsonResponse(_serialize_patient(patient))

    if request.method == "DELETE":
        patient.delete()
        return JsonResponse({"detail": "deleted"})

    data = _json_body(request)
    if "external_id" in data:
        patient.external_id = (data.get("external_id") or "").strip()
    if "first_name" in data:
        patient.first_name = (data.get("first_name") or "").strip()
    if "last_name" in data:
        patient.last_name = (data.get("last_name") or "").strip()
    if "sex" in data:
        patient.sex = (data.get("sex") or "").strip()
    if "metadata" in data:
        if not isinstance(data.get("metadata"), dict):
            return JsonResponse({"detail": "metadata must be an object"}, status=400)
        patient.metadata = data.get("metadata")
    if "date_of_birth" in data:
        try:
            patient.date_of_birth = _parse_date(data.get("date_of_birth"), "date_of_birth")
        except ValueError as e:
            return JsonResponse({"detail": str(e)}, status=400)

    if Patient.objects.filter(external_id=patient.external_id).exclude(pk=patient.pk).exists():
        return JsonResponse({"detail": "external_id already exists"}, status=409)
    patient.save()
    return JsonResponse(_serialize_patient(patient))


@require_http_methods(["GET", "POST"])
def devices(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    if request.method == "GET":
        qs = Device.objects.all().order_by("device_id")
        serial_number = (request.GET.get("serial_number") or "").strip()
        if serial_number:
            qs = qs.filter(serial_number=serial_number)
        return JsonResponse({"items": [_serialize_device(d) for d in qs]})

    data = _json_body(request)
    serial_number = (data.get("serial_number") or "").strip()
    if not serial_number:
        return JsonResponse({"detail": "serial_number is required"}, status=400)

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return JsonResponse({"detail": "metadata must be an object"}, status=400)

    if Device.objects.filter(serial_number=serial_number).exists():
        return JsonResponse({"detail": "serial_number already exists"}, status=409)
    device = Device.objects.create(
        serial_number=serial_number,
        model=(data.get("model") or "").strip(),
        firmware_version=(data.get("firmware_version") or "").strip(),
        metadata=metadata,
    )
    return JsonResponse(_serialize_device(device), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def device_detail(request: HttpRequest, device_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        return JsonResponse({"detail": "device not found"}, status=404)

    if request.method == "GET":
        return JsonResponse(_serialize_device(device))

    if request.method == "DELETE":
        device.delete()
        return JsonResponse({"detail": "deleted"})

    data = _json_body(request)
    if "serial_number" in data:
        device.serial_number = (data.get("serial_number") or "").strip()
    if "model" in data:
        device.model = (data.get("model") or "").strip()
    if "firmware_version" in data:
        device.firmware_version = (data.get("firmware_version") or "").strip()
    if "metadata" in data:
        if not isinstance(data.get("metadata"), dict):
            return JsonResponse({"detail": "metadata must be an object"}, status=400)
        device.metadata = data.get("metadata")

    if Device.objects.filter(serial_number=device.serial_number).exclude(pk=device.pk).exists():
        return JsonResponse({"detail": "serial_number already exists"}, status=409)
    device.save()
    return JsonResponse(_serialize_device(device))


@require_http_methods(["GET", "POST"])
def calibration_profiles(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    if request.method == "GET":
        qs = CalibrationProfile.objects.all().order_by("calibration_profile_id")
        device_id = request.GET.get("device_id")
        if device_id is not None:
            try:
                qs = qs.filter(device_id=int(device_id))
            except ValueError:
                return JsonResponse({"detail": "device_id must be an integer"}, status=400)

        is_active = request.GET.get("is_active")
        if is_active is not None:
            flag = str(is_active).lower()
            if flag not in {"1", "0", "true", "false", "yes", "no"}:
                return JsonResponse({"detail": "is_active must be boolean-like"}, status=400)
            qs = qs.filter(is_active=flag in {"1", "true", "yes"})

        return JsonResponse({"items": [_serialize_calibration(c) for c in qs]})

    data = _json_body(request)
    device_id = data.get("device_id")
    profile_name = (data.get("profile_name") or "").strip()
    if device_id is None or not profile_name:
        return JsonResponse({"detail": "device_id and profile_name are required"}, status=400)

    try:
        device = Device.objects.get(pk=int(device_id))
    except (ValueError, Device.DoesNotExist):
        return JsonResponse({"detail": "invalid device_id"}, status=400)

    parameters = data.get("parameters", {})
    if not isinstance(parameters, dict):
        return JsonResponse({"detail": "parameters must be an object"}, status=400)

    version = (data.get("version") or "").strip()
    if CalibrationProfile.objects.filter(
        device=device,
        profile_name=profile_name,
        version=version,
    ).exists():
        return JsonResponse(
            {"detail": "calibration profile with same device/profile_name/version already exists"},
            status=409,
        )
    calibration = CalibrationProfile.objects.create(
        device=device,
        profile_name=profile_name,
        version=version,
        parameters=parameters,
        is_active=bool(data.get("is_active", True)),
    )
    return JsonResponse(_serialize_calibration(calibration), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def calibration_profile_detail(request: HttpRequest, calibration_profile_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        calibration = CalibrationProfile.objects.get(pk=calibration_profile_id)
    except CalibrationProfile.DoesNotExist:
        return JsonResponse({"detail": "calibration profile not found"}, status=404)

    if request.method == "GET":
        return JsonResponse(_serialize_calibration(calibration))

    if request.method == "DELETE":
        calibration.delete()
        return JsonResponse({"detail": "deleted"})

    data = _json_body(request)
    if "device_id" in data:
        try:
            calibration.device = Device.objects.get(pk=int(data.get("device_id")))
        except (ValueError, Device.DoesNotExist):
            return JsonResponse({"detail": "invalid device_id"}, status=400)
    if "profile_name" in data:
        calibration.profile_name = (data.get("profile_name") or "").strip()
    if "version" in data:
        calibration.version = (data.get("version") or "").strip()
    if "parameters" in data:
        if not isinstance(data.get("parameters"), dict):
            return JsonResponse({"detail": "parameters must be an object"}, status=400)
        calibration.parameters = data.get("parameters")
    if "is_active" in data:
        calibration.is_active = bool(data.get("is_active"))

    if CalibrationProfile.objects.filter(
        device=calibration.device,
        profile_name=calibration.profile_name,
        version=calibration.version,
    ).exclude(pk=calibration.pk).exists():
        return JsonResponse(
            {"detail": "calibration profile with same device/profile_name/version already exists"},
            status=409,
        )
    calibration.save()
    return JsonResponse(_serialize_calibration(calibration))


@require_http_methods(["GET", "POST"])
def annotations(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    if request.method == "GET":
        qs = Annotation.objects.all().order_by("annotation_id")
        patient_id = request.GET.get("patient_id")
        if patient_id is not None:
            try:
                qs = qs.filter(patient_id=int(patient_id))
            except ValueError:
                return JsonResponse({"detail": "patient_id must be an integer"}, status=400)
        session_id = request.GET.get("session_id")
        if session_id is not None:
            try:
                qs = qs.filter(session_id=int(session_id))
            except ValueError:
                return JsonResponse({"detail": "session_id must be an integer"}, status=400)
        report_id = request.GET.get("report_id")
        if report_id is not None:
            try:
                qs = qs.filter(report_id=int(report_id))
            except ValueError:
                return JsonResponse({"detail": "report_id must be an integer"}, status=400)
        author = (request.GET.get("author") or "").strip()
        if author:
            qs = qs.filter(author=author)
        return JsonResponse({"items": [_serialize_annotation(a) for a in qs]})

    data = _json_body(request)
    body = (data.get("body") or "").strip()
    if not body:
        return JsonResponse({"detail": "body is required"}, status=400)

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return JsonResponse({"detail": "metadata must be an object"}, status=400)

    patient = None
    if data.get("patient_id") is not None:
        try:
            patient = Patient.objects.get(pk=int(data.get("patient_id")))
        except (ValueError, Patient.DoesNotExist):
            return JsonResponse({"detail": "invalid patient_id"}, status=400)

    session = None
    if data.get("session_id") is not None:
        try:
            session = Session.objects.get(pk=int(data.get("session_id")))
        except (ValueError, Session.DoesNotExist):
            return JsonResponse({"detail": "invalid session_id"}, status=400)

    report = None
    if data.get("report_id") is not None:
        try:
            report = Report.objects.get(pk=int(data.get("report_id")))
        except (ValueError, Report.DoesNotExist):
            return JsonResponse({"detail": "invalid report_id"}, status=400)

    annotation = Annotation.objects.create(
        patient=patient,
        session=session,
        report=report,
        author=(data.get("author") or "").strip(),
        body=body,
        metadata=metadata,
    )
    return JsonResponse(_serialize_annotation(annotation), status=201)


@require_http_methods(["GET", "PATCH", "DELETE"])
def annotation_detail(request: HttpRequest, annotation_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        annotation = Annotation.objects.get(pk=annotation_id)
    except Annotation.DoesNotExist:
        return JsonResponse({"detail": "annotation not found"}, status=404)

    if request.method == "GET":
        return JsonResponse(_serialize_annotation(annotation))

    if request.method == "DELETE":
        annotation.delete()
        return JsonResponse({"detail": "deleted"})

    data = _json_body(request)
    if "author" in data:
        annotation.author = (data.get("author") or "").strip()
    if "body" in data:
        body = (data.get("body") or "").strip()
        if not body:
            return JsonResponse({"detail": "body cannot be empty"}, status=400)
        annotation.body = body
    if "metadata" in data:
        if not isinstance(data.get("metadata"), dict):
            return JsonResponse({"detail": "metadata must be an object"}, status=400)
        annotation.metadata = data.get("metadata")
    if "patient_id" in data:
        if data.get("patient_id") in (None, ""):
            annotation.patient = None
        else:
            try:
                annotation.patient = Patient.objects.get(pk=int(data.get("patient_id")))
            except (ValueError, Patient.DoesNotExist):
                return JsonResponse({"detail": "invalid patient_id"}, status=400)
    if "session_id" in data:
        if data.get("session_id") in (None, ""):
            annotation.session = None
        else:
            try:
                annotation.session = Session.objects.get(pk=int(data.get("session_id")))
            except (ValueError, Session.DoesNotExist):
                return JsonResponse({"detail": "invalid session_id"}, status=400)
    if "report_id" in data:
        if data.get("report_id") in (None, ""):
            annotation.report = None
        else:
            try:
                annotation.report = Report.objects.get(pk=int(data.get("report_id")))
            except (ValueError, Report.DoesNotExist):
                return JsonResponse({"detail": "invalid report_id"}, status=400)

    annotation.save()
    return JsonResponse(_serialize_annotation(annotation))


@require_http_methods(["POST"])
def pair_device(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    data = _json_body(request)
    device = None
    if data.get("device_id") is not None:
        try:
            device = Device.objects.get(pk=int(data.get("device_id")))
        except (ValueError, Device.DoesNotExist):
            return JsonResponse({"detail": "invalid device_id"}, status=400)
    else:
        serial_number = (data.get("serial_number") or "").strip()
        if not serial_number:
            return JsonResponse({"detail": "device_id or serial_number is required"}, status=400)
        device, _ = Device.objects.get_or_create(serial_number=serial_number)

    if "model" in data:
        device.model = (data.get("model") or "").strip()
    if "firmware_version" in data:
        device.firmware_version = (data.get("firmware_version") or "").strip()

    metadata = device.metadata if isinstance(device.metadata, dict) else {}
    now_us = _now_us()
    pairing = {
        "status": "paired",
        "paired_at_us": now_us,
        "paired_by": request.user.username,
    }
    connection = {
        "status": (data.get("connection_status") or "connected"),
        "quality": (data.get("connection_quality") or "good"),
        "last_seen_us": now_us,
    }
    metadata["pairing"] = pairing
    metadata["connection"] = connection
    device.metadata = metadata
    device.save()

    return JsonResponse(
        {
            "detail": "device paired",
            "device": _serialize_device(device),
            "pairing": pairing,
            "connection": connection,
        }
    )


@require_http_methods(["GET"])
def device_status(request: HttpRequest, device_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        return JsonResponse({"detail": "device not found"}, status=404)

    metadata = device.metadata if isinstance(device.metadata, dict) else {}
    pairing = metadata.get("pairing") if isinstance(metadata.get("pairing"), dict) else {}
    connection = metadata.get("connection") if isinstance(metadata.get("connection"), dict) else {}
    firmware_update = _refresh_firmware_update(device)

    return JsonResponse(
        {
            "device_id": device.device_id,
            "serial_number": device.serial_number,
            "pairing": {
                "status": pairing.get("status", "unpaired"),
                "paired_at_us": pairing.get("paired_at_us"),
                "paired_by": pairing.get("paired_by"),
            },
            "connection": {
                "status": connection.get("status", "unknown"),
                "quality": connection.get("quality", "unknown"),
                "last_seen_us": connection.get("last_seen_us"),
            },
            "firmware_update": firmware_update,
        }
    )


@require_http_methods(["POST"])
def device_firmware_update(request: HttpRequest, device_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        return JsonResponse({"detail": "device not found"}, status=404)

    data = _json_body(request)
    target_version = (data.get("target_version") or "").strip()
    if not target_version:
        return JsonResponse({"detail": "target_version is required"}, status=400)
    try:
        duration_sec = _coerce_duration_seconds(data.get("duration_sec"), default_seconds=10)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    now_us = _now_us()
    metadata = device.metadata if isinstance(device.metadata, dict) else {}
    metadata["firmware_update"] = {
        "status": "in_progress",
        "target_version": target_version,
        "requested_by": request.user.username,
        "requested_at_us": now_us,
        "started_at_us": now_us,
        "completed_at_us": None,
        "duration_sec": duration_sec,
        "progress_pct": 0,
    }
    device.metadata = metadata
    device.save(update_fields=["metadata", "updated_at"])
    update = _refresh_firmware_update(device)
    return JsonResponse({"device_id": device.device_id, "current_version": device.firmware_version, "update": update})


@require_http_methods(["GET"])
def device_firmware_status(request: HttpRequest, device_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        return JsonResponse({"detail": "device not found"}, status=404)

    update = _refresh_firmware_update(device)
    return JsonResponse({"device_id": device.device_id, "current_version": device.firmware_version, "update": update})


@require_http_methods(["POST"])
def calibration_run_start(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    data = _json_body(request)
    device_id = data.get("device_id")
    if device_id is None:
        return JsonResponse({"detail": "device_id is required"}, status=400)
    try:
        device = Device.objects.get(pk=int(device_id))
    except (ValueError, Device.DoesNotExist):
        return JsonResponse({"detail": "invalid device_id"}, status=400)

    parameters = data.get("parameters", {})
    if not isinstance(parameters, dict):
        return JsonResponse({"detail": "parameters must be an object"}, status=400)
    try:
        duration_sec = _coerce_duration_seconds(data.get("duration_sec"), default_seconds=8)
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

    now_us = _now_us()
    metadata = device.metadata if isinstance(device.metadata, dict) else {}
    metadata["calibration_job"] = {
        "status": "in_progress",
        "started_at_us": now_us,
        "completed_at_us": None,
        "duration_sec": duration_sec,
        "progress_pct": 0,
        "requested_by": request.user.username,
        "profile_name": (data.get("profile_name") or "auto-calibration"),
        "version": (data.get("version") or "auto"),
        "parameters": parameters,
        "created_profile_id": None,
    }
    device.metadata = metadata
    device.save(update_fields=["metadata", "updated_at"])
    job = _refresh_calibration_job(device)
    return JsonResponse({"device_id": device.device_id, "calibration_job": job})


@require_http_methods(["GET"])
def calibration_run_status(request: HttpRequest, device_id: int) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    try:
        device = Device.objects.get(pk=device_id)
    except Device.DoesNotExist:
        return JsonResponse({"detail": "device not found"}, status=404)

    job = _refresh_calibration_job(device)
    return JsonResponse({"device_id": device.device_id, "calibration_job": job})


@require_http_methods(["GET", "PATCH"])
def ui_preferences(request: HttpRequest) -> JsonResponse:
    auth_error = _require_auth(request)
    if auth_error is not None:
        return auth_error

    pref, _created = ClinicianUiPreference.objects.get_or_create(
        user=request.user,
        defaults={"sensor_layout": default_sensor_layout()},
    )

    if request.method == "GET":
        return JsonResponse(_serialize_ui_preference(pref))

    data = _json_body(request)
    if "sensor_layout" not in data:
        return JsonResponse({"detail": "sensor_layout is required"}, status=400)
    try:
        pref.sensor_layout = _coerce_sensor_layout(data.get("sensor_layout"))
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)
    pref.save(update_fields=["sensor_layout", "updated_at"])
    return JsonResponse(_serialize_ui_preference(pref))
