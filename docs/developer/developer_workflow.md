# Developer Workflow and Docs Definition of Done

Last Verified: 2026-04-11  
Owner: Platform Engineering  
Code References: `scripts/`, `wbs/wbs/tests/`  
Test References: `pytest.ini`, `wbs/wbs/tests/`

## Branch Workflow
- Make behavior changes with tests in same PR.
- Keep API changes synchronized with `docs/api/api_reference.md`.
- Update feature handbook pages for any UI/backend behavior changes.

## Docs Definition of Done (Required in Feature PR)
- Update implementation docs for changed feature area.
- Update API reference if request/response/validation changed.
- Update runbook docs if deploy/ops behavior changed.
- Update security doc if auth/data/PHI surface changed.
- Add changelog line in `docs/CHANGELOG_DOCS.md`.
- Add or update automated tests for changed behavior.

## Command Checklist
```bash
python wbs/manage.py check
pytest -q
python scripts/check_docs.py
```

## Versioning and Change Hygiene
- API contract labels use `prototype-v2` until formal versioning is introduced.
- Breaking changes require migration note + doc changelog + regression test updates.
