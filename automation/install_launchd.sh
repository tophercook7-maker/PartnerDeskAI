#!/usr/bin/env bash
#
# install_launchd.sh
# ------------------
# One-shot macOS launchd installer for PartnerDeskAI's daily run.
#
# Writes ~/Library/LaunchAgents/com.mixedmakershop.partnerdeskai.daily.plist
# so the system runs `python3 <repo>/automation/daily_ops.py` every day at
# 09:00 local time. Output is captured to <repo>/logs/launchd.out.log and
# launchd.err.log.
#
# Idempotent: safe to re-run. Each run overwrites the plist and reloads the
# agent (unload errors are ignored so the first run works on a clean system).
#
# This script does NOT run daily_ops.py itself. It only installs the schedule.
#
# PROJECT_DIR is derived from this script's own location, so moving the repo
# only requires re-running install_launchd.sh from the new location.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.mixedmakershop.partnerdeskai.daily.plist"
LABEL="com.mixedmakershop.partnerdeskai.daily"

# Resolve the absolute path to python3 — launchd does not search PATH, so
# the plist must point at a concrete binary.
PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "Error: python3 not found in PATH" >&2
    exit 1
fi

# Make sure the directories launchd needs already exist.
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/logs"

# Write the plist. Variables expand inside the heredoc, so the file
# contains absolute paths only — no $ENV references at runtime.
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_BIN}</string>
        <string>${PROJECT_DIR}/automation/daily_ops.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>9</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>RunAtLoad</key><false/>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/launchd.err.log</string>
</dict>
</plist>
EOF

# Unload any existing agent first. If nothing is loaded, this is a no-op —
# `|| true` swallows that error so re-runs stay clean under `set -e`.
launchctl unload "$PLIST" 2>/dev/null || true

# Load the freshly written plist.
launchctl load "$PLIST"

echo "Installed launchd agent: ${LABEL}"
echo "Runs daily at 09:00"
echo "Command: python3 ${PROJECT_DIR}/automation/daily_ops.py"
