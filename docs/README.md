# InsolePro Engineering Handbook

Last Verified: 2026-04-11  
Owner: Platform Engineering  
Code References: `wbs/wbs/urls.py`, `wbs/wbs/models.py`, `wbs/wbs/static/wbs/`  
Test References: `wbs/wbs/tests/`

This handbook is the canonical source of truth for implementation and operations.

## Source of Truth Policy
- Product intent lives in PRDs: [Backend PRD](./backend_prd.md), [Frontend PRD](./frontend_prd.md).
- Implemented behavior lives in subsystem handbooks below.
- If PRD and implementation differ, implementation docs are authoritative and PRDs must be updated with a drift note.

## Documentation Taxonomy
- Product: PRDs and implemented scope notes.
- Architecture: system topology, request/data flow, module boundaries.
- Backend: domain behavior, business rules, command workflows.
- Frontend: page behavior, UI states, and API bindings.
- API: endpoint-by-endpoint contract and failure model.
- Data Model: persisted schema and relationships.
- Integrations: report/PDF/FHIR mapping and export behaviors.
- Operations: deploy/runbook/incident/backup/observability.
- Security: auth/session/CSRF/PHI boundaries and compliance gap register.
- QA: test strategy, traceability matrix, acceptance drills.
- Developer Workflow: contribution rules and docs Definition of Done.

## Handbook Index
- [System Architecture](./architecture/system_architecture.md)
- [Backend Handbook](./backend/backend_handbook.md)
- [Frontend Handbook](./frontend/frontend_handbook.md)
- [API Reference](./api/api_reference.md)
- [Data Model Reference](./data/data_model_reference.md)
- [FHIR + Reports Integration](./integrations/fhir_and_reports.md)
- [Environment + Deployment Runbook](./operations/environment_and_deployment.md)
- [Incident Response Runbook](./operations/incident_response.md)
- [Backup, Restore, Observability](./operations/backup_restore_observability.md)
- [Security + HIPAA-Ready Posture](./security/security_and_hipaa_posture.md)
- [QA Strategy + Traceability](./qa/test_strategy_and_traceability.md)
- [Developer Workflow + Docs DoD](./developer/developer_workflow.md)
- [Docs Changelog](./CHANGELOG_DOCS.md)

## Last Verified Metadata Policy
Each top-level `docs/*.md` file must include:
- `Last Verified` (ISO date)
- `Owner` (team/role)
- `Code References` (key module paths)
- `Test References` (key test paths)

Any feature PR that changes runtime behavior must update at least one handbook page and `docs/CHANGELOG_DOCS.md`.
