# FHIR + Report Integration

Last Verified: 2026-04-11  
Owner: Integrations Engineering  
Code References: `wbs/wbs/fhir_views.py`, `wbs/wbs/reports_views.py`  
Test References: `wbs/wbs/tests/test_fhir_api.py`, `wbs/wbs/tests/test_reports_api.py`

## Report Pipeline
- Report creation stores JSON payload in DB.
- PDF generation is performed by `_write_report_pdf`.
- Download endpoint always refreshes PDF from current payload to ensure parity with preview content.

## Report Types and Interpretation Modes
- `clinical_summary`: clinical interpretation framing.
- `fall_risk_summary`: fall-risk framing from same metric corpus.
- `weekly_clinical_summary`: week-aggregated clinical framing.
- `weekly_fall_risk_summary`: week-aggregated fall-risk framing.
- `fhir_export`: persisted FHIR-like bundle payload.

## Weekly Rollup Behavior
- Window: calendar Mon-Sun using clinic timezone.
- Validation: `week_start` must be Monday.
- Storage strategy: write report against anchor session (latest in week).
- Aggregate metadata resides in `payload.aggregate`.

## FHIR Export Behavior
- Endpoint: `/api/fhir/export/session/<id>/`.
- POST creates a report row with bundle payload.
- GET returns latest bundle for that session.
- Bundle includes Patient, Device, Encounter, Observation resources when source links exist.

## Integration Failure Modes
- Missing session: `404`.
- No previous export on GET: `404`.
- Unauthenticated access: `401`.
