# Incident Response Runbook

Last Verified: 2026-04-11  
Owner: Platform Operations  
Code References: `wbs/wbs/*_views.py`, `wbs/wbs/static/wbs/page_*.js`  
Test References: `wbs/wbs/tests/test_*_api.py`

## Severity Model
- Sev1: complete outage or unsafe clinical workflow interruption.
- Sev2: core flow degraded (session ingest, report generation, login).
- Sev3: non-critical defects or degraded UX with workaround.

## Triage Decision Tree
1. Confirm blast radius:
- all users vs single user/session vs single page.
2. Check service health:
- app process, DB reachability, migration state.
3. Check auth/CSRF path:
- `/api/auth/csrf/`, `/api/auth/me/` responses.
4. Check failing subsystem endpoint directly.

## Common Incidents and Actions
- Service down:
- verify container/process status
- inspect startup logs and DB connectivity
- rerun migration and check command

- Migration failure:
- inspect failing migration
- restore pre-migration backup if needed
- redeploy with corrected migration set

- Report generation/download failure:
- verify DB report row exists
- verify write permission to `generated_reports/`
- regenerate with `/api/reports/<id>/download/`

- EMR/FHIR sync issues:
- validate source session exists
- replay POST export endpoint
- inspect last `fhir_export` report payload

- Live session stale/slow:
- inspect frame ingest endpoint latency
- inspect metric recomputation cost
- verify DB performance and session size

## Post-Incident
- capture timeline and root cause.
- add regression test(s).
- update relevant handbook sections and changelog.
