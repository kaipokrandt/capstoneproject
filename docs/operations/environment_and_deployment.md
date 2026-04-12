# Environment and Deployment Runbook

Last Verified: 2026-04-11  
Owner: Platform Operations  
Code References: `docker-compose.yml`, `Dockerfile`, `scripts/web-entrypoint.sh`, `.env.example`  
Test References: `wbs/wbs/tests/test_ui_shell.py`

## Environment Matrix
- Local dev (SQLite): direct `python manage.py runserver`.
- Docker dev/prototype (Postgres): `docker-compose up --build` with `.env.docker`.
- Runtime toggle: `USE_POSTGRES=1` to activate Postgres in Django settings.

## Startup Lifecycle
- Wait for Postgres.
- Run migrations.
- Bootstrap superuser from env if missing.
- Optionally bootstrap demo data via `DJANGO_DEMO_BOOTSTRAP=1`.
- Start Django server.

## Required Environment Variables
- Django: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`.
- DB: `USE_POSTGRES`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.
- Superuser bootstrap: `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, optional email.
- Demo bootstrap: `DJANGO_DEMO_BOOTSTRAP`.

## Release Checklist
1. Pull code and install dependencies.
2. Apply migrations (`python wbs/manage.py migrate --noinput`).
3. Run smoke checks:
- `python wbs/manage.py check`
- `pytest -q`
4. Validate auth + dashboard + live + reports + compare routes.
5. Validate report generation/download and FHIR export in environment.

## Rollback Guidance
- If deploy fails before migrations: roll back image/app code.
- If migration applied and app fails: restore DB snapshot and redeploy previous version.
- Keep generated reports directory backup aligned with DB snapshot timestamp.
