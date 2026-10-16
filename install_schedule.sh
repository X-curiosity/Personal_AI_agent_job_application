#!/usr/bin/env bash
# Install a macOS launchd job that refreshes Co-Apply GPT's local data
# (company snapshots + actively-hiring index) every 6 hours.
# Sources update at their own pace (the YC mirror is daily); this keeps local
# copies fresh without an always-on worker. The job runs through a login shell
# because macOS blocks a bare binary's file access to ~/Desktop under launchd.
# Undo with uninstall_schedule.sh.
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
LABEL="com.coapplygpt.refresh-data"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${PROJECT_DIR}/.job_assistant"
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-lc</string>
        <string>cd '${PROJECT_DIR}' &amp;&amp; exec .venv/bin/python -m tau_job_application refresh-data</string>
    </array>
    <key>StartInterval</key>
    <integer>21600</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/refresh.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/refresh.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed ${LABEL} — refresh-data runs every 6 hours and at login."
echo "Log: ${LOG_DIR}/refresh.log · Undo: ./uninstall_schedule.sh"
