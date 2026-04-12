# Backend Handbook

Last Verified: 2026-04-11  
Owner: Backend Engineering  
Code References: `wbs/wbs/sessions_views.py`, `wbs/wbs/reports_views.py`, `wbs/wbs/master_views.py`  
Test References: `wbs/wbs/tests/test_sessions_api.py`, `wbs/wbs/tests/test_reports_api.py`, `wbs/wbs/tests/test_master_api.py`

## Domain Features
- Session lifecycle: start, ingest frame, compute metrics, end, detail, list, compare.
- Clinical entities: patients, devices, calibration profiles, annotations.
- Reports: single-session and weekly rollup report generation.
- Integrations: FHIR-like export per session.
- Device operations: pair, status, firmware update simulation, calibration run simulation.
- Clinician personalization: per-user sensor layout persistence (`ui-preferences`).

## Metric Computation Semantics
- Ingestion accepts base64 ADC payload of exact `gw*gh*2` bytes.
- Every frame ingest triggers full session recompute (`recompute_session_metrics`).
- Metrics produced per frame:
- `cop_x`, `cop_y`, `cop_v`, `sway_path`, `total_load`
- `stance_pct`, `swing_pct`, `asymmetry_index`
- `cadence_spm` when step transitions detected.

## Report Semantics
- Single scope (`scope=single` or omitted): anchored to explicit `session_id`.
- Weekly scope (`scope=weekly`): requires `patient_id` + Monday `week_start` and aggregates all sessions in Mon-Sun window.
- Weekly report is persisted against anchor session (latest session in window).
- Report types:
- Single: `clinical_summary`, `fall_risk_summary`, `fhir_export`
- Weekly: `weekly_clinical_summary`, `weekly_fall_risk_summary`

## Failure and Validation Behavior
- All API namespaces require authentication except CSRF bootstrap/login/register routes.
- Validation returns `400` with `detail` text.
- Missing entities return `404`.
- Duplicate constraints return `409`.
- Session compare requires 2+ unique session ids.
- Weekly generation rejects non-Monday `week_start`.

## Management Commands
- `bootstrap_superuser`: creates superuser from env vars when none exists.
- `bootstrap_demo_data`: seeds deterministic demo entities, sessions, metrics, reports, and weekly examples.
- `backfill_unassigned_sessions`: maps sessions without patient links and patches report payload patient references.

## Backend Smoke Commands
```bash
python wbs/manage.py check
python wbs/manage.py migrate --noinput
python wbs/manage.py bootstrap_superuser
python wbs/manage.py bootstrap_demo_data
pytest -q
```
