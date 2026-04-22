# Environment and Deployment Runbook

Last Verified: 2026-04-21  
Owner: Platform Operations  
Code References: `docker-compose.yml`, `Dockerfile`, `scripts/web-entrypoint.sh`, `scripts/ble-bridge-start.sh`, `expo-start.sh`, `.env.example`  
Test References: `wbs/wbs/tests/test_ui_shell.py`

## Environment Matrix
- Local dev (SQLite): direct `python manage.py runserver`.
- Docker dev/prototype (Postgres): `docker-compose up --build` with `.env`.
- **Expo / demo (recommended):** `./expo-start.sh` — starts Docker + BLE bridge in one command.
- Runtime toggle: `USE_POSTGRES=1` to activate Postgres in Django settings.

## Expo Startup (Single Command)

> **For the capstone expo, this is the only command needed:**
> ```bash
> ./expo-start.sh
> ```

What it does:
1. Runs `docker compose up -d --build` (web on `:8000`, db on `:5432`).
2. Waits for `GET /api/health/` to return `200`.
3. Launches `scripts/ble-bridge-start.sh` in the foreground.
4. The BLE bridge logs in to the Django API, scans for the `STEPPA` device, and streams frames indefinitely with auto-retry on disconnect.

**Prerequisites:**
- Docker Desktop running.
- `.venv` created: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- `.env` configured (defaults work for a fresh stack).

**To stop:** `Ctrl+C` stops the bridge. Then `docker compose down` to stop Docker.

> **macOS note:** Bluetooth cannot pass through Docker Desktop. The BLE bridge **must** run on the host Mac — `expo-start.sh` handles this automatically.

## BLE Bridge Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `BLE_BASE_URL` | `http://127.0.0.1:8000` | Django API base URL (host-side) |
| `BLE_USERNAME` | `admin` | Django login for bridge auth |
| `BLE_PASSWORD` | `admin` | Django login for bridge auth |
| `BLE_PATIENT_ID` | `1` | Patient PK to attach BLE sessions to |
| `BLE_DEVICE_ID` | `1` | Device PK to attach BLE sessions to |
| `BLE_DEVICE_NAME` | `STEPPA` | BLE advertised name to scan for |

## Startup Lifecycle (Docker container)
1. Wait for Postgres.
2. Run migrations.
3. Bootstrap superuser — **always syncs password from env** (`get_or_create` + `set_password`). Safe to run on every start; will not create duplicates.
4. Optionally bootstrap demo data via `DJANGO_DEMO_BOOTSTRAP=1`.
5. Start Django server.

## IMU Calibration (before each assessment)
1. Power on the STEPPA board and ensure the BLE bridge is streaming (BLE Data Stream log shows data).
2. Place the board flat on a stable surface.
3. In the Live Session UI, select the device and click **Calibrate**.
4. The current `ax/ay/az` values are stored as `imu_offset` in `Device.metadata`.
5. The bridge picks up the offset within 2s and subtracts it from all subsequent frames.
6. **Start Assessment is blocked until calibration is completed.**

## Required Environment Variables
- Django: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`.
- DB: `USE_POSTGRES`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.
- Superuser bootstrap: `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL`.
- Demo bootstrap: `DJANGO_DEMO_BOOTSTRAP`.
- BLE bridge: `BLE_BASE_URL`, `BLE_USERNAME`, `BLE_PASSWORD`, `BLE_PATIENT_ID`, `BLE_DEVICE_ID`, `BLE_DEVICE_NAME`.

## Release Checklist
1. Pull code and install dependencies.
2. Apply migrations (`python wbs/manage.py migrate --noinput`).
3. Run smoke checks:
   - `python wbs/manage.py check`
   - `pytest -q`
4. Validate auth + dashboard + live + reports + compare routes.
5. Validate report generation/download and FHIR export in environment.
6. Run `./expo-start.sh` and confirm BLE bridge connects and heartbeat annotations appear in the Live Session BLE Data Stream log.

## Rollback Guidance
- If deploy fails before migrations: roll back image/app code.
- If migration applied and app fails: restore DB snapshot and redeploy previous version.
- Keep generated reports directory backup aligned with DB snapshot timestamp.
