#!/usr/bin/env bash
# expo-start.sh — Single command to start InsolePro for the expo.
#
# Usage:
#   ./expo-start.sh
#
# What it does:
#   1. Builds and starts Docker services (web + db) in the background
#   2. Waits until the web service passes its health check
#   3. Launches the BLE bridge in this terminal (foreground, auto-retries on disconnect)
#
# Requirements:
#   - Docker Desktop running
#   - .venv created:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
#   - .env configured with BLE_USERNAME, BLE_PASSWORD, BLE_PATIENT_ID, BLE_DEVICE_ID
#     (defaults: admin / admin / 1 / 1)
#
# To stop everything:
#   Ctrl+C — stops the BLE bridge AND runs docker compose down automatically

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RESET='\033[0m'

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║       InsolePro — Expo Startup           ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}"
echo ""

# ---------------------------------------------------------------------------
# 1. Start Docker services
# ---------------------------------------------------------------------------
echo -e "${BOLD}[1/2] Starting Docker services (web + db)...${RESET}"
docker compose up -d --build
echo -e "${GREEN}      Docker services started.${RESET}"
echo ""

# ---------------------------------------------------------------------------
# 2. Launch BLE bridge (blocks — auto-retries on disconnect)
# ---------------------------------------------------------------------------
echo -e "${BOLD}[2/2] Launching BLE bridge on host...${RESET}"
echo -e "      Web UI will be available at ${CYAN}http://localhost:8000${RESET} once healthy."
echo ""

cleanup() {
  echo ""
  echo -e "${BOLD}Stopping BLE bridge...${RESET}"
  # Kill the bridge process group so nested sleep/retry loops also die
  kill -TERM "-${BRIDGE_PID}" 2>/dev/null || kill -TERM "${BRIDGE_PID}" 2>/dev/null || true
  wait "${BRIDGE_PID}" 2>/dev/null || true
  echo -e "${BOLD}Shutting down Docker services...${RESET}"
  docker compose down
  echo -e "${GREEN}Done.${RESET}"
  exit 0
}
trap cleanup INT TERM

# Run bridge in its own process group so kill -TERM -PID reaches all children
set -m
"${REPO_ROOT}/scripts/ble-bridge-start.sh" &
BRIDGE_PID=$!
set +m
wait $BRIDGE_PID
