#!/bin/bash
# Read-only VM health log, one line every 600 s: load, available memory, free swap, total ngspice RSS.
# Start after a reboot:  setsid nohup verification/maintenance/vm_health.sh >/dev/null 2>&1 &
cd "$(dirname "$0")/../.." || exit 1
LOG=results/maintenance/vm_health/health.log
mkdir -p "$(dirname "$LOG")"
echo "$(date '+%F %T') start (boot $(uptime -s))" >> "$LOG"
while true; do
  read -r l1 l5 l15 _ < /proc/loadavg
  avail=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
  swap=$(awk '/SwapFree/ {print int($2/1024)}' /proc/meminfo)
  rss=0; for p in $(pgrep -x ngspice); do r=$(awk '/VmRSS/ {print int($2/1024)}' /proc/$p/status 2>/dev/null); rss=$((rss + ${r:-0})); done
  echo "$(date '+%F %T') load $l1 $l5 $l15 mem_avail_MB $avail swap_free_MB $swap ngspice_rss_MB $rss" >> "$LOG"
  sleep 600
done
