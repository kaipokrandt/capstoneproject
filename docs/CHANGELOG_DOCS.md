# Documentation Changelog

Last Verified: 2026-04-21  
Owner: Platform Engineering  
Code References: `wbs/wbs/`  
Test References: `wbs/wbs/tests/`

## 2026-04-21 (Session 2 — BLE Integration + Expo Startup)

### Expo Startup
- Added `expo-start.sh` as the single-command expo entrypoint: starts Docker services then launches the BLE bridge on the host Mac.
- Added `scripts/ble-bridge-start.sh`: polls `GET /api/health/` until Django is healthy, auto-starts Docker if not running, then launches `bridge_ble_to_api.py` with auto-retry on disconnect.
- Added `GET /api/health/` unauthenticated liveness endpoint (`system_views.health`).
- Updated `scripts/web-entrypoint.sh` to print BLE bridge instructions on container start.
- Updated `docker-compose.yml` with expo startup documentation in header comment.
- Added BLE env vars to `.env`: `BLE_USERNAME`, `BLE_PASSWORD`, `BLE_PATIENT_ID`, `BLE_DEVICE_ID`, `BLE_DEVICE_NAME`, `BLE_BASE_URL`.
- Fixed `bootstrap_superuser` command to always sync password from env (`set_password`) using `get_or_create` — prevents stale Postgres volume from causing login failures.

### BLE Bridge — Heartbeat Logging
- `bridge_ble_to_api.py`: added 5-second heartbeat annotation (`author=ble-bridge`, `source=ble-bridge-heartbeat`) with `frames_in_window`, `total_frames`, `last_ax/ay/az`, `last_total_load` in metadata.
- Added `?author=` filter to `GET /api/annotations/` endpoint.

### Live Session UI — BLE Stream Log
- Added **BLE Data Stream** log box to `sessions_live.html`: scrolling monospace display of BLE heartbeat annotations.
- `page_live.js`: polls `GET /api/annotations/?author=ble-bridge` every 5s; snapshots `bleLastAnnotationId` on session start so only new entries appear; shows green **Live · HH:MM:SS** status badge.

### IMU Calibration
- Added `POST /api/devices/<id>/calibrate-imu/` endpoint: reads latest `ble-bridge` heartbeat annotation for the device, stores `ax/ay/az` as `imu_offset` in `Device.metadata`.
- `bridge_ble_to_api.py`: polls `GET /api/devices/<id>/` every 2s for updated `imu_offset` and subtracts it from every frame (software zero-offset).
- Added **Calibrate** button and status label to `sessions_live.html` above the action buttons.
- `page_live.js`: blocks **Start Assessment** if `imuCalibrated` flag is not set; calls `POST /api/devices/<id>/calibrate-imu/` on click.

### Metrics Pipeline Bug Fix
- `metrics_pipeline.py`: corrected `contact_thresh` from `5.0e5` (unreachable) to `5.0e4`. Real board `total_load` after the 12-bit ADC→pressure transform peaks at ~36,000–40,000 counts. Previous threshold prevented `in_contact` from ever being `True`, so `cadence_spm` was never emitted.
- All 9 metrics now compute correctly from live data: `cop_x`, `cop_y`, `cop_v`, `sway_path`, `total_load`, `stance_pct`, `swing_pct`, `asymmetry_index`, `cadence_spm`.

### Observed Live Metric Ranges (STEPPA board, single insole, flat surface)
| Metric | Observed range | Unit |
|---|---|---|
| `cop_x` | 0.82–0.83 | grid_x |
| `cop_y` | 0.11–0.12 | grid_y |
| `cop_v` | 0.001–0.005 | grid_per_s |
| `total_load` | 36,000–37,000 | counts |
| `asymmetry_index` | ~-0.98 | ratio (right-biased, single insole) |
| `cadence_spm` | 52–69 | steps_per_min |

## 2026-04-21 (Session 1)
- Added `docs/firmware/ble_packet_structure.md`: full STEPPA BLE packet structure, field definitions, grid mapping, observed value ranges, validation rules, and known async ORM bug.

## 2026-04-11
- Added production-grade handbook structure and canonical docs index.
- Added architecture, backend, frontend, API, data model, integrations, operations, security, QA, and developer workflow docs.
- Added docs quality checks (`scripts/check_docs.py`) and CI workflow (`.github/workflows/docs-quality.yml`).
- Added PRD drift sections to backend and frontend PRDs.
- Expanded API docs to include weekly report scope and clinician UI preferences endpoint.
