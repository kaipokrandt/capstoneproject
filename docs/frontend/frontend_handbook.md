# Frontend Handbook

Last Verified: 2026-04-11  
Owner: Frontend Engineering  
Code References: `wbs/wbs/templates/wbs/pages/`, `wbs/wbs/static/wbs/page_*.js`, `wbs/wbs/static/wbs/ui_core.js`  
Test References: `wbs/wbs/tests/test_ui_shell.py`, `wbs/wbs/tests/test_overview_api.py`

## Page Inventory
- Login: `/app/login/` (`page_login.js`).
- Dashboard: `/app/dashboard/` (`page_dashboard.js`).
- Patients: `/app/patients/` (`page_patients.js`).
- Devices: `/app/devices/` (`page_devices.js`).
- Live Session: `/app/sessions/live/` (`page_live.js`).
- Compare: `/app/sessions/compare/` (`page_compare.js`).
- Reports: `/app/reports/` (`page_reports.js`).

## Shared Runtime Contract
- `ui_core.js` obtains CSRF token and user session (`/api/auth/csrf/`, `/api/auth/me/`).
- All non-GET API calls include `X-CSRFToken` and session cookie.
- Unauthenticated page usage redirects to login with `next` param.

## Critical UI State Machines
1. Live session:
- Idle -> Running -> Ended or Interrupted.
- Polls frame ingest and metric retrieval every second.
- Stale quality uses sync-age and telemetry thresholds.
- Fall simulation (`Shift+F`) triggers forced interruption, modal/banner, and annotation write.

2. Reports modal:
- Closed -> Loading -> Summary tab/PDF tab -> Close.
- Footer actions: download PDF, sync to EMR, close.
- Supports weekly and single reports with distinct interpretation text.

3. Sensor calibration UX:
- Edit mode toggle (`Shift+S`) available while idle or running.
- Drag-and-save overlays on split sole SVGs.
- Save writes both local storage and `/api/ui-preferences/` profile endpoint.

## Frontend-to-Backend Endpoint Map
- Dashboard: `/api/overview/`, `/api/patients/`, `/api/devices/`, `/api/reports/`, `/api/devices/<id>/status/`.
- Patients: `/api/patients/`, `/api/reports/`, `/api/annotations/`, `/api/sessions/<id>/metrics/`.
- Devices: `/api/devices/`, `/api/calibration-profiles/`, `/api/devices/pair/`, `/api/devices/<id>/firmware/update/`, `/api/calibration/run/`.
- Live: `/api/sessions/start/`, `/api/sessions/<id>/frames/`, `/api/sessions/<id>/metrics/`, `/api/sessions/<id>/end/`, `/api/annotations/`, `/api/ui-preferences/`.
- Compare: `/api/patients/`, `/api/sessions/`, `/api/sessions/compare/`.
- Reports: `/api/patients/`, `/api/sessions/`, `/api/reports/`, `/api/reports/generate/`, `/api/reports/<id>/download/`, `/api/fhir/export/session/<id>/`.

## Design System Notes
- InsolePro branding is centralized in template/style tokens and `ui_scheme.css`.
- Clinical-first hierarchy: primary CTA visibility, clear status language, low cognitive load.
- Modal, card, KPI, and warning patterns are reusable primitives.
