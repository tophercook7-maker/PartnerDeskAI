#!/usr/bin/env bash
# automation/open_hub.sh
# ----------------------
# Start the PartnerDesk Hub on port 8787 if it isn't already running,
# then open it in the default browser. Idempotent: safe to run as many
# times as you want — won't spawn duplicate servers.
#
# Safety contract:
#   - Never calls OpenAI.
#   - Never posts anything publicly.
#   - Never modifies the database.
#   - Does NOT run Daily Ops.
#
# Usage:
#   bash automation/open_hub.sh
set -eu

PORT=8787
URL="http://127.0.0.1:${PORT}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Probe whether the Hub is already responding.
# -f       → exit non-zero on HTTP errors
# -s       → silence progress output
# --max-time → cap so a hung port can't stall the launcher
if curl -fs --max-time 2 "${URL}/api/status" >/dev/null 2>&1; then
    echo "Hub already running."
else
    echo "Starting Hub on port ${PORT}…"
    mkdir -p logs
    # Use `python3 -m uvicorn` so we don't depend on `uvicorn` being
    # on PATH — same invocation pattern used by the dev sessions.
    nohup python3 -m uvicorn hub.app:app \
        --host 127.0.0.1 --port "${PORT}" \
        > logs/hub.out.log 2> logs/hub.err.log &

    # Poll for readiness so the browser doesn't open before the server
    # is responding. Cap at 10 seconds (20 × 0.5s).
    for _ in $(seq 1 20); do
        if curl -fs --max-time 1 "${URL}/api/status" >/dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done
fi

# Open the browser. `open` is macOS-native; on other platforms it
# silently fails — we still print the URL so the user can paste it.
open "${URL}" 2>/dev/null || true

echo "PartnerDesk Hub is open at ${URL}"
