# QA Strategy and Traceability

Last Verified: 2026-04-11  
Owner: QA Engineering  
Code References: `wbs/wbs/urls.py`, `wbs/wbs/models.py`  
Test References: `wbs/wbs/tests/`

## Test Layers
- API integration tests for auth, master endpoints, sessions, reports, FHIR, overview.
- UI shell tests for route auth and page availability.
- Model tests for schema constraints and cascade behavior.

## Traceability Matrix (Feature -> Tests)
| Feature Area | Primary Tests |
|---|---|
| Auth and CSRF | `test_auth.py` |
| Patients/Devices/Calibration/Annotations | `test_master_api.py` |
| Session lifecycle and compare | `test_sessions_api.py` |
| Reports and weekly rollup | `test_reports_api.py` |
| FHIR export | `test_fhir_api.py` |
| Overview endpoint | `test_overview_api.py` |
| UI route protection | `test_ui_shell.py` |
| Model constraints | `test_models.py` |

## Operability Drill (Docs-Only Onboarding)
1. Start stack and migrate.
2. Login with seeded/admin user.
3. Create/select patient/device.
4. Run live assessment start -> ingest -> end.
5. Generate report and open preview modal.
6. Download PDF and trigger EMR sync.
7. Run compare across patient sessions.
8. Run calibration and firmware workflows.
9. Trigger and verify one recovery flow from runbook.

## Acceptance Criteria for Documentation
- Every implemented endpoint documented.
- Every UI page documented with API bindings.
- Every management command documented.
- Every top-level docs file carries verification metadata.
