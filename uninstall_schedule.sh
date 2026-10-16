#!/usr/bin/env bash
set -euo pipefail
LABEL="com.coapplygpt.refresh-data"
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null && echo "Removed ${LABEL}" || echo "Not installed."
rm -f "$HOME/Library/LaunchAgents/${LABEL}.plist"
