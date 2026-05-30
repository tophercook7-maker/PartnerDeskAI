#!/usr/bin/env bash
# automation/open_hub.sh
# ----------------------
# Start the PartnerDesk Hub on port 8787 if it isn't already running,
# then open it in the default browser. Idempotent: safe to run as many
# times as you want — won't spawn duplicate servers.
#
# Robust to being invoked from a .app bundle (where macOS launchd
# strips PATH to a minimal set that doesn't include the Python
# framework with the project's deps): _find_python actively probes
# each candidate for `import uvicorn, fastapi` and uses the first
# one that has them.
#
# Exit codes:
#   0   Hub is up (already-running OR newly-started + readiness probe passed)
#   1   No suitable python3 found, OR readiness probe timed out
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

# --- Find a python3 that actually has the project's deps -------------------
# Probes each candidate by running `python3 -c "import uvicorn, fastapi"`
# and returns the first one that succeeds. Prefers `command -v python3`
# (your shell's choice — fast path for terminal use) but falls back to
# common framework + homebrew + system paths so .app launches work too.
_find_python() {
    local candidate
    for candidate in \
        "$(command -v python3 2>/dev/null)" \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3 \
        /usr/bin/python3 \
    ; do
        [[ -n "$candidate" && -x "$candidate" ]] || continue
        if "$candidate" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

# Probe whether the Hub is already responding.
# -f       → exit non-zero on HTTP errors
# -s       → silence progress output
# --max-time → cap so a hung port can't stall the launcher
if curl -fs --max-time 2 "${URL}/api/status" >/dev/null 2>&1; then
    echo "Hub already running."
else
    PY=$(_find_python) || {
        echo "ERROR: no python3 with uvicorn+fastapi found." >&2
        echo "  Tried: shell PATH, framework Python (Current/3.14/3.13/3.12)," >&2
        echo "         homebrew (/opt/homebrew/bin), /usr/local/bin, /usr/bin." >&2
        echo "  Install: pip3 install fastapi uvicorn jinja2 openai python-dotenv" >&2
        exit 1
    }
    echo "Starting Hub on port ${PORT} using ${PY}…"
    mkdir -p logs
    nohup "$PY" -m uvicorn hub.app:app \
        --host 127.0.0.1 --port "${PORT}" \
        > logs/hub.out.log 2> logs/hub.err.log &

    # Poll for readiness so the browser doesn't open before the server
    # is responding. Cap at 10 seconds (20 × 0.5s). Track success in a
    # flag so we can fail-fast if it never comes up.
    ready=false
    for _ in $(seq 1 20); do
        if curl -fs --max-time 1 "${URL}/api/status" >/dev/null 2>&1; then
            ready=true
            break
        fi
        sleep 0.5
    done
    if [[ "$ready" != true ]]; then
        echo "ERROR: Hub did not become ready on ${URL} within 10 seconds." >&2
        echo "  Check logs/hub.err.log for uvicorn startup errors:" >&2
        tail -20 logs/hub.err.log 2>/dev/null | sed 's/^/    /' >&2
        exit 1
    fi
fi

# Open the browser. `open` is macOS-native; on other platforms it
# silently fails — we still print the URL so the user can paste it.
open "${URL}" 2>/dev/null || true

echo "PartnerDesk Hub is open at ${URL}"
