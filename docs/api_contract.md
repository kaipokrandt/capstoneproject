# API Contract (Prototype)

Last Verified: 2026-04-11  
Owner: Backend Engineering  
Code References: `wbs/wbs/*_urls.py`, `wbs/wbs/*_views.py`  
Test References: `wbs/wbs/tests/test_*_api.py`

Base URL: `http://localhost:8000`
Auth model: Django session cookie + CSRF token.

Canonical reference: `docs/api/api_reference.md` (authoritative and implementation-complete).  
This document is retained as a quick-start contract summary.

## Auth

### `GET /api/auth/csrf/`
Returns CSRF token and sets `csrftoken` cookie.

Response:
```json
{"csrfToken":"..."}
```

### `POST /api/auth/register/`
Body:
```json
{"username":"alice","password":"secret","email":"a@example.com"}
```

### `POST /api/auth/login/`
Body:
```json
{"username":"alice","password":"secret"}
```

### `POST /api/auth/logout/`
No body.

### `GET /api/auth/me/`
Response (authenticated):
```json
{"authenticated":true,"id":1,"username":"alice","email":"a@example.com"}
```

## Overview

### `GET /api/overview/`
Frontend startup endpoint.

Response (unauth):
```json
{"health":"ok","authenticated":false,"user":null,"counts":null,"latest":null,"timestamp":"..."}
```

Response (auth):
```json
{
  "health":"ok",
  "authenticated":true,
  "user":{"id":1,"username":"admin","email":""},
  "counts":{"patients":2,"devices":2,"sessions":4,"reports":6},
  "latest":{"session_id":4,"report_id":6},
  "timestamp":"..."
}
```

## Patients

### `GET /api/patients/?external_id=...`
### `POST /api/patients/`
Body:
```json
{"external_id":"P-001","first_name":"Sam","last_name":"Lee","date_of_birth":"1990-01-02","sex":"f","metadata":{"clinic":"A"}}
```

### `GET /api/patients/<patient_id>/`
### `PATCH /api/patients/<patient_id>/`
### `DELETE /api/patients/<patient_id>/`

## Devices

### `GET /api/devices/?serial_number=...`
### `POST /api/devices/`
Body:
```json
{"serial_number":"DEV-001","model":"wbs-v1","firmware_version":"1.0.0","metadata":{"site":"lab"}}
```

### `GET /api/devices/<device_id>/`
### `PATCH /api/devices/<device_id>/`
### `DELETE /api/devices/<device_id>/`

## Calibration Profiles

### `GET /api/calibration-profiles/?device_id=...&is_active=true|false`
### `POST /api/calibration-profiles/`
Body:
```json
{"device_id":1,"profile_name":"default","version":"v1","parameters":{"gain":1.2},"is_active":true}
```

### `GET /api/calibration-profiles/<calibration_profile_id>/`
### `PATCH /api/calibration-profiles/<calibration_profile_id>/`
### `DELETE /api/calibration-profiles/<calibration_profile_id>/`

## Annotations

### `GET /api/annotations/?patient_id=...&session_id=...&report_id=...`
### `POST /api/annotations/`
Body:
```json
{"patient_id":1,"session_id":2,"report_id":3,"author":"clinician","body":"Initial note","metadata":{"severity":"low"}}
```

### `GET /api/annotations/<annotation_id>/`
### `PATCH /api/annotations/<annotation_id>/`
### `DELETE /api/annotations/<annotation_id>/`

## Clinician UI Preferences

### `GET /api/ui-preferences/`
Returns per-authenticated-user UI preferences including sensor layout calibration points.

### `PATCH /api/ui-preferences/`
Body:
```json
{"sensor_layout":{"left":[{"x":0.5,"y":0.3,"w":0.9}],"right":[{"x":0.5,"y":0.3,"w":0.9}]}}
```
Example is abbreviated; `left` and `right` arrays must each contain 12 sensor points.

## Sessions

### `POST /api/sessions/start/`
Body:
```json
{"source":"device-stream","patient_id":1,"device_id":1,"calibration_profile_id":1,"notes":"visit"}
```

Response:
```json
{"session_id":1,"started_at_us":1700000000000000,"source":"device-stream","patient_id":1,"device_id":1,"calibration_profile_id":1}
```

### `POST /api/sessions/<session_id>/frames/`
Body:
```json
{"ts_us":1700000000000000,"gw":2,"gh":2,"battery_pct":90,"flags":0,"total_load":123.4,"adc_base64":"AQACAAMABAA="}
```

Response:
```json
{"frame_id":1,"metric_rows_written":8}
```

### `POST /api/sessions/<session_id>/end/`
Body:
```json
{"ended_at_us":1700000000100000,"risk_label":"low","risk_score":18.5}
```

### `GET /api/sessions/<session_id>/`
Returns session metadata plus:
- `raw_frame_count`
- `computed_metric_count`

### `GET /api/sessions/<session_id>/metrics/?metric_name=cop_x,total_load&ts_from=...&ts_to=...&limit=...`
Response shape:
```json
{
  "session_id":1,
  "count":16,
  "metric_names":["cop_x","total_load"],
  "series":{
    "cop_x":[{"ts_us":1700000000000000,"value":0.95,"unit":"grid_x"}],
    "total_load":[{"ts_us":1700000000000000,"value":120.3,"unit":"counts"}]
  }
}
```

### `GET /api/sessions/compare/?session_ids=1,2,3&metric_name=total_load,cop_x`
Returns per-session summary metrics plus deltas from the first session.

Response shape:
```json
{
  "session_ids":[1,2,3],
  "patient_id":1,
  "metric_filter":["total_load","cop_x"],
  "comparison":[
    {
      "session_id":1,
      "patient_id":1,
      "device_id":1,
      "started_at_us":1700000000000000,
      "ended_at_us":1700000000100000,
      "raw_frame_count":24,
      "computed_metric_count":192,
      "metrics":{
        "total_load":{"sample_count":24,"avg":120.1,"min":90.2,"max":146.5,"last":118.8,"unit":"counts"}
      }
    }
  ],
  "delta_from_first":{
    "2":{"total_load":{"avg_delta":8.3}}
  }
}
```

## Device Pairing + Firmware

### `POST /api/devices/pair/`
Body:
```json
{"device_id":1,"connection_status":"connected","connection_quality":"excellent"}
```
Pairs an existing device (or create by `serial_number` if `device_id` omitted) and stores pairing metadata.

### `GET /api/devices/<device_id>/status/`
Returns pairing state, connection state, and current firmware update state.

### `POST /api/devices/<device_id>/firmware/update/`
Body:
```json
{"target_version":"2.1.0","duration_sec":10}
```
Starts a prototype firmware update job (tracked in device metadata).

### `GET /api/devices/<device_id>/firmware/`
Returns firmware update status (`idle|in_progress|completed`) and progress.

## Calibration Run Workflow

### `POST /api/calibration/run/`
Body:
```json
{"device_id":1,"profile_name":"clinic-default","version":"v2","parameters":{"gain":1.4},"duration_sec":8}
```
Starts a prototype calibration job for a device.

### `GET /api/calibration/run/<device_id>/`
Returns calibration job progress/state.  
When completed, backend auto-creates an active calibration profile and returns `created_profile_id`.

## Reports

### `POST /api/reports/generate/`
Body:
```json
{"session_id":1,"report_type":"clinical_summary","clinician_notes":"Patient stable."}
```
Generates report payload and PDF on disk.

### `GET /api/reports/?session_id=...&patient_id=...&report_type=...`
### `GET /api/reports/<report_id>/`
### `GET /api/reports/<report_id>/download/`
Returns PDF binary (`application/pdf`).

## FHIR (Mock Adapter)

### `POST /api/fhir/export/session/<session_id>/`
Builds and persists latest FHIR-like bundle (`report_type="fhir_export"`).

### `GET /api/fhir/export/session/<session_id>/`
Returns latest persisted bundle for that session.

Bundle includes:
- `Patient` (if linked)
- `Device` (if linked)
- `Encounter`
- `Observation` resources for computed metrics

## Demo Bootstrap

Management command:
```bash
python manage.py bootstrap_demo_data
```

Startup toggle in env:
```env
DJANGO_DEMO_BOOTSTRAP=1
```
When enabled, startup runs demo seeding after migrations and superuser bootstrap.
