#!/bin/bash
# automation/hub_doctor.sh
# -----------------------
# Diagnostic snapshot of the PartnerDesk Hub. Read-only — never starts
# or stops anything, never modifies any file.
#
# Reports:
#   - Project path the doctor is running from
#   - Whether port 8787 is listening (and by which PID/command)
#   - PID from logs/hub.pid + whether that process is alive
#   - Whether /api/status responds
#   - Last 40 lines of logs/hub.err.log
#   - Last 40 lines of logs/hub.out.log
#
# Usage:
#   bash automation/hub_doctor.sh
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT=8787
URL="http://127.0.0.1:${PORT}"

# --- Section helper ------------------------------------------------------
_section() {
    printf '\n==== %s ====\n' "$1"
}

echo "PartnerDesk Hub doctor"
echo "  time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  project path: ${ROOT}"

_section "Port ${PORT} listening?"
# lsof on macOS — prints owner PID + command if the port is bound.
LSOF_OUT=$(lsof -nP -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)
if [[ -n "$LSOF_OUT" ]]; then
    echo "  YES — listener(s):"
    echo "$LSOF_OUT" | sed 's/^/    /'
else
    echo "  NO — port ${PORT} not bound"
fi

_section "PID file (logs/hub.pid)"
PID_FILE="logs/hub.pid"
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE" 2>/dev/null | tr -d '[:space:]')
    if [[ -n "$PID" ]]; then
        echo "  ${PID_FILE} = ${PID}"
        if kill -0 "$PID" 2>/dev/null; then
            echo "  process ${PID} is ALIVE"
            ps -p "$PID" -o pid,etime,command 2>/dev/null | sed 's/^/    /'
        else
            echo "  process ${PID} is DEAD (stale PID file)"
        fi
    else
        echo "  ${PID_FILE} is empty"
    fi
else
    echo "  no ${PID_FILE} on disk"
fi

_section "/api/status response"
if curl -fs --max-time 2 "${URL}/api/status" >/dev/null 2>&1; then
    echo "  Hub OK — ${URL}/api/status responds with 200"
else
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "${URL}/api/status" 2>/dev/null || echo "no-connection")
    echo "  Hub NOT responding (status: ${code})"
fi

_section "logs/hub.err.log (last 40 lines)"
if [[ -f logs/hub.err.log ]]; then
    tail -40 logs/hub.err.log | sed 's/^/  /'
else
    echo "  (no logs/hub.err.log on disk)"
fi

_section "logs/hub.out.log (last 40 lines)"
if [[ -f logs/hub.out.log ]]; then
    tail -40 logs/hub.out.log | sed 's/^/  /'
else
    echo "  (no logs/hub.out.log on disk)"
fi

echo
echo "(read-only — nothing was started, stopped, or modified)"
