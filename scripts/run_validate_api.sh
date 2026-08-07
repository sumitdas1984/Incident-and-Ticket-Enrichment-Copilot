#!/usr/bin/env bash
#
# Spawn the Alarm API simulator in the background, run both Postman
# collections via Newman, and clean up the simulator on exit (any
# reason: success, failure, Ctrl-C).
#
# Invoked by `make validate-api`. Reads:
#   ALARM_API_VALIDATE_PORT  port to bind (default 18000)
#   ALARM_API_TOKEN          bearer token (default demo-token)
#
# Writes:
#   newman-report/<collection>.html   (gitignored)

set -euo pipefail

# The simulator's __main__ binds its container port (8000) directly. We
# use that here; if a developer needs to override, they can stub the
# container port via ALARM_API_PORT (settings.alarm_api_port) AND edit
# __main__.py. For Story 2.2.1 we want the default `make validate-api`
# to work out of the box.
PORT="${ALARM_API_VALIDATE_PORT:-8000}"
BASE_URL="http://localhost:${PORT}"
TOKEN="${ALARM_API_TOKEN:-demo-token}"
LOG_FILE="$(mktemp -t alarm-api-validate.XXXXXX.log)"
SIM_PID=""

cleanup() {
  local rc=$?
  if [ -n "${SIM_PID}" ] && kill -0 "${SIM_PID}" 2>/dev/null; then
    echo "→ stopping simulator (pid=${SIM_PID})"
    kill "${SIM_PID}" 2>/dev/null || true
    # Give it a moment to exit cleanly, then force.
    sleep 0.5
    kill -9 "${SIM_PID}" 2>/dev/null || true
  fi
  if [ "$rc" -ne 0 ]; then
    echo
    echo "✗ validate-api failed. Simulator log:"
    echo "----"
    cat "${LOG_FILE}" || true
    echo "----"
  fi
  rm -f "${LOG_FILE}"
  exit "$rc"
}
trap cleanup EXIT INT TERM

# --- 1. Pick a free port (if the requested one is taken, fail loudly). ---
if (echo > /dev/tcp/127.0.0.1/"${PORT}") 2>/dev/null; then
  echo "✗ port ${PORT} already in use. Set ALARM_API_VALIDATE_PORT." >&2
  exit 1
fi

# --- 2. Spawn the simulator. ---
echo "→ booting alarm-api simulator on :${PORT} (log: ${LOG_FILE})"
ALARM_API_TOKEN="${TOKEN}" \
  uv run python -m connectors.alarm_api \
  >"${LOG_FILE}" 2>&1 &
SIM_PID=$!

# --- 3. Wait for /health (poll every 200ms, max 10s). ---
echo "→ waiting for /health"
for _ in $(seq 1 50); do
  if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
    echo "  ✓ simulator is up"
    break
  fi
  if ! kill -0 "${SIM_PID}" 2>/dev/null; then
    echo "✗ simulator died before /health responded. See log:" >&2
    exit 1
  fi
  sleep 0.2
done
if ! curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
  echo "✗ simulator did not respond to /health within 10s" >&2
  exit 1
fi

# --- 4. Run both collections. ---
echo "→ running postman/chaining/"
uv run python scripts/validate_api.py \
  --collection postman/chaining/Alarm-API-Chaining.postman_collection.json \
  --base-url "${BASE_URL}" \
  --token "${TOKEN}" \
  --report-dir newman-report

echo "→ running postman/scenarios/"
uv run python scripts/validate_api.py \
  --collection postman/scenarios/Alarm-API-Scenarios.postman_collection.json \
  --base-url "${BASE_URL}" \
  --token "${TOKEN}" \
  --report-dir newman-report

echo "PASS: validate-api"
