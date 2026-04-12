# API Reference (Implemented)

Last Verified: 2026-04-11  
Owner: Backend Engineering  
Code References: `wbs/wbs/*_urls.py`, `wbs/wbs/*_views.py`  
Test References: `wbs/wbs/tests/test_auth.py`, `wbs/wbs/tests/test_*_api.py`

Base URL: `http://localhost:8000`  
Auth: Django session cookie + CSRF for mutating methods.

## Auth
- `GET /api/auth/csrf/`: returns `{csrfToken}` and sets CSRF cookie.
- `POST /api/auth/register/`: requires `username`, `password`; creates authenticated user.
- `POST /api/auth/login/`: requires `username`, `password`.
- `POST /api/auth/logout/`: logs out session.
- `GET /api/auth/me/`: returns authenticated identity, `401` when unauthenticated.

## Overview
- `GET /api/overview/`: health, auth state, entity counts, latest ids, timestamp.

## Patients
- `GET /api/patients/?external_id=...`
- `POST /api/patients/`
- `GET/PATCH/DELETE /api/patients/<patient_id>/`
- Common errors: `400` invalid payload, `404` not found, `409` duplicate `external_id`.

## Devices + Device Operations
- `GET /api/devices/?serial_number=...`
- `POST /api/devices/`
- `GET/PATCH/DELETE /api/devices/<device_id>/`
- `POST /api/devices/pair/` with `device_id` or `serial_number`.
- `GET /api/devices/<device_id>/status/`
- `POST /api/devices/<device_id>/firmware/update/`
- `GET /api/devices/<device_id>/firmware/`

## Calibration Profiles + Jobs
- `GET /api/calibration-profiles/?device_id=...&is_active=true|false`
- `POST /api/calibration-profiles/`
- `GET/PATCH/DELETE /api/calibration-profiles/<calibration_profile_id>/`
- `POST /api/calibration/run/`
- `GET /api/calibration/run/<device_id>/`

## Sessions
- `GET /api/sessions/?patient_id=...&device_id=...`
- `POST /api/sessions/start/`
- `POST /api/sessions/<session_id>/frames/`
- `POST /api/sessions/<session_id>/end/`
- `GET /api/sessions/<session_id>/`
- `GET /api/sessions/<session_id>/metrics/?metric_name=...&ts_from=...&ts_to=...&limit=...`
- `GET /api/sessions/compare/?session_ids=1,2&metric_name=...`

## Reports
- `POST /api/reports/generate/`
- Single mode: provide `session_id`.
- Weekly mode: provide `scope=weekly`, `patient_id`, Monday `week_start`, optional weekly report type.
- `GET /api/reports/?session_id=...&patient_id=...&report_type=...`
- `GET /api/reports/<report_id>/`
- `GET /api/reports/<report_id>/download/` (always regenerates latest PDF from payload).

## FHIR
- `POST /api/fhir/export/session/<session_id>/`: create `fhir_export` report payload.
- `GET /api/fhir/export/session/<session_id>/`: fetch latest bundle for session.

## Annotations
- `GET /api/annotations/?patient_id=...&session_id=...&report_id=...`
- `POST /api/annotations/`
- `GET/PATCH/DELETE /api/annotations/<annotation_id>/`

## Clinician UI Preferences
- `GET /api/ui-preferences/`: returns user preference row with `sensor_layout`.
- `PATCH /api/ui-preferences/`: updates `sensor_layout` with `left` and `right` 12-point arrays.

## Error Model
- `401`: authentication required.
- `400`: validation/input/type errors.
- `404`: object missing.
- `409`: conflict/duplicate for constrained resources.
- Error payload shape: `{"detail": "..."}` (some endpoints include extra fields like `missing_session_ids`).

## Versioning Strategy
- Current API maturity: `prototype-v2`.
- Backward-incompatible changes must:
- update this reference
- update `docs/CHANGELOG_DOCS.md`
- update affected tests under `wbs/wbs/tests/`.
