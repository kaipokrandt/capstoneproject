# Security and HIPAA-Ready Posture

Last Verified: 2026-04-11  
Owner: Security Engineering  
Code References: `wbs/wbs/auth_views.py`, `wbs/wbs/settings.py`, `wbs/wbs/models.py`  
Test References: `wbs/wbs/tests/test_auth.py`

## Security Model (Current)
- Session-based auth with Django auth middleware.
- CSRF token required for mutating requests.
- Route-level auth checks on API handlers (`_require_auth`).
- UI routes redirect unauthenticated users to login.

## Data Classification and PHI Boundaries
- Potential PHI: patient identifiers, demographics, annotations, session/report data.
- Stored locations:
- DB tables (`patients`, `sessions`, `annotations`, `reports`, metrics tables)
- report PDF files in `generated_reports/`
- user session data in Django session backend
- Local browser storage includes selected patient id and sensor layout calibration.

## Access Control Expectations
- Least privilege at infra level for DB and file paths.
- Use distinct service credentials per environment.
- Disable debug and lock allowed hosts/trusted origins in production.

## Auditability Expectations
- Session and report lifecycle stored in DB.
- Annotation metadata captures safety events for live simulated fall path.
- Export actions traceable via `fhir_export` report entries.

## Hardening Checklist
- Set strong `DJANGO_SECRET_KEY`.
- Set `DJANGO_DEBUG=0`.
- Restrict `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Enforce HTTPS termination and secure cookies in production config.
- Rotate DB credentials and secret material.
- Restrict filesystem permissions for `generated_reports/`.
- Enable centralized logs and access audit trail.

## HIPAA Gap Register (Prototype -> Production)
- No formal RBAC model beyond authenticated users.
- No explicit encryption-at-rest policy documented in app layer.
- No formal audit log pipeline or immutable retention guarantees.
- No signed BAA/compliance control mapping in repo.
- No automated vulnerability/dependency scanning workflow yet.

These gaps must be closed before regulated deployment.
