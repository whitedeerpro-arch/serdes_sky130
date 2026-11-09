#!/bin/bash
# Status report of Claude's long runs every 30 min (read-only).  Restart after a reboot:
#   setsid nohup verification/maintenance/run_status.sh >/dev/null 2>&1 &
cd "$(dirname "$0")/../.." || exit 1
while true; do
  uv run python verification/maintenance/run_status.py >/dev/null 2>&1
  sleep 1800
done
