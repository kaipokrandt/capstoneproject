# System Architecture

Last Verified: 2026-04-11  
Owner: Platform Engineering  
Code References: `wbs/wbs/urls.py`, `wbs/wbs/ui_views.py`, `wbs/wbs/*_views.py`  
Test References: `wbs/wbs/tests/test_ui_shell.py`, `wbs/wbs/tests/test_*_api.py`

## Runtime Topology
- Django monolith serves both server-rendered UI pages and JSON APIs.
- Frontend uses plain HTML templates + page-specific JS modules under `wbs/wbs/static/wbs/`.
- Database is SQLite by default, PostgreSQL when `USE_POSTGRES=1`.
- Docker startup executes migrations, superuser bootstrap, optional demo bootstrap.

## URL Surface
- UI routes: `/`, `/app/*`.
- API routes:
- `/api/auth/*`
- `/api/overview/`
- `/api/sessions/*`
- `/api/reports/*`
- `/api/fhir/*`
- `/api/*` for patients/devices/calibration/annotations/ui-preferences.

## End-to-End Flows
1. Live assessment flow:
- UI (`page_live.js`) starts session via `/api/sessions/start/`.
- Frame polling simulator posts to `/api/sessions/<id>/frames/`.
- Backend recomputes computed metrics per ingest.
- UI polls `/api/sessions/<id>/metrics/` for charts.
- Session ends through `/api/sessions/<id>/end/`.

2. Reporting flow:
- UI (`page_reports.js`) generates report via `/api/reports/generate/`.
- Backend writes report payload and polished PDF.
- UI opens floating modal and consumes `/api/reports/<id>/` and `/api/reports/<id>/download/`.
- Optional EMR sync uses `/api/fhir/export/session/<session_id>/`.

3. Device flow:
- Pairing and status under `/api/devices/*`.
- Firmware update simulation tracked in device metadata.
- Calibration run simulation tracked in metadata and materialized to calibration profiles.

## Module Boundaries
- `auth_views.py`: session-based auth and CSRF bootstrap.
- `sessions_views.py`: session lifecycle, ingestion, metrics, compare.
- `reports_views.py`: report generation/list/detail/download, weekly rollups.
- `master_views.py`: CRUD entities + operational device/calibration endpoints + UI preferences.
- `fhir_views.py`: mock FHIR bundle export/readback.
- `metrics_pipeline.py`: signal-to-metric transformation.

## Artifacts Produced
- Raw frames in DB (`raw_frames`).
- Computed metrics in DB (`computed_metrics`).
- Reports in DB (`reports`) plus PDF files under `generated_reports/`.
- FHIR-like bundles stored in report payload (`report_type=fhir_export`).
