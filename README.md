# InsolePro Capstone Project

Production-style prototype for clinical balance assessment using smart insoles.  
This repository contains:
- Django backend APIs and server-rendered clinical UI (`wbs/`)
- Containerized dev stack (`Dockerfile`, `docker-compose.yml`)
- Legacy Python modules kept for reference (`legacy/`)
- Product and engineering documentation (`docs/`)

## What this project does
- Session-based clinical web app (`/app/*`) with login/authentication.
- Ingests pressure frames and computes balance metrics.
- Supports patient, device, calibration, and annotation workflows.
- Generates polished report PDFs (single-session and weekly rollup).
- Provides mock FHIR export for EMR integration testing.
- Includes clinician-specific sensor layout preference persistence.

## Repository layout
- `wbs/`: Django project + app code
- `wbs/wbs/static/wbs/`: page scripts/styles
- `wbs/wbs/templates/wbs/pages/`: UI templates
- `wbs/wbs/tests/`: pytest test suite
- `scripts/`: startup and utility scripts
- `docs/`: full engineering handbook (authoritative docs)
- `legacy/`: historical implementation reference

## Prerequisites
- Python 3.12+
- Docker + docker-compose (or Docker Compose v2)
- PostgreSQL client tools (optional, for manual DB ops)

## Quick start (Docker, recommended)

### 1. Configure environment
```bash
cp .env.example .env.docker
```
Review and update at least:
- `DJANGO_SECRET_KEY`
- `DJANGO_SUPERUSER_USERNAME`
- `DJANGO_SUPERUSER_PASSWORD`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`

### 2. Start stack
If you have legacy compose:
```bash
docker-compose up --build
```
If you have compose v2:
```bash
docker compose up --build
```

### 3. Open app
- UI: `http://localhost:8000/`
- Login page: `http://localhost:8000/app/login/`

### 4. Sign in
Use the superuser from env (`DJANGO_SUPERUSER_*`).  
On first startup, `bootstrap_superuser` creates one only if no superuser exists.

## Optional demo data
To auto-seed on startup:
- Set `DJANGO_DEMO_BOOTSTRAP=1` in `.env.docker`
- Restart web container

Or seed manually:
```bash
# docker-compose
docker-compose exec web python /app/wbs/manage.py bootstrap_demo_data

# compose v2
docker compose exec web python /app/wbs/manage.py bootstrap_demo_data
```

## Local development (without Docker)

### 1. Create and activate venv
```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure env
Set env vars (or export from shell):
- For SQLite local dev: leave `USE_POSTGRES` unset/false.
- For Postgres: set `USE_POSTGRES=1` and `POSTGRES_*` vars.

### 4. Run migrations
```bash
python wbs/manage.py migrate --noinput
```

### 5. Create superuser (choose one)
```bash
# interactive
python wbs/manage.py createsuperuser

# or env-based bootstrap
DJANGO_SUPERUSER_USERNAME=admin DJANGO_SUPERUSER_PASSWORD=admin1234 python wbs/manage.py bootstrap_superuser
```

### 6. Run server
```bash
python wbs/manage.py runserver 0.0.0.0:8000
```

## Run tests
```bash
pytest -q
```

Useful targeted runs:
```bash
pytest wbs/wbs/tests/test_auth.py -q
pytest wbs/wbs/tests/test_sessions_api.py -q
pytest wbs/wbs/tests/test_reports_api.py -q
```

## Docs and quality checks
- Full handbook: `docs/README.md`
- Docs quality check:
```bash
python scripts/check_docs.py
```

## Core routes

### UI routes
- `/` -> login or dashboard redirect
- `/app/dashboard/`
- `/app/patients/`
- `/app/devices/`
- `/app/sessions/live/`
- `/app/sessions/compare/`
- `/app/reports/`

### API namespaces
- `/api/auth/*`
- `/api/overview/`
- `/api/patients/*`
- `/api/devices/*`
- `/api/calibration-profiles/*`
- `/api/calibration/run/*`
- `/api/annotations/*`
- `/api/sessions/*`
- `/api/reports/*`
- `/api/fhir/*`
- `/api/ui-preferences/`

For complete contract details, use:
- `docs/api/api_reference.md` (authoritative)
- `docs/api_contract.md` (quick summary)

## Key management commands
```bash
python wbs/manage.py bootstrap_superuser
python wbs/manage.py bootstrap_demo_data
python wbs/manage.py backfill_unassigned_sessions --dry-run
python wbs/manage.py backfill_unassigned_sessions --patient-external-id DEMO-P-001
```

## Troubleshooting

### 1. `Saved locally. Server profile save failed`
Cause: backend migration for UI preferences missing in running container.  
Fix:
```bash
# docker-compose
docker-compose exec -T web python /app/wbs/manage.py migrate --noinput

# compose v2
docker compose exec web python /app/wbs/manage.py migrate --noinput
```

### 2. Docker build fails with DNS/TLS timeout (`deb.debian.org`, `registry-1.docker.io`)
Cause: host network/DNS instability.  
Fix:
- Retry on stable network.
- Ensure Docker daemon can resolve DNS through host network.
- Keep using host network configuration already defined in compose build.

### 3. `no such table` errors
Cause: migrations not applied in selected environment (SQLite or Postgres).  
Fix:
```bash
python wbs/manage.py migrate --noinput
```

### 4. Login fails unexpectedly
- Verify CSRF route responds: `GET /api/auth/csrf/`
- Verify credentials match existing user.
- Confirm session cookies are not blocked.

### 5. Empty dashboard/report data
- Run demo seed command (`bootstrap_demo_data`) or create patient/session data manually.

## Security and production notes
This repo is a production-style prototype, not a finalized regulated deployment.  
Before production use, complete hardening and compliance steps in:
- `docs/security/security_and_hipaa_posture.md`
- `docs/operations/environment_and_deployment.md`

## Contribution expectations
When changing behavior:
1. Update tests in `wbs/wbs/tests/`.
2. Update relevant docs under `docs/`.
3. Add a line in `docs/CHANGELOG_DOCS.md`.
4. Run:
```bash
python wbs/manage.py check
pytest -q
python scripts/check_docs.py
```
