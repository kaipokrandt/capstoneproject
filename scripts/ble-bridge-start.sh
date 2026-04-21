#!/usr/bin/env bash
# ble-bridge-start.sh
#
# Runs on the HOST Mac (not inside Docker).
# Waits for the Django web service to be healthy, then connects to the
# STEPPA BLE device and forwards frames to the API indefinitely.
# On disconnect it retries automatically — ideal for expo demos.
#
# Called by expo-start.sh. Can also be run standalone:
#   ./scripts/ble-bridge-start.sh
#
# Environment variables (all have defaults from .env or fallbacks):
#   BLE_BASE_URL    — Django API base URL  (default: http://127.0.0.1:8000)
#   BLE_USERNAME    — API login username   (default: admin)
#   BLE_PASSWORD    — API login password   (default: admin)
#   BLE_PATIENT_ID  — patient PK to use    (default: 1)
#   BLE_DEVICE_ID   — device PK to use     (default: 1)
#   BLE_DEVICE_NAME — BLE advertised name  (default: STEPPA)
#   VENV_PATH       — path to .venv        (default: <repo-root>/.venv)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ---------------------------------------------------------------------------
# Load .env if present so callers don't have to export every var manually
# ---------------------------------------------------------------------------
if [ -f "${REPO_ROOT}/.env" ]; then
  set -o allexport
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +o allexport
fi

BLE_BASE_URL="${BLE_BASE_URL:-http://127.0.0.1:8000}"
BLE_USERNAME="${BLE_USERNAME:-admin}"
BLE_PASSWORD="${BLE_PASSWORD:-admin}"
BLE_PATIENT_ID="${BLE_PATIENT_ID:-1}"
BLE_DEVICE_ID="${BLE_DEVICE_ID:-1}"
BLE_DEVICE_NAME="${BLE_DEVICE_NAME:-STEPPA}"
VENV_PATH="${VENV_PATH:-${REPO_ROOT}/.venv}"
PYTHON="${VENV_PATH}/bin/python3"
BRIDGE_SCRIPT="${REPO_ROOT}/scripts/bridge_ble_to_api.py"
HEALTH_URL="${BLE_BASE_URL}/api/health/"
RETRY_DELAY=5

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "[ble-bridge] $(date '+%H:%M:%S') $*"; }

wait_for_web() {
  log "Waiting for Django web service at ${HEALTH_URL} ..."
  until "$PYTHON" - "$HEALTH_URL" <<'PY' 2>/dev/null
import sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=3) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
  do
    log "  Web not ready yet — retrying in ${RETRY_DELAY}s ..."
    sleep "$RETRY_DELAY"
  done
  log "Web service is healthy."
}

check_venv() {
  if [ ! -x "$PYTHON" ]; then
    echo "[ble-bridge] ERROR: Python venv not found at ${VENV_PATH}" >&2
    echo "[ble-bridge]        Create it with: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
  fi
}

ensure_docker() {
  if ! docker info >/dev/null 2>&1; then
    log "ERROR: Docker is not running. Start Docker Desktop first." >&2
    exit 1
  fi
  # If no containers from this project are up, start them
  RUNNING=$(docker compose -f "${REPO_ROOT}/docker-compose.yml" ps --services --filter status=running 2>/dev/null | wc -l | tr -d ' ')
  if [ "$RUNNING" -eq 0 ]; then
    log "Docker services not running — starting them now..."
    docker compose -f "${REPO_ROOT}/docker-compose.yml" up -d --build
    log "Docker services started."
  else
    log "Docker services already running."
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
check_venv
ensure_docker
wait_for_web

log "Starting BLE bridge (device=${BLE_DEVICE_NAME}, patient=${BLE_PATIENT_ID}, device_id=${BLE_DEVICE_ID})"
log "API target: ${BLE_BASE_URL}"
log "Press Ctrl+C to stop."
echo ""

ATTEMPT=0
while true; do
  ATTEMPT=$((ATTEMPT + 1))
  log "Connection attempt #${ATTEMPT} ..."

  set +e
  "$PYTHON" "$BRIDGE_SCRIPT" \
    --base-url   "$BLE_BASE_URL" \
    --username   "$BLE_USERNAME" \
    --password   "$BLE_PASSWORD" \
    --patient-id "$BLE_PATIENT_ID" \
    --device-id  "$BLE_DEVICE_ID" \
    --device-name "$BLE_DEVICE_NAME" \
    --notes "Expo live BLE ingest"
  EXIT_CODE=$?
  set -e

  if [ "$EXIT_CODE" -eq 130 ]; then
    # Ctrl+C — user intentionally stopped
    log "Stopped by user."
    break
  fi

  log "Bridge exited (code ${EXIT_CODE}). Retrying in ${RETRY_DELAY}s ..."
  sleep "$RETRY_DELAY"
done
